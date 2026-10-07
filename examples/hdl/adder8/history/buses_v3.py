"""Generic graph placement and multi-terminal A* routing; no adder-specific patterns.

The Boolean graph is unchanged. Deterministic annealing shortens connections,
then each net grows a directed wire tree. Jump arrows permit insulated crossings.
"""
from __future__ import annotations

from collections import defaultdict, deque
from heapq import heappop, heappush
from itertools import permutations
import math
import random

from arrowasm import Cell, MapError, validate_cell
from arrow_layout import GATE_TYPES, bounds_of, depth_of, destinations, edges
from mapdata import map_hash


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


# Only exactly representable output sets are allowed: no unused branch can later
# hit another wire, input source, or test target.
WIRE_CELLS = {}
for kind in (1, 6, 7, 8, 10, 11, 12, 13, 14):
    for mirrored in (False, True):
        for rotation in range(4):
            cell = Cell(kind, rotation, mirrored)
            WIRE_CELLS.setdefault(frozenset(destinations((0, 0), cell)), cell)


def wire_cell(position, targets):
    offsets = frozenset((x - position[0], y - position[1]) for x, y in targets)
    return WIRE_CELLS.get(offsets)


def arrange_free(netlist, pitch):
    sources, vertices = {}, []
    for entries in netlist["inputs"].values():
        for entry in entries:
            sources[entry["net"]] = len(vertices)
            vertices.append({"kind": "input", "net": entry["net"]})
    for net in ("const0", "const1"):
        if any(net in node["inputs"] for node in netlist["nodes"]):
            sources[net] = len(vertices)
            vertices.append({"kind": "constant", "net": net})
    for node in netlist["nodes"]:
        sources[node["output"]] = len(vertices)
        vertices.append({"kind": "gate", "node": node})
    count = len(vertices)
    columns = max(1, math.ceil(math.sqrt(count)))
    slots = [(x * pitch, y * pitch) for y in range(math.ceil(count / columns)) for x in range(columns)]
    # Empty slots participate in swaps, allowing holes where they reduce wire length.
    positions = slots[:]
    connections, incident = [], defaultdict(set)
    for i, vertex in enumerate(vertices):
        if vertex["kind"] == "gate":
            for net in vertex["node"]["inputs"]:
                pair = sources[net], i
                incident[pair[0]].add(len(connections))
                incident[pair[1]].add(len(connections))
                connections.append(pair)
    rng = random.Random(0)
    best, best_cost = positions[:], sum(manhattan(positions[a], positions[b]) for a, b in connections)
    total = best_cost
    iterations = max(2500, min(60_000, count * 800))
    for step in range(iterations):
        a, b = rng.sample(range(len(slots)), 2) if len(slots) > 1 else (0, 0)
        affected = incident[a] | incident[b]
        before = sum(manhattan(positions[connections[i][0]], positions[connections[i][1]]) for i in affected)
        positions[a], positions[b] = positions[b], positions[a]
        after = sum(manhattan(positions[connections[i][0]], positions[connections[i][1]]) for i in affected)
        delta = after - before
        temperature = pitch * (0.025 + 1.7 * (1 - step / iterations) ** 3)
        if delta <= 0 or rng.random() < math.exp(-delta / temperature):
            total += delta
            if total < best_cost:
                best, best_cost = positions[:], total
        else:
            positions[a], positions[b] = positions[b], positions[a]
    return vertices, best[:count], sources


