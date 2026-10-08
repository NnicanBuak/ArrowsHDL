"""Real Yosys synthesis, followed by a checked, bit-level Boolean netlist."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from arrowasm import MapError

ROOT = Path(__file__).resolve().parents[1]


def find_yosys() -> str:
    if os.environ.get("YOSYS"):
        return os.environ["YOSYS"]
    for name in ("yosys", "yowasp-yosys"):
        if found := shutil.which(name):
            return found
    local = ROOT / ".venv" / ("Scripts/yowasp-yosys.exe" if os.name == "nt" else "bin/yowasp-yosys")
    if local.is_file():
        return str(local)
    raise MapError("Yosys не найден. Установите зависимости из ArrowsHDL/requirements.txt")


def synthesize(source: Path, top: str, timeout: float = 90) -> tuple[dict, str]:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", top):
        raise MapError("Некорректное имя верхнего модуля")
    text = source.read_text(encoding="utf-8-sig")
    # Yosys may ignore simulation timing: reject it before synthesis, not afterwards.
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
    if re.search(r"\b(initial|always|always_ff|always_latch|always_comb|tri|inout|real|time|specify)\b|`|\$", code):
        raise MapError("MVP принимает комбинационные модули с assign; процессы, inout, директивы и системные задачи пока не поддерживаются")
    if re.search(r"\b(?:[0-9]+)?'[sS]?[bBoOdDhH][0-9a-fA-F_]*[xXzZ?]", code):
        raise MapError("Неопределённые значения x/z не поддерживаются")
    # Module parameter declarations and overrides are not simulation delays.
    # Balance parentheses so expressions inside parameter values remain valid.
    parameter_types = set(re.findall(r"\bmodule\s+(\w+)\s*#\s*\(", code))
    without_parameters = list(code)
    for match in re.finditer(r"\b(?:module\s+)?(\w+)\s*#\s*\(", code):
        if match.group(1) not in parameter_types:
            continue
        end, depth = match.end(), 1
        while end < len(code) and depth:
            depth += (code[end] == '(') - (code[end] == ')')
            end += 1
        declaration = bool(re.match(r'module\s', match.group(0)))
        instance = re.match(r"\s+[A-Za-z_][A-Za-z0-9_$]*\s*\(", code[end:])
        if not depth and (declaration or instance):
            without_parameters[code.index('#', match.start(), match.end())] = ' '
    without_parameters = ''.join(without_parameters)
    if "#" in without_parameters:
        raise MapError("Задержки # в исходнике не поддерживаются")
    with tempfile.TemporaryDirectory(prefix="arrows-yosys-") as folder:
        work = Path(folder)
        (work / "design.v").write_text(text, encoding="utf-8")
        script = f"read_verilog design.v; hierarchy -check -top {top}; proc; check -assert; write_json hierarchy.json; synth -top {top} -flatten -noabc; check -assert; write_json netlist.json"
        result = subprocess.run([find_yosys(), "-Q", "-T", "-p", script], cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        if result.returncode:
            raise MapError("Yosys: " + (result.stderr or result.stdout)[-4000:].strip())
        data = json.loads((work / "netlist.json").read_text(encoding="utf-8"))
        data['hierarchy_modules']=json.loads((work/'hierarchy.json').read_text(encoding='utf-8'))['modules']
        return normalize(data, top), result.stdout


def normalize(raw: dict, top: str) -> dict:
    module = raw["modules"].get(top)
    if module is None:
        raise MapError(f"В результате Yosys отсутствует модуль {top}")
    nodes, inputs, outputs, used, scopes = [], {}, {}, set(), []

    def bit(value):
        if value in ("0", "1"):
            return "const" + value
        if type(value) is int:
            return "n" + str(value)
        raise MapError(f"Неопределённый бит Yosys: {value}")

    def emit(name, op, args, output, origin=None):
        nodes.append({"id": name, "op": op, "inputs": args, "output": output, "origin": origin})

    for name, port in sorted(module.get("ports", {}).items()):
        bits = [bit(v) for v in port["bits"]]
        indices = list(range(port.get("offset", 0), port.get("offset", 0) + len(bits)))
        if port.get("upto"):
            indices.reverse()
        entries = [{"index": i, "net": net} for i, net in zip(indices, bits)]
        if port["direction"] == "input":
            if any(net in used or net.startswith("const") for net in bits):
                raise MapError("Входные биты должны иметь независимые источники")
            inputs[name] = entries
            used.update(bits)
        elif port["direction"] == "output":
            outputs[name] = entries
        else:
            raise MapError("Двунаправленный порт не поддерживается")

    for name, cell in sorted(module.get("cells", {}).items()):
        kind = cell["type"]
        connections = cell["connections"]
        if kind == "$scopeinfo":
            # Flatten preserves instance/module attributes in this non-electrical
            # cell. Keep its provenance without treating it as a logic element.
            if connections or cell.get("port_directions"):
                raise MapError(f"Служебная запись иерархии имеет электрические порты: {name}")
            attrs = cell.get("attributes", {})
            scopes.append({"name": name, "module": attrs.get("module"),
                           "source": attrs.get("module_src"), "instance_source": attrs.get("cell_src")})
            continue
        if kind not in {"$_BUF_", "$_NOT_", "$_AND_", "$_OR_", "$_XOR_", "$_XNOR_", "$_NAND_", "$_NOR_", "$_MUX_"}:
            raise MapError(f"Неподдерживаемая клетка Yosys {kind}: {name}")
        if any(len(values) != 1 for values in connections.values()):
            raise MapError(f"Ожидается битовая клетка: {name}")
        c = {key: bit(values[0]) for key, values in connections.items()}
        y, a, origin = c["Y"], c["A"], cell.get("attributes", {}).get("src")
        if y in used or y.startswith("const"):
            raise MapError(f"Повторный источник сигнала {y}")
        used.add(y)
        op = kind[2:-1]
        if op in ("BUF", "NOT"):
            emit(name, op, [a], y, origin)
        elif op in ("AND", "OR", "XOR"):
            emit(name, op, [a, c["B"]], y, origin)
        elif op in ("NAND", "NOR", "XNOR"):
            tmp = "tmp:" + name
            emit(name + ":gate", {"NAND": "AND", "NOR": "OR", "XNOR": "XOR"}[op], [a, c["B"]], tmp, origin)
            emit(name, "NOT", [tmp], y, origin)
        else:
            prefix = "tmp:" + name
            emit(name + ":select", "NOT", [c["S"]], prefix + ":s", origin)
            emit(name + ":a", "AND", [a, prefix + ":s"], prefix + ":a", origin)
            emit(name + ":b", "AND", [c["B"], c["S"]], prefix + ":b", origin)
            emit(name, "OR", [prefix + ":a", prefix + ":b"], y, origin)

    # Give every output bit its own physical terminal, even when HDL aliases outputs.
    for name, entries in outputs.items():
        for entry in entries:
            net = f"port:{name}:{entry['index']}"
            emit(net, "BUF", [entry["net"]], net)
            entry["net"] = net
    available = {entry["net"] for entries in inputs.values() for entry in entries} | {"const0", "const1"}
    ordered, pending = [], nodes[:]
    while pending:
        ready = [node for node in pending if set(node["inputs"]) <= available]
        if not ready:
            raise MapError("Обратная связь или сигнал без источника в логическом графе")
        for node in ready:
            if node["output"] in available:
                raise MapError(f"Повторный источник {node['output']}")
            available.add(node["output"])
            ordered.append(node)
            pending.remove(node)
    if not outputs:
        raise MapError("У схемы должен быть хотя бы один выход")
    graph = {"schema": 1, "top": top, "creator": raw.get("creator"), "inputs": inputs, "outputs": outputs, "nodes": ordered}
    if scopes:
        graph["scopes"] = scopes
        # Preserve named buses and real module boundaries before bit mapping
        # destroys the instance names of individual logic cells.
        names=module.get('netnames',{})
        known=lambda v: type(v) is int or v in ('0','1')
        graph['wire_names']={name:[{'index':i+wire.get('offset',0),'net':bit(v)}
                                  for i,v in enumerate(wire['bits']) if known(v)]
                             for name,wire in sorted(names.items()) if not name.startswith('$')}
        by_net={node['output']:node for node in ordered}
        hierarchy=raw.get('hierarchy_modules',{})
        instances=[]
        for scope in scopes:
            interface={'inputs':{},'outputs':{}}
            for port,definition in hierarchy.get(scope['module'],{}).get('ports',{}).items():
                entries=graph['wire_names'].get(scope['name']+'.'+port,[])
                direction=definition['direction']+'s'
                if direction in interface:interface[direction][port]=entries
            stop={e['net'] for es in interface['inputs'].values() for e in es}
            pending=[e['net'] for es in interface['outputs'].values() for e in es]
            owned=set()
            while pending:
                net=pending.pop()
                if net in stop or net not in by_net:continue
                node=by_net[net]
                if node['id'] in owned:continue
                owned.add(node['id']);pending.extend(node['inputs'])
            instances.append(dict(scope,**interface,nodes=sorted(owned)))
        if any(instance['nodes'] for instance in instances):
            graph['instances']=instances
            for node in ordered:
                candidates=[s['name'] for s in instances if node['id'] in s['nodes']]
                if candidates:node['scope']=min(candidates,key=lambda name:(name.count('.'),name))
    return graph
