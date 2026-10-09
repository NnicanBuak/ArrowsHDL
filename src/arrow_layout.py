"""Physical placement, routing, and checks on every concrete arrow connection."""
from __future__ import annotations

from collections import defaultdict, deque

from arrowasm import Cell, MapError, validate_cell
from mapdata import map_hash

VECTORS = {1: [(0, -1)], 2: [(0, -1), (1, 0), (0, 1), (-1, 0)], 3: [(0, -1)], 4: [(0, -1)], 5: [(0, -1)], 6: [(0, -1), (0, 1)], 7: [(0, -1), (1, 0)], 8: [(0, -1), (1, 0), (-1, 0)], 9: [(0, -1), (1, 0), (0, 1), (-1, 0)], 10: [(0, -2)], 11: [(1, -1)], 12: [(0, -1), (0, -2)], 13: [(1, 0), (0, -2)], 14: [(0, -1), (1, -1)], 15: [(0, -1)], 16: [(0, -1)], 17: [(0, -1)], 18: [(0, -1)], 19: [(0, -1)], 20: [(0, -1)], 21: [(0, -1), (1, 0), (0, 1), (-1, 0)], 22: [(0, -1)], 23: [], 24: [(0, -1)], 25: []}
GATE_TYPES = {"BUF": 1, "OR": 1, "NOT": 15, "AND": 16, "MAJ": 16, "ATLEAST2": 16, "XOR": 17,
              "SET": 18, "TOGGLE": 19, "RANDOM": 20}


def destinations(position, cell):
    if cell.type not in VECTORS:
        raise MapError(f"Неизвестный элемент проверки трассировки: {cell.type}")
    for dx, dy in VECTORS[cell.type]:
        if cell.mirrored:
            dx = -dx
        for _ in range(cell.rotation):
            dx, dy = -dy, dx
        yield position[0] + dx, position[1] + dy


def edges(cells):
    return {key: [v for v in destinations(key, cell) if v in cells] for key, cell in cells.items()}


def depth_of(cells):
    links = edges(cells)
    incoming = dict.fromkeys(cells, 0)
    depths = dict.fromkeys(cells, 1)
    for targets in links.values():
        for target in targets:
            incoming[target] += 1
    queue = deque(sorted(key for key, count in incoming.items() if count == 0))
    count = 0
    while queue:
        key = queue.popleft()
        count += 1
        for target in links[key]:
            depths[target] = max(depths[target], depths[key] + 1)
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)
    if count != len(cells):
        raise MapError("В физической карте обнаружен цикл")
    return max(depths.values(), default=0)


def bounds_of(cells):
    xs, ys = zip(*cells)
    width, height = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
    return {"min": [min(xs), min(ys)], "max": [max(xs), max(ys)], "width": width, "height": height, "area": width * height}


def logic_core_metrics(cells,gates,output_nets):
    """Only computation and paths between gates; external port tails cost nothing.

Primary-input wires stop before the first gate. Output terminal buffers and
wires after the last gate are excluded. Constants that feed logic stay inside.
The complete map's settle bound remains a separate physical timing contract.
"""
    internal={p for p,n in gates.items() if n['output'] not in output_nets or n.get('op','BUF')!='BUF'}
    links=edges(cells)
    reverse={p:[] for p in cells}
    for p,targets in links.items():
        for q in targets:reverse[q].append(p)

    def reach(starts,graph):
        seen=set(starts)
        todo=deque(starts)
        while todo:
            for q in graph[todo.popleft()]:
                if q not in seen:
                    seen.add(q);todo.append(q)
        return seen

    constants={p for p,c in cells.items() if c.type==2}
    selected=reach(internal|constants,links)&reach(internal,reverse)
    core={p:cells[p] for p in selected}
    bounds=bounds_of(core) if core else {'min':None,'max':None,'width':0,'height':0,'area':0}
    return {'cells':len(core),'gates':len(internal),'bounds':bounds,'ticks':depth_of(core),
            'excluded_io_cells':len(cells)-len(core)}


