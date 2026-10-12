"""Real Yosys synthesis, followed by a checked, bit-level Boolean netlist."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from arrowshdl.arrowasm import MapError

ROOT = Path(__file__).resolve().parents[2]


def find_yosys() -> str:
    if os.environ.get("YOSYS"):
        return os.environ["YOSYS"]
    installed = Path(sys.executable).parent / ('yowasp-yosys.exe' if os.name == 'nt' else 'yowasp-yosys')
    if installed.is_file():
        return str(installed)
    for name in ("yosys", "yowasp-yosys"):
        if found := shutil.which(name):
            return found
    local = ROOT / ".venv" / ("Scripts/yowasp-yosys.exe" if os.name == "nt" else "bin/yowasp-yosys")
    if local.is_file():
        return str(local)
    raise MapError("Yosys not found. Install the ArrowsHDL dependencies")


def _quoted(path):
    value = str(path).replace("\\", "/")
    if any(c in value for c in ('"', "\n", "\r", ";")):
        raise MapError("Invalid path for Yosys")
    return '"' + value + '"'


def _validate_sources(sources):
    # Frontends must never silently erase simulation timing or initialization.
    # Combinational processes, macros and standard elaboration are allowed.
    for source in sources:
        code = re.sub(r"/\*.*?\*/|//[^\n]*", "", source.read_text(encoding="utf-8-sig"), flags=re.S)
        if re.search(r"\b(initial|specify|real|realtime|force|release)\b", code):
            raise MapError(f"{source}: simulation-only initialization/timing is unsupported")
        if re.search(r"#\s*(?:[0-9]|'|[A-Za-z_])", code):
            raise MapError(f"{source}: simulation delays are unsupported")
        if re.search(r'\b(?:assign|buf|not|and|or|xor|nand|nor|xnor)\s*#', code):
            raise MapError(f'{source}: operator and primitive delays are unsupported')


def elaborate(sources, top, timeout=90, *, standard="1800-2023", include_dirs=(), defines=(), parameters=None, blackbox_modules=()):
    from arrowshdl.standards import check_standard
    check_standard(standard)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", top):
        raise MapError("Invalid top module name")
    sources = [Path(sources)] if isinstance(sources, (str, Path)) else list(map(Path, sources))
    if not sources:
        raise MapError("No source files specified")
    sources = [p.resolve() for p in sources]
    _validate_sources(sources)
    library = Path(__file__).parent / "library/arrows.v"
    params = parameters or {}
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k) or not re.fullmatch(r"[-+0-9A-Za-z_'\[\]:]+", str(v)) for k,v in params.items()):
        raise MapError("Invalid parameter override")
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:=[-+0-9A-Za-z_']+)?", v) for v in defines):
        raise MapError("Invalid macro definition")
    # WASI sees the working directory; stage inputs with relative paths so native
    # Yosys and YoWASP use the same command on Windows, Linux and macOS.
    with tempfile.TemporaryDirectory(prefix="arrowshdl-inputs-") as staged:
        stage = Path(staged)
        stage_paths = []
        stage_includes = []
        for index, parent in enumerate(dict.fromkeys([*(p.parent for p in sources), *map(Path, include_dirs)])):
            target = stage / f"include{index}"
            target.mkdir()
            for header in parent.rglob('*'):
                if header.is_file() and header.suffix in ('.vh', '.svh', '.h', '.inc'):
                    destination = target / header.relative_to(parent)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(header, destination)
            stage_includes.append(target.name)
        for index, source in enumerate([library, *sources]):
            name = f"source{index}{source.suffix}"
            (stage / name).write_text(source.read_text(encoding='utf-8-sig'), encoding='utf-8')
            stage_paths.append(name)
        return _elaborate_staged(stage, stage_paths, stage_includes, top, timeout, standard, defines, params, blackbox_modules)


def _elaborate_staged(stage, files, include_dirs, top, timeout, standard, defines, params, blackbox_modules=()):
    inc = ' '.join('-I ' + (_quoted(p) if standard == '1364-2005' else p) for p in include_dirs)
    defs = ' '.join('-D ' + v for v in defines)
    paths = ' '.join(_quoted(p) if standard == '1364-2005' else p for p in files)
    if standard == "1364-2005":
        read = f"read_verilog {inc} {defs} {paths}; "
        for key,value in params.items():
            read += f"chparam -set {key} {value} {top}; "
        for module in blackbox_modules:
            read += f'blackbox {module}; '
    else:
        overrides = ' '.join(f'-G {k}={v}' for k,v in params.items())
        boxes = ' '.join('--blackboxed-module '+v for v in blackbox_modules)
        read = f"read_slang -j 1 --std {standard} --keep-hierarchy --empty-blackboxes --top {top} {inc} {defs} {overrides} {boxes} {paths}; "
    script = read + ("proc; write_json hierarchy.json" if blackbox_modules else
                     f"hierarchy -check -top {top}; proc; check -assert; write_json hierarchy.json")
    result = subprocess.run([find_yosys(), "-Q", "-T", "-p", script], cwd=stage, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if result.returncode:
        raise MapError("Yosys: " + result.stdout[-3000:].strip() + "\n" + result.stderr[-3000:].strip())
    raw = json.loads((stage / "hierarchy.json").read_text(encoding="utf-8"))
    # Slang reports connected widths before Yosys can silently resize them.
    for module in raw['modules'].values():
        for name, cell in module.get('cells', {}).items():
            declaration = raw['modules'].get(cell['type'])
            if not declaration:
                continue
            for port, desc in declaration.get('ports', {}).items():
                connected = cell.get('connections', {}).get(port)
                if connected is None or len(connected) != len(desc['bits']):
                    raise MapError(f'{name}.{port}: incompatible width or missing port')
                direction = cell.get('port_directions', {}).get(port)
                if direction and direction != desc['direction']:
                    raise MapError(f'{name}.{port}: incompatible port direction')
    if 'arrows_cell' in raw['modules']:
        # Slang keeps actual black-box instance parameters but omits defaults
        # from the declaration. RTLIL hierarchy needs those at object linking.
        raw['modules']['arrows_cell']['parameter_default_values'] = {
            key: format(value, '032b') for key,value in
            {'TYPE': 1, 'X': 0, 'Y': 0, 'ROTATION': 0, 'MIRRORED': 0}.items()}
    for name, defaults in (('arrows_logic', {'OP':1}), ('arrows_timer', {'TICKS':1})):
        if name in raw['modules']:
            raw['modules'][name]['parameter_default_values'] = {k:format(v,'032b') for k,v in defaults.items()}
    return raw, result.stdout


def synthesize_raw(raw, top, timeout=90):
    native = any(c['type'] == 'arrows_cell' or 'arrows_cell' in c['type'] and c['type'].startswith('$paramod')
                 for m in raw['modules'].values() for c in m.get('cells', {}).values())
    if native:
        from arrowshdl.physical import normalize_physical_hierarchy
        return normalize_physical_hierarchy(raw, top), 'Expanded structural RTLIL hierarchy; native tick paths preserved\n'
    # JSON import does not elaborate parameterized blackboxes. Specialize
    # technology declarations ourselves before Boolean synthesis; parameters
    # remain attached to the declaration and native instances remain distinct.
    from copy import deepcopy
    raw = deepcopy(raw)
    native_names = {'arrows_logic','arrows_detector','arrows_edge','arrows_rise','arrows_timer','arrows_impulse','arrows_clock','arrows_register','arrows_latch'}
    additions = {}
    for module in raw['modules'].values():
        for cell in module.get('cells', {}).values():
            name = cell['type']
            if name not in native_names:
                continue
            definition = raw['modules'][name]
            params = dict(definition.get('parameter_default_values', {}), **cell.get('parameters', {}))
            token = name + '__' + '_'.join(k+'_'+str(v) for k,v in sorted(params.items()))
            specialized = deepcopy(definition)
            specialized['parameter_default_values'] = params
            specialized.setdefault('attributes', {})['arrowshdl_primitive'] = name
            additions[token] = specialized
            cell['type'] = token
            cell['parameters'] = {}
            cell.setdefault('attributes', {})['keep'] = '1'
    raw['modules'].update(additions)
    with tempfile.TemporaryDirectory(prefix="arrowshdl-link-") as folder:
        work = Path(folder)
        (work / "input.json").write_text(json.dumps(raw), encoding="utf-8")
        native = any(c['type'] == 'arrows_cell' or 'arrows_cell' in c['type'] and c['type'].startswith('$paramod')
                     for m in raw['modules'].values() for c in m.get('cells', {}).values())
        if native:
            # Fixed structural designs have already been elaborated. Optimizing
            # their tick paths as combinational logic would change behavior.
            script = "read_json input.json; flatten; write_json netlist.json"
        else:
            script = f"read_json input.json; hierarchy -check -top {top}; synth -top {top} -flatten -noabc; check -assert; write_json netlist.json"
        result = subprocess.run([find_yosys(), "-Q", "-T", "-p", script], cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        if result.returncode:
            raise MapError("Yosys: " + (result.stderr.strip() or result.stdout)[-4000:].strip())
        data = json.loads((work / "netlist.json").read_text(encoding="utf-8"))
        data['hierarchy_modules'] = raw['modules']
        return normalize(data, top), result.stdout


def synthesize(source, top, timeout=90, **options):
    raw, log = elaborate(source, top, timeout, **options)
    graph, synth_log = synthesize_raw(raw, top, timeout)
    return graph, log + synth_log


def normalize(raw: dict, top: str) -> dict:
    module = raw["modules"].get(top)
    if module is None:
        raise MapError(f"Yosys output does not contain module {top}")
    if any(c['type'] == 'arrows_cell' or c['type'].startswith('$paramod\\arrows_cell') for c in module.get('cells', {}).values()):
        from arrowshdl.physical import normalize_physical
        return normalize_physical(raw, top)
    nodes, inputs, outputs, used, scopes = [], {}, {}, set(), []
    tick = False

    def bit(value):
        if value in ("0", "1"):
            return "const" + value
        if type(value) is int:
            return "n" + str(value)
        raise MapError(f"Undefined Yosys bit: {value}")

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
                raise MapError("Input bits must have independent drivers")
            inputs[name] = entries
            used.update(bits)
        elif port["direction"] == "output":
            outputs[name] = entries
        else:
            raise MapError("Bidirectional ports are unsupported")

    for name, cell in sorted(module.get("cells", {}).items()):
        kind = cell["type"]
        connections = cell["connections"]
        native_kind = raw['modules'].get(kind,{}).get('attributes',{}).get('arrowshdl_primitive') or next((n for n in ('arrows_logic','arrows_detector','arrows_edge','arrows_rise','arrows_timer','arrows_impulse','arrows_clock','arrows_register','arrows_latch')
                            if kind == n or kind.startswith('$paramod') and ('\\'+n+'\\' in kind or kind.endswith('\\'+n))), kind)
        if native_kind in ('arrows_register','arrows_latch'):
            outputs_q=connections['Q']
            for index,value in enumerate(outputs_q):
                y=bit(value)
                if y in used or y.startswith('const'): raise MapError(name+': duplicate driver')
                used.add(y)
                args=[bit(connections['load'][0]),bit(connections['D'][index])] if native_kind=='arrows_register' else [bit(connections['set'][0]),bit(connections['clear'][0])]
                nodes.append(dict(id=name+f'[{index}]',op='REGISTER' if native_kind=='arrows_register' else 'LATCH',inputs=args,output=y,native=True,ticks=1))
            tick=True
            continue
        if native_kind in ('arrows_logic', 'arrows_detector', 'arrows_edge', 'arrows_rise', 'arrows_timer', 'arrows_impulse','arrows_clock'):
            from arrowshdl.physical import parameter
            params = dict(raw['modules'].get(kind, {}).get('parameter_default_values', {}), **cell.get('parameters', {}))
            op = {'arrows_detector': 'DETECTOR', 'arrows_edge': 'EDGE', 'arrows_rise': 'RISE',
                  'arrows_timer': 'TIMER', 'arrows_impulse': 'IMPULSE','arrows_clock':'CLOCK'}.get(native_kind)
            if native_kind == 'arrows_logic':
                op = {1:'OR', 2:'SOURCE', 4:'DELAY', 5:'DETECTOR', 9:'IMPULSE', 15:'NOT',
                      16:'ATLEAST2', 17:'XOR', 18:'SET', 19:'TOGGLE', 20:'RANDOM', 24:'BUTTON'}.get(parameter(params.get('OP'), 1))
                if not op:
                    raise MapError(f'{name}: operation requires a physical template')
                if any(v != '0' for v in connections.get('B', [])):
                    raise MapError(f'{name}: blocking inputs require a physical template')
            values = connections.get('S' if op == 'DETECTOR' and native_kind == 'arrows_logic' else 'I', [])
            args = [bit(v) for v in values if v != '0']
            y = bit(connections['O'][0])
            if y in used or y.startswith('const'):
                raise MapError(f'{name}: duplicate signal driver')
            used.add(y)
            nodes.append(dict(id=name, op=op, inputs=args, output=y, native=True,
                              ticks=parameter(params.get('PERIOD' if op=='CLOCK' else 'TICKS'), 20 if op=='CLOCK' else 1)))
            tick = True
            continue
        if kind == "$scopeinfo":
            # Flatten preserves instance/module attributes in this non-electrical
            # cell. Keep its provenance without treating it as a logic element.
            if connections or cell.get("port_directions"):
                raise MapError(f"Hierarchy metadata record has electrical ports: {name}")
            attrs = cell.get("attributes", {})
            rtlil_module = attrs.get('module')
            original = raw.get('hierarchy_modules', {}).get(rtlil_module, {}).get('attributes', {}).get('hdlname')
            module_name = original or (rtlil_module.split('$' + top + '.')[0] if isinstance(rtlil_module, str) else rtlil_module)
            scopes.append({"name": name, "module": module_name, "rtlil_module": rtlil_module,
                           "source": attrs.get("module_src"), "instance_source": attrs.get("cell_src")})
            continue
        if kind not in {"$_BUF_", "$_NOT_", "$_AND_", "$_OR_", "$_XOR_", "$_XNOR_", "$_NAND_", "$_NOR_", "$_MUX_"}:
            raise MapError(f"Unsupported Yosys cell: {kind}: {name}")
        if any(len(values) != 1 for values in connections.values()):
            raise MapError(f"Expected a single-bit cell: {name}")
        c = {key: bit(values[0]) for key, values in connections.items()}
        y, a, origin = c["Y"], c["A"], cell.get("attributes", {}).get("src")
        if y in used or y.startswith("const"):
            raise MapError(f"Duplicate signal driver: {y}")
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
    if tick:
        available.update(n['output'] for n in nodes if n.get('native'))
        ordered = [n for n in nodes if n.get('native')]
        pending = [n for n in nodes if not n.get('native')]
        driven = available | {n['output'] for n in pending}
        missing = {v for n in nodes for v in n['inputs']} - driven
        if missing:
            raise MapError(f'Native signal has no driver: {sorted(missing)}')
    while pending:
        ready = [node for node in pending if set(node["inputs"]) <= available]
        if not ready:
            raise MapError("Feedback or undriven signal in logic graph")
        for node in ready:
            if node["output"] in available:
                raise MapError(f"Duplicate driver: {node['output']}")
            available.add(node["output"])
            ordered.append(node)
            pending.remove(node)
    if not outputs:
        raise MapError("Scheme must have at least one output")
    graph = {"schema": 1, "top": top, "creator": raw.get("creator"), "inputs": inputs, "outputs": outputs, "nodes": ordered}
    if tick:
        graph['kind'] = 'tick'
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
            for port,definition in hierarchy.get(scope.get('rtlil_module', scope['module']),{}).get('ports',{}).items():
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