def arrange_buses(netlist, pitch, mode="sides", seed=0, columns=None):
    """Fixed, ordered port bundles; only internal vertices may move.

Critical-chain edges receive extra weight. Ports are never individual annealing
variables, so no optimization can scatter a bus's bits.
    """
    sources, vertices, fixed = {}, [], {}
    output_nets = {e["net"] for entries in netlist["outputs"].values() for e in entries}
    internal_count = sum(n["output"] not in output_nets for n in netlist["nodes"])
    constants = [net for net in ("const0", "const1") if any(net in n["inputs"] for n in netlist["nodes"])]
    columns = columns or max(1, math.ceil(math.sqrt(internal_count + len(constants))))
    row_count = max(1, math.ceil((internal_count + len(constants)) / columns))
    right, bottom = (columns - 1) * pitch, (row_count - 1) * pitch
    cursors = {"left": 0, "top": 0, "bottom": 0}
    input_groups = sorted(netlist["inputs"].items(), key=lambda item: (-len(item[1]), item[0]))
    packed = {}
    packed_offset = 0
    for width in sorted({len(es) for _,es in input_groups if len(es)>1},reverse=True):
        cohort = [name for name,es in input_groups if len(es)==width]
        for index,name in enumerate(cohort):
            packed[name] = packed_offset+index,len(cohort)
        packed_offset += width*len(cohort)+2
    for group_index, (name, entries) in enumerate(input_groups):
        side = "left" if mode == "sides" or len(entries) == 1 else ("top" if mode in ("paired-top","flow-down") or group_index % 2 == 0 else "bottom")
        for bit_index,entry in enumerate(entries):
            v = {"kind": "input", "net": entry["net"]}
            index = len(vertices)
            sources[entry["net"]] = index
            offset = cursors[side]
            if mode in ("paired-top","flow-down") and name in packed:
                start,stride = packed[name]
                offset = start+bit_index*stride
            if side == "left":
                key, rotation, fixture = (-3, offset), 1, (-4, offset)
            elif side == "top":
                key, rotation, fixture = (offset, -3), 2, (offset, -4)
            else:
                key, rotation, fixture = (offset, bottom + 3), 0, (offset, bottom + 4)
            v.update(rotation=rotation, fixture=fixture)
            fixed[index] = key
            vertices.append(v)
            cursors[side] += 2
        cursors[side] += 2
    for net in constants:
        sources[net] = len(vertices)
        vertices.append({"kind": "constant", "net": net})
    output_positions, offset = {}, 0
    for name, entries in sorted(netlist["outputs"].items(), key=lambda item: (-len(item[1]), item[0])):
        for entry in entries:
            output_positions[entry["net"]] = (offset,bottom+3) if mode == "flow-down" else (right+3,offset)
            offset += 2
        offset += 2
    for node in netlist["nodes"]:
        index = len(vertices)
        sources[node["output"]] = index
        vertices.append({"kind": "gate", "node": node, "rotation": 2 if mode == "flow-down" and node["output"] in output_positions else 1})
        if node["output"] in output_positions:
            fixed[index] = output_positions[node["output"]]
    movable = [i for i in range(len(vertices)) if i not in fixed]
    slots = [(x * pitch, y * pitch) for y in range(row_count) for x in range(columns)]
    # Empty slots are genuine movable holes; ports stay fixed outside the core.
    count = len(vertices)
    movable += list(range(count, count + len(slots) - len(movable)))
    positions = [None] * (count + len(slots) - (count-len(fixed)))
    for i, key in fixed.items():
        positions[i] = key
    for i, key in zip(movable, slots):
        positions[i] = key
    level, remaining = dict.fromkeys(sources, 0), dict.fromkeys(sources, 0)
    for node in netlist["nodes"]:
        level[node["output"]] = 1 + max(level[net] for net in node["inputs"])
    longest = max(level[net] for net in output_nets)
    for node in reversed(netlist["nodes"]):
        for net in node["inputs"]:
            remaining[net] = max(remaining[net], remaining[node["output"]] + 1)
    connections, incident = [], defaultdict(set)
    for node in netlist["nodes"]:
        target = sources[node["output"]]
        for net in node["inputs"]:
            pair = sources[net], target
            weight = 5 if level[net] + 1 + remaining[node["output"]] >= longest - 1 else 1
            incident[pair[0]].add(len(connections))
            incident[pair[1]].add(len(connections))
            connections.append((*pair, weight))

    def cost(edge):
        a, b, weight = connections[edge]
        ax, ay = positions[a]
        bx, by = positions[b]
        return weight * (abs(bx - ax - 1) + abs(by - ay))

    rng = random.Random(seed)
    best, total = positions[:], sum(cost(i) for i in range(len(connections)))
    best_cost = total
    iterations = max(2500, min(60_000, count * 650))
    for step in range(iterations):
        if len(movable) < 2:
            break
        a, b = rng.sample(movable, 2)
        affected = incident[a] | incident[b]
        before = sum(cost(i) for i in affected)
        positions[a], positions[b] = positions[b], positions[a]
        delta = sum(cost(i) for i in affected) - before
        temperature = pitch * (0.03 + 3 * (1-step/iterations) ** 3)
        if delta <= 0 or rng.random() < math.exp(-delta / temperature):
            total += delta
            if total < best_cost:
                best, best_cost = positions[:], total
        else:
            positions[a], positions[b] = positions[b], positions[a]
    return vertices, best[:count], sources