def validate_connections(cells,owners,gates,pins,roots):
    """Check real physical edges, including multi-input gates and wire reachability."""
    links,reverse=edges(cells),defaultdict(list)
    for key,targets in links.items():
        for target in targets:
            reverse[target].append(key)
            if target in gates:
                if key not in pins[target]:raise MapError(f"Посторонний сигнал у элемента {target}")
            elif key in gates:
                if owners[target]!=gates[key]['output']:raise MapError(f"Посторонний выход элемента {key}")
            elif owners[key]!=owners[target] and owners[key]!='constant:'+owners[target]:
                raise MapError(f"Короткое замыкание {key} → {target}")
    for key,expected in pins.items():
        if set(reverse[key])!=set(expected):raise MapError(f"Разрыв входов элемента {key}")
        for pin,net in zip(expected,gates[key]['inputs']):
            if owners[pin]!=net:raise MapError(f"Неверный сигнал у элемента {key}")
    for net,root in roots.items():
        reached,todo=set(),[root]
        while todo:
            key=todo.pop()
            if key not in reached:
                reached.add(key)
                todo.extend(v for v in links[key] if owners[v]==net)
        if {key for key,owner in owners.items() if owner==net}-reached:raise MapError(f"Разрыв цепи {net}")
    depth_of(cells)


def place(netlist, max_cells=100_000, layout="compact", input_buses=None, input_bus_gap='auto'):
    from native_rules import validate_gate_rule
    for node in netlist['nodes']:validate_gate_rule(node)
    from copy import deepcopy
    from input_buses import configure, describe
    config = configure(netlist, input_buses, input_bus_gap)
    if config['groups']:
        if layout != 'compact':
            raise MapError('Группировка входов поддерживается в режиме compact')
        netlist = deepcopy(netlist)
        netlist['_input_bus_config'] = config
    if layout == "sparse":
        return place_sparse(netlist, max_cells)
    if layout != "compact":
        raise MapError(f"Неизвестный способ размещения: {layout}")
    from compact_layout import place_compact
    cells, meta = place_compact(netlist, max_cells)
    describe(netlist, meta)
    return cells, meta


