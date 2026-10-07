"""Generic graph placement and multi-terminal A* routing; no adder-specific patterns.

The Boolean graph is unchanged. Deterministic annealing shortens connections,
then each net grows a directed wire tree. Jump arrows permit insulated crossings.
"""
from __future__ import annotations

from collections import defaultdict
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
for kind in (1, 6, 7, 8, 10, 12, 13):
    for mirrored in (False, True):
        for rotation in range(4):
            cell = Cell(kind, rotation, mirrored)
            WIRE_CELLS.setdefault(frozenset(destinations((0, 0), cell)), cell)


def wire_cell(position, targets):
    offsets = frozenset((x - position[0], y - position[1]) for x, y in targets)
    return WIRE_CELLS.get(offsets)


def arrange(netlist, pitch):
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


class Router:
    def __init__(self, netlist, pitch, max_cells):
        self.netlist, self.max_cells = netlist, max_cells
        self.cells, self.owners, self.outs = {}, {}, {}
        self.gates, self.pins, self.roots, self.sinks = {}, {}, {}, defaultdict(list)
        self.reserved, self.inputs, self.outputs = set(), {}, {}
        vertices, positions, sources = arrange(netlist, pitch)
        output_nets = {e["net"] for entries in netlist["outputs"].values() for e in entries}
        self.source_positions = {net: positions[i] for net, i in sources.items()}
        for vertex, (x, y) in zip(vertices, positions):
            if vertex["kind"] == "gate":
                node = vertex["node"]
                key = x, y
                self.add(key, "gate:" + node["id"], Cell(GATE_TYPES[node["op"]], 1))
                self.gates[key] = node
                if node["output"] in output_nets:
                    self.reserved.add((x + 1, y))
                else:
                    self.add((x + 1, y), node["output"])
                    self.roots[node["output"]] = x + 1, y
            elif vertex["kind"] == "input":
                self.add((x, y), vertex["net"])
                self.roots[vertex["net"]] = x, y
                self.reserved.add((x - 1, y))
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
            candidates = [(x - 1, y), (x, y - 1), (x, y + 1)]
            pins = min(permutations(candidates, len(node["inputs"])), key=lambda ps: sum(manhattan(self.source_positions[net], pin) for net, pin in zip(node["inputs"], ps)))
            self.pins[key] = list(pins)
            for net, pin in zip(node["inputs"], pins):
                self.add(pin, net)
                self.outs[pin].add(key)
                self.sinks[net].append(pin)
        for name, entries in netlist["inputs"].items():
            self.inputs[name] = [{"index": e["index"], "contact": list(self.roots[e["net"]]), "fixture": [self.roots[e["net"]][0] - 1, self.roots[e["net"]][1]], "rotation": 1} for e in entries]
        for name, entries in netlist["outputs"].items():
            self.outputs[name] = []
            for e in entries:
                x, y = self.source_positions[e["net"]]
                self.outputs[name].append({"index": e["index"], "contact": [x, y], "fixture": [x + 1, y], "rotation": 0})
        xs, ys = zip(*self.cells)
        self.bounds = min(xs), min(ys), max(xs), max(ys)

    def add(self, key, owner, cell=None):
        if key in self.cells or key in self.reserved:
            raise MapError(f"Конфликт компактного размещения в {key}")
        if len(self.cells) >= self.max_cells:
            raise MapError(f"Схема превышает лимит {self.max_cells} клеток")
        self.cells[key], self.owners[key] = cell, owner
        if cell is None:
            self.outs[key] = set()

    def path(self, tree, goal, margin):
        lo_x, lo_y, hi_x, hi_y = self.bounds
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
            for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
                for distance in (1, 2):
                    next_key = key[0] + distance * dx, key[1] + distance * dy
                    if not (lo_x - margin <= next_key[0] <= hi_x + margin and lo_y - margin <= next_key[1] <= hi_y + margin):
                        continue
                    if next_key in self.reserved or (next_key in self.cells and next_key != goal):
                        continue
                    if key in tree and wire_cell(key, self.outs[key] | {next_key}) is None:
                        continue
                    added = 1 if distance == 1 else 1.05
                    candidate = spent + added
                    if candidate < cost.get(next_key, math.inf):
                        cost[next_key], previous[next_key] = candidate, key
                        heappush(heap, (candidate + manhattan(next_key, goal) / 2, candidate, next_key))
        return None

    def route(self):
        order = sorted(self.sinks, key=lambda net: (-len(self.sinks[net]), net))
        for net in order:
            tree, pending = {self.roots[net]}, set(self.sinks[net])
            while pending:
                goal = min(pending, key=lambda p: (min(manhattan(p, start) for start in tree), p))
                path = None
                for margin in (3, 8, 16, 32):
                    path = self.path(tree, goal, margin)
                    if path:
                        break
                if path is None:
                    raise MapError(f"Не удалось проложить компактную цепь {net}")
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
    failure = None
    for pitch in (5, 6, 8):
        try:
            router = Router(netlist, pitch, max_cells)
            cells = router.route()
            manifest = {
                "schema": 1, "top": netlist["top"], "map_hash": map_hash(cells),
                "profile": "GraphDLC-01232bd", "verified_against_current_game": False,
                "inputs": router.inputs, "outputs": router.outputs,
                "settle_ticks": depth_of(cells) + 2, "cells": len(cells),
                "logic_nodes": len(netlist["nodes"]), "layout": "compact-graph-v1",
                "bounds": bounds_of(cells), "placement_pitch": pitch,
                "gate_labels": [{"at": list(key), "op": node["op"], "id": node["id"]} for key, node in router.gates.items()],
            }
            return cells, manifest
        except MapError as error:
            if "лимит" in str(error):
                raise
            failure = error
    raise MapError(f"Компактная трассировка не выполнена: {failure}")