class Router:
    def __init__(self, netlist, pitch, max_cells, placement=None):
        self.netlist, self.max_cells = netlist, max_cells
        self.cells, self.owners, self.outs = {}, {}, {}
        self.gates, self.pins, self.roots, self.sinks = {}, {}, {}, defaultdict(list)
        self.reserved, self.inputs, self.outputs = set(), {}, {}
        vertices, positions, sources = placement or arrange_free(netlist, pitch)
        self.input_interfaces = {}
        self.output_interfaces = {}
        output_nets = {e["net"] for entries in netlist["outputs"].values() for e in entries}
        self.source_positions = {net: positions[i] for net, i in sources.items()}
        for vertex, (x, y) in zip(vertices, positions):
            if vertex["kind"] == "gate":
                node = vertex["node"]
                key = x, y
                self.add(key, "gate:" + node["id"], Cell(GATE_TYPES[node["op"]], vertex.get("rotation",1)))
                self.gates[key] = node
                if node["output"] in output_nets:
                    fixture = next(destinations(key,self.cells[key]))
                    self.reserved.add(fixture)
                    self.output_interfaces[node["output"]] = fixture
                else:
                    self.add((x + 1, y), node["output"])
                    self.roots[node["output"]] = x + 1, y
            elif vertex["kind"] == "input":
                self.add((x, y), vertex["net"])
                self.roots[vertex["net"]] = x, y
                fixture = vertex.get("fixture", (x - 1, y))
                self.reserved.add(fixture)
                self.input_interfaces[vertex["net"]] = {"fixture": list(fixture), "rotation": vertex.get("rotation", 1)}
            else:
                net = vertex["net"]
                if net == "const1":
                    self.add((x, y), "constant:const1", Cell(2, 1))
                    self.reserved.update({(x - 1, y), (x, y - 1), (x, y + 1)})
                    self.add((x + 1, y), net)
                    self.roots[net] = x + 1, y
                else:
                    self.add((x, y), net)
                    self.roots[net] = x, y
        for key, node in self.gates.items():
            x, y = key
            if node["output"] in output_nets:
                fx,fy = self.output_interfaces[node["output"]]
                candidates = [(2*x-fx,2*y-fy)]
            else:
                candidates = [(x - 1, y), (x, y - 1), (x, y + 1)]
            pins = min(permutations(candidates, len(node["inputs"])), key=lambda ps: sum(manhattan(self.source_positions[net], pin) for net, pin in zip(node["inputs"], ps)))
            self.pins[key] = list(pins)
            for net, pin in zip(node["inputs"], pins):
                self.add(pin, net)
                self.outs[pin].add(key)
                self.sinks[net].append(pin)
        for name, entries in netlist["inputs"].items():
            self.inputs[name] = [{"index": e["index"], "contact": list(self.roots[e["net"]]), **self.input_interfaces[e["net"]]} for e in entries]
        for name, entries in netlist["outputs"].items():
            self.outputs[name] = []
            for e in entries:
                x, y = self.source_positions[e["net"]]
                self.outputs[name].append({"index": e["index"], "contact": [x, y], "fixture": list(self.output_interfaces[e["net"]]), "rotation": 0})
        xs, ys = zip(*self.cells)
        self.bounds = min(xs), min(ys), max(xs), max(ys)
        self.fixed_cells = set(self.cells)
        self.fixed_outs = {key:set(values) for key,values in self.outs.items()}
        self.ripups = 0


    def add(self, key, owner, cell=None):
        if key in self.cells or key in self.reserved:
            raise MapError(f"Конфликт компактного размещения в {key}")
        if len(self.cells) >= self.max_cells:
            raise MapError(f"Схема превышает лимит {self.max_cells} клеток")
        self.cells[key], self.owners[key] = cell, owner
        if cell is None:
            self.outs[key] = set()

    def path(self, tree, goal, margin, soft=False):
        lo_x, lo_y, hi_x, hi_y = self.bounds
        net = self.owners[goal]
        heap, cost, previous = [], {}, {}
        for key in sorted(tree):
            if len(self.outs[key]) < 3:
                cost[key] = 0
                heappush(heap, (manhattan(key, goal) / 2, 0, key))
        while heap:
            _, spent, key = heappop(heap)
            if spent != cost[key]:
                continue
            if key == goal:
                path = [key]
                while path[-1] in previous:
                    path.append(previous[path[-1]])
                return list(reversed(path))
            for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)):
                for distance in ((1,) if dx and dy else (1, 2)):
                    next_key = key[0] + distance * dx, key[1] + distance * dy
                    if not (lo_x - margin <= next_key[0] <= hi_x + margin and lo_y - margin <= next_key[1] <= hi_y + margin):
                        continue
                    blocked = next_key in self.cells and next_key != goal
                    removable = soft and next_key not in self.fixed_cells and self.owners.get(next_key) != net
                    if next_key in self.reserved or (blocked and not removable):
                        continue
                    if key in tree and wire_cell(key, self.outs[key] | {next_key}) is None:
                        continue
                    added = 1 if distance == 1 and not (dx and dy) else 1.05
                    if blocked:
                        added += 20
                    candidate = spent + added
                    if candidate < cost.get(next_key, math.inf):
                        cost[next_key], previous[next_key] = candidate, key
                        heappush(heap, (candidate + manhattan(next_key, goal) / 2, candidate, next_key))
        return None

    def route(self, order=None):
        order = order or sorted(self.sinks, key=lambda net: (-len(self.sinks[net]), net))
        queue, attempts = deque(order), 0
        while queue:
            net = queue.popleft()
            attempts += 1
            if attempts > max(40, len(order)*3):
                raise MapError("Исчерпан бюджет перестройки проводов")
            self.clear_net(net)
            tree, pending = {self.roots[net]}, set(self.sinks[net])
            while pending:
                goal = min(pending, key=lambda p: (min(manhattan(p, start) for start in tree), p))
                path = None
                for margin in (3, 8, 16, 32):
                    path = self.path(tree, goal, margin)
                    if path:
                        break
                if path is None:
                    path = self.path(tree,goal,8,soft=True)
                    if path is None:
                        raise MapError(f"Не удалось проложить компактную цепь {net}")
                    blockers = sorted({self.owners[p] for p in path if p in self.cells and p not in self.fixed_cells and self.owners[p] != net})
                    for blocker in blockers:
                        self.clear_net(blocker)
                        if blocker not in queue:
                            queue.append(blocker)
                        self.ripups += 1
                    path = self.path(tree,goal,32)
                    if path is None:
                        raise MapError(f"Не удалось перестроить цепь {net}")
                for key in path[1:-1]:
                    self.add(key, net)
                for key, target in zip(path, path[1:]):
                    self.outs[key].add(target)
                tree.update(path)
                pending.remove(goal)
        for key, targets in self.outs.items():
            if not targets:
                # Unused inputs still have a physical contact; emit only into empty
                # space that is also free of Source/Target fixture positions.
                for dx, dy in ((1, 0), (0, -1), (0, 1), (-1, 0)):
                    dest = key[0] + dx, key[1] + dy
                    if dest not in self.cells and dest not in self.reserved:
                        targets.add(dest)
                        break
                else:
                    raise MapError(f"Не удалось изолировать неиспользуемый контакт {key}")
            self.cells[key] = wire_cell(key, targets)
            if self.cells[key] is None:
                raise MapError(f"Неподдерживаемое разветвление в {key}")
        for key, cell in self.cells.items():
            validate_cell(*key, cell)
        self.validate()
        return self.cells

    def clear_net(self, net):
        for key in [p for p,owner in self.owners.items() if owner == net]:
            if key in self.fixed_cells:
                self.outs[key] = set(self.fixed_outs[key])
            else:
                del self.cells[key],self.owners[key],self.outs[key]

    def validate(self):
        links, reverse = edges(self.cells), defaultdict(list)
        for key, targets in links.items():
            for target in targets:
                reverse[target].append(key)
                if target in self.gates:
                    if key not in self.pins[target]:
                        raise MapError(f"Посторонний сигнал у элемента {target}")
                elif key in self.gates:
                    if self.owners[target] != self.gates[key]["output"]:
                        raise MapError(f"Посторонний выход элемента {key}")
                elif self.owners[key] != self.owners[target] and self.owners[key] != "constant:" + self.owners[target]:
                    raise MapError(f"Короткое замыкание {key} → {target}")
        for key, pins in self.pins.items():
            if set(reverse[key]) != set(pins):
                raise MapError(f"Разрыв входов элемента {key}")
            for pin, net in zip(pins, self.gates[key]["inputs"]):
                if self.owners[pin] != net:
                    raise MapError(f"Неверный сигнал у элемента {key}")
        for net, root in self.roots.items():
            reached, todo = set(), [root]
            while todo:
                key = todo.pop()
                if key not in reached:
                    reached.add(key)
                    todo.extend(v for v in links[key] if self.owners[v] == net)
            if {key for key, owner in self.owners.items() if owner == net} - reached:
                raise MapError(f"Разрыв цепи {net}")