def place_sparse(netlist, max_cells=100_000):
    from native_rules import validate_gate_rule
    for node in netlist['nodes']:validate_gate_rule(node)
    cells, owners, gate_positions, gate_pins = {}, {}, {}, {}
    inputs, outputs = {}, {}
    nets = [entry["net"] for entries in netlist["inputs"].values() for entry in entries]
    for const in ("const0", "const1"):
        if any(const in node["inputs"] for node in netlist["nodes"]):
            nets.append(const)
    nets += [node["output"] for node in netlist["nodes"]]
    rows = {net: i * 4 for i, net in enumerate(nets)}
    gate_y = len(nets) * 4 + 4
    consumers = defaultdict(list)
    starts, vertical = {}, set()
    last_x = 12 + max(0, len(netlist["nodes"]) - 1) * 16 + 12

    def add(key, cell, owner):
        if key in cells:
            raise MapError(f"Конфликт трассировки в {key}")
        validate_cell(*key, cell)
        cells[key], owners[key] = cell, owner
        if len(cells) > max_cells:
            raise MapError(f"Схема превышает лимит {max_cells} клеток")

    for name, entries in netlist["inputs"].items():
        inputs[name] = []
        for entry in entries:
            net, row = entry["net"], rows[entry["net"]]
            starts[net] = 0
            inputs[name].append({"index": entry["index"], "contact": [0, row], "fixture": [-1, row], "rotation": 1})
    for net in ("const0", "const1"):
        if net in rows:
            starts[net] = 0

    for i, node in enumerate(netlist["nodes"]):
        gx = 12 + i * 16
        gkey = gx, gate_y
        gate_positions[gkey] = node
        gate_pins[gkey] = []
        for pin, net in enumerate(node["inputs"]):
            x = gx - 4 if pin == 0 else gx
            row = rows[net]
            consumers[net].append(x)
            for y in range(row + 1, gate_y):
                key = x, y
                add(key, Cell(1, 2), net)
                vertical.add(key)
            if pin == 0:
                add((x, gate_y), Cell(1, 1), net)
                for px in range(x + 1, gx):
                    add((px, gate_y), Cell(1, 1), net)
                gate_pins[gkey].append((gx - 1, gate_y))
            else:
                gate_pins[gkey].append((gx, gate_y - 1))
        add(gkey, Cell(GATE_TYPES[node["op"]], 1), "gate:" + node["id"])
        net = node["output"]
        ox, row = gx + 4, rows[net]
        for x in range(gx + 1, ox):
            add((x, gate_y), Cell(1, 1), net)
        for y in range(row + 1, gate_y + 1):
            key = ox, y
            add(key, Cell(1, 0), net)
            vertical.add(key)
        starts[net] = ox

    for name, entries in netlist["outputs"].items():
        outputs[name] = []
        for entry in entries:
            row = rows[entry["net"]]
            outputs[name].append({"index": entry["index"], "contact": [last_x, row], "fixture": [last_x + 1, row], "rotation": 0})

    output_nets = {entry["net"] for entries in netlist["outputs"].values() for entry in entries}
    for net in nets:
        row, start = rows[net], starts[net]
        end = max(consumers[net] + ([last_x] if net in output_nets else [start]))
        crossings = {x for x, y in vertical if y == row and start <= x <= end}
        for x in range(start, end + 1):
            if x in crossings:
                continue
            type_id = 10 if x + 1 in crossings else (7 if x in consumers[net] else 1)
            if x == 0 and net == "const1":
                type_id = 2
            add((x, row), Cell(type_id, 1), net)

    # Check every concrete edge against net ownership, including crossings and fanout.
    links = edges(cells)
    reverse = defaultdict(list)
    for key, targets in links.items():
        for target in targets:
            reverse[target].append(key)
            if target in gate_positions:
                if key not in gate_pins[target]:
                    raise MapError(f"Посторонний сигнал у логического элемента {target}")
            elif key in gate_positions:
                if owners[target] != gate_positions[key]["output"]:
                    raise MapError(f"Посторонняя связь от элемента {key}")
            elif owners[key] != owners[target]:
                raise MapError(f"Короткое замыкание {key} → {target}")
    for key, pins in gate_pins.items():
        if set(reverse[key]) != set(pins):
            raise MapError(f"Не все входы логического элемента соединены: {key}")
        node = gate_positions[key]
        for pin, net in zip(pins, node["inputs"]):
            if owners[pin] != net:
                raise MapError(f"Неправильный сигнал на входе {key}")
    # A disconnected path of the right ownership is still a routing failure.
    for net in nets:
        start = (starts[net], rows[net])
        if net not in {e["net"] for entries in netlist["inputs"].values() for e in entries} and not net.startswith("const"):
            producer = next(key for key, node in gate_positions.items() if node["output"] == net)
            start = producer[0] + 1, producer[1]
        reached, todo = set(), [start]
        while todo:
            key = todo.pop()
            if key in reached:
                continue
            reached.add(key)
            todo += [v for v in links[key] if owners[v] == net]
        if {key for key, owner in owners.items() if owner == net} - reached:
            raise MapError(f"Разрыв цепи {net}")
    manifest = {
        "schema": 1, "top": netlist["top"], "map_hash": map_hash(cells),
        "profile": "GraphDLC-01232bd", "verified_against_current_game": False,
        "inputs": inputs, "outputs": outputs, "settle_ticks": depth_of(cells) + 2,
        "cells": len(cells), "logic_nodes": len(netlist["nodes"]),
        "layout": "sparse-buses-v1", "bounds": bounds_of(cells), "gate_labels": [{"at": list(key), "op": node["op"], "id": node["id"]} for key, node in gate_positions.items()],
    }
    from signal_metadata import describe_signals
    manifest['signals']=describe_signals(netlist,cells,owners,gate_positions)
    return cells, manifest