def place_compact(netlist, max_cells=100_000):
    failures, candidates = [], []
    configs = [("flow-down",5,seed) for seed in (0,1,2,5)] + [("paired-top",5,1),("top-bottom",5,0)]
    for mode,pitch,seed in configs:
        try:
            router = Router(netlist,pitch,max_cells,arrange_buses(netlist,pitch,mode,seed))
            cells = router.route()
            manifest = {
                "schema": 1, "top": netlist["top"], "map_hash": map_hash(cells),
                "profile": "GraphDLC-01232bd", "verified_against_current_game": False,
                "inputs": router.inputs, "outputs": router.outputs,
                "settle_ticks": depth_of(cells) + 2, "cells": len(cells),
                "logic_nodes": len(netlist["nodes"]), "layout": "compact-buses-v2",
                "bounds": bounds_of(cells), "placement_pitch": pitch,
                "port_layout": mode, "placement_seed": seed, "rerouted_nets": router.ripups,
                "gate_labels": [{"at": list(key), "op": node["op"], "id": node["id"]} for key, node in router.gates.items()],
            }
            candidates.append((cells,manifest))
        except MapError as error:
            failures.append(str(error))
    if not candidates:
        # Keep buses constrained even when a larger routing core is necessary.
        for pitch in (6,8):
            try:
                router = Router(netlist,pitch,max_cells,arrange_buses(netlist,pitch,"flow-down",0))
                cells = router.route()
                manifest = {"schema":1,"top":netlist["top"],"map_hash":map_hash(cells),
                            "profile":"GraphDLC-01232bd","verified_against_current_game":False,
                            "inputs":router.inputs,"outputs":router.outputs,"settle_ticks":depth_of(cells)+2,
                            "cells":len(cells),"logic_nodes":len(netlist["nodes"]),"layout":"compact-buses-v2",
                            "bounds":bounds_of(cells),"placement_pitch":pitch,"port_layout":"flow-down",
                            "placement_seed":0,"rerouted_nets":router.ripups,
                            "gate_labels":[{"at":list(key),"op":node["op"],"id":node["id"]} for key,node in router.gates.items()]}
                candidates.append((cells,manifest))
                break
            except MapError as error:
                failures.append(str(error))
    if not candidates:
        raise MapError(f"Компактная трассировка не выполнена: {failures[-1]}")
    min_area = min(m["bounds"]["area"] for _,m in candidates)
    min_cells = min(len(c) for c,_ in candidates)
    eligible = [(c,m) for c,m in candidates if m["bounds"]["area"] <= min_area*1.25 and len(c) <= min_cells*1.2]
    # If the two independent bounds have no common candidate, choose a balanced
    # Pareto compromise instead of silently disabling either size constraint.
    if not eligible:
        eligible = [min(candidates,key=lambda cm:max(cm[1]["bounds"]["area"]/min_area,len(cm[0])/min_cells))]
    cells,manifest = min(eligible,key=lambda cm:(cm[1]["settle_ticks"],cm[1]["bounds"]["area"],len(cm[0])))
    manifest["optimization"] = {"objective":"min_ticks_with_compactness_limits",
        "area_factor":1.25,"cell_factor":1.2,
        "candidates":[{"cells":len(c),"area":m["bounds"]["area"],"ticks":m["settle_ticks"],"mode":m["port_layout"],"seed":m["placement_seed"]} for c,m in candidates]}
    return cells,manifest
