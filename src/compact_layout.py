"""Logic-first placement and multi-terminal A* routing with fixed port banks.

Internal paths are routed before I/O and protected from later port routing.
Actual internal arrow counts select candidates; port tails cost nothing.
Technology mapping and verified templates precede the general router.
"""
from __future__ import annotations

from collections import defaultdict, deque
from heapq import heappop, heappush
from itertools import permutations
import math
import os
import random
import time

from arrowasm import Cell, MapError, validate_cell
from arrow_layout import GATE_TYPES, bounds_of, depth_of, destinations, edges,logic_core_metrics
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


def arrange_buses(netlist, pitch, mode="sides", seed=0, columns=None,logic_first=False):
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
    # A fixed I/O frame contains every candidate core (pitch <= 8). Its contact
    # positions depend on the graph, never the annealing seed or candidate pitch.
    interface_pitch=8 if logic_first else pitch
    right, bottom = (columns - 1) * interface_pitch, (row_count - 1) * interface_pitch
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
            if logic_first and (target in fixed or pair[0] in fixed):
                continue
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
        self.pin_consumers=defaultdict(list)
        self.reserved, self.inputs, self.outputs = set(), {}, {}
        vertices, positions, sources = placement or arrange_free(netlist, pitch)
        self.input_interfaces = {}
        self.output_interfaces = {}
        output_nets = {e["net"] for entries in netlist["outputs"].values() for e in entries}
        self.output_nets=output_nets
        self.source_positions = {vertex.get('net',vertex.get('node',{}).get('output')):position
                                 for vertex,position in zip(vertices,positions)}
        consumers=defaultdict(list)
        for node in netlist['nodes']:
            for net in node['inputs']:consumers[net].append(node['output'])
        output_directions={vertex['node']['output']:vertex.get('rotation',1) for vertex in vertices if vertex['kind']=='gate'}
        self.direct_nets=set()
        self.flexible_gates=set()
        self.explicit_pins={}
        self.node_groups={node['id']:node.get('scope','core') for node in netlist['nodes']}
        for vertex, (x, y) in zip(vertices, positions):
            if vertex["kind"] == "gate":
                node = vertex["node"]
                key = x, y
                self.add(key, "gate:" + node["id"], Cell(GATE_TYPES[node["op"]], vertex.get("rotation",1)))
                self.gates[key] = node
                flexible=vertex.get('flexible_output',False) and node['op'] in ('OR','BUF')
                if flexible:
                    self.flexible_gates.add(key)
                    self.outs[key]=set()
                    self.roots[node['output']]=key
                if vertex.get('pins') is not None:
                    self.explicit_pins[key]=[tuple(p) for p in vertex['pins']]
                if node["output"] in output_nets:
                    fixture = next(destinations(key,self.cells[key]))
                    self.reserved.add(fixture)
                    self.output_interfaces[node["output"]] = fixture
                    if flexible:self.outs[key].add(fixture)
                elif flexible:
                    self.direct_nets.add(node['output'])
                else:
                    destination=next(destinations(key,self.cells[key]))
                    sinks=consumers[node['output']]
                    if len(sinks)==1 and self.source_positions.get(sinks[0])==destination:
                        self.roots[node['output']]=key
                        self.direct_nets.add(node['output'])
                    else:
                        self.add(destination, node["output"])
                        self.roots[node["output"]] = destination
            elif vertex["kind"] == "input":
                self.add((x, y), vertex["net"])
                self.roots[vertex["net"]] = x, y
                fixture = tuple(vertex.get("fixture", (x - 1, y)))
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
        primary={e['net'] for es in netlist['inputs'].values() for e in es}
        for key, node in self.gates.items():
            x, y = key
            if node["output"] in output_nets:
                fx,fy = self.output_interfaces[node["output"]]
                candidates = [(2*x-fx,2*y-fy)]
            else:
                candidates = [(x - 1, y), (x, y - 1), (x, y + 1)]
            def compatible(pin,net):
                if key not in self.flexible_gates and pin in destinations(key,self.cells[key]):return False
                if pin in self.reserved:return False
                if pin not in self.cells:return True
                if pin in self.gates:
                    return self.gates[pin]['output']==net and (
                        wire_cell(pin,self.outs[pin]|{key}) is not None if pin in self.flexible_gates
                        else key in destinations(pin,self.cells[pin]))
                return self.owners[pin]==net and wire_cell(pin,self.outs[pin]|{key}) is not None
            choices=[ps for ps in permutations(candidates,len(node['inputs'])) if all(compatible(pin,net) for net,pin in zip(node['inputs'],ps))]
            if key in self.explicit_pins:
                choices=[tuple(self.explicit_pins[key])]
                if not all(compatible(pin,net) for net,pin in zip(node['inputs'],choices[0])):choices=[]
            if not choices:raise MapError(f"Нет совместимых контактов у элемента {node['id']}")
            pins = min(choices, key=lambda ps: sum(manhattan(self.roots[net], pin) for net, pin in zip(node["inputs"], ps) if net not in primary and node['output'] not in output_nets))
            self.pins[key] = list(pins)
            for net, pin in zip(node["inputs"], pins):
                if pin not in self.cells:self.add(pin, net)
                if pin not in self.gates or pin in self.flexible_gates:self.outs[pin].add(key)
                self.sinks[net].append(pin)
                self.pin_consumers[pin].append(key)
        for name, entries in netlist["inputs"].items():
            self.inputs[name] = [{"index": e["index"], "contact": list(self.roots[e["net"]]), **self.input_interfaces[e["net"]]} for e in entries]
        for name, entries in netlist["outputs"].items():
            self.outputs[name] = []
            for e in entries:
                x, y = self.source_positions[e["net"]]
                self.outputs[name].append({"index": e["index"], "contact": [x, y], "fixture": list(self.output_interfaces[e["net"]]), "rotation": 0})
        xs, ys = zip(*self.cells)
        self.bounds = min(xs), min(ys), max(xs), max(ys)
        self.routing_limits = [None, None, None, None]
        for entries in self.inputs.values():
            for entry in entries:
                x,y=entry['contact']; rotation=entry['rotation']
                axis = {1:0, 2:1, 3:2, 0:3}[rotation]
                value = x if axis in (0,2) else y
                old=self.routing_limits[axis]
                self.routing_limits[axis] = value if old is None else (max(old,value) if axis<2 else min(old,value))
        for entries in self.outputs.values():
            for entry in entries:
                x,y=entry['contact']; fx,fy=entry['fixture']
                axis = 2 if fx>x else 0 if fx<x else 3 if fy>y else 1
                value=x if axis in (0,2) else y
                old=self.routing_limits[axis]
                self.routing_limits[axis]=value if old is None else (max(old,value) if axis<2 else min(old,value))
        if any(not self.route_allowed(p) for p in self.cells):
            raise MapError('Контакты ввода/вывода не образуют внешнюю границу схемы')
        self.fixed_cells = set(self.cells)
        self.fixed_outs = {key:set(values) for key,values in self.outs.items()}
        internal={p for p,n in self.gates.items() if n['output'] not in output_nets or n['op']!='BUF'}
        core_nets={self.gates[p]['output'] for p in internal}|{'const0','const1'}
        self.core_sinks={net:{pin for p in internal for pin,n in zip(self.pins[p],self.gates[p]['inputs']) if n==net}
                         for net in self.sinks if net in core_nets}
        self.ripups = 0
        self.io_conflict_fallback = False

    def add(self, key, owner, cell=None):
        if key in self.cells or key in self.reserved:
            raise MapError(f"Конфликт компактного размещения в {key}")
        if len(self.cells) >= self.max_cells:
            raise MapError(f"Схема превышает лимит {self.max_cells} клеток")
        self.cells[key], self.owners[key] = cell, owner
        if cell is None:
            self.outs[key] = set()

    def route_allowed(self, position):
        limits=getattr(self,'routing_limits',(None,None,None,None))
        x,y=position
        return all(limit is None or (value>=limit if i<2 else value<=limit)
                   for i,(value,limit) in enumerate(zip((x,y,x,y),limits)))

    def path(self, tree, goal, margin, soft=False):
        lo_x, lo_y, hi_x, hi_y = self.bounds
        net = self.owners[goal]
        # An isolated sink otherwise makes forward A* flood the whole board.
        # Check a small reverse component first. Exceeding the budget means
        # "unknown", so a routable path is never rejected by this shortcut.
        seen,pending={goal},deque([goal])
        connected=goal in tree
        while pending and not connected and len(seen)<=128:
            current=pending.popleft()
            for dx,dy in ((1,0),(0,1),(-1,0),(0,-1),(1,1),(-1,1),(1,-1),(-1,-1)):
                for distance in ((1,) if dx and dy else (1,2)):
                    predecessor=current[0]+distance*dx,current[1]+distance*dy
                    if not self.route_allowed(predecessor):continue
                    if not (lo_x-margin<=predecessor[0]<=hi_x+margin and lo_y-margin<=predecessor[1]<=hi_y+margin):
                        continue
                    if predecessor in seen or predecessor in self.reserved:
                        continue
                    if predecessor in tree:
                        if len(self.outs[predecessor])<3 and wire_cell(predecessor,self.outs[predecessor]|{current}) is not None:
                            connected=True
                        continue
                    blocked=predecessor in self.cells
                    removable=soft and predecessor not in self.fixed_cells and self.owners.get(predecessor)!=net
                    if blocked and not removable:
                        continue
                    seen.add(predecessor);pending.append(predecessor)
        if not connected and not pending:
            return None
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
                    if key in self.flexible_gates and next_key in self.pins[key]:continue
                    if not self.route_allowed(next_key):continue
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

    def tree(self,net):
        reached,todo=set(),[self.roots[net]]
        while todo:
            p=todo.pop()
            if p not in reached:
                reached.add(p)
                todo.extend(q for q in self.outs.get(p,()) if self.owners.get(q)==net)
        return reached

    def route_phase(self,targets):
        order=sorted((net for net,sinks in targets.items() if sinks),key=lambda net:(-len(targets[net]),net))
        queue, attempts = deque(order), 0
        net_attempts=defaultdict(int)
        def fail(message,net,goal=None):
            error=MapError(message);error.net=net;error.goal=goal
            raise error
        while queue:
            net = queue.popleft()
            attempts += 1
            net_attempts[net] += 1
            # A few conflicting nets must not consume the entire graph's budget
            # by repeatedly tearing down each other's identical routes.
            if net_attempts[net] > 6:
                fail(f"Цепь {net} повторно конфликтует: исчерпан лимит 6 перестроений",net)
            if attempts > max(40, len(order)*3):
                fail("Исчерпан бюджет перестройки проводов",net)
            self.clear_net(net)
            tree=self.tree(net)
            pending=set(targets[net])-tree
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
                        fail(f"Не удалось проложить компактную цепь {net}",net,goal)
                    blockers = sorted({self.owners[p] for p in path if p in self.cells and p not in self.fixed_cells and self.owners[p] != net})
                    for blocker in blockers:
                        self.clear_net(blocker)
                        if blocker not in queue:
                            queue.append(blocker)
                        self.ripups += 1
                    path = self.path(tree,goal,32)
                    if path is None:
                        fail(f"Не удалось перестроить цепь {net}",net,goal)
                for key in path[1:-1]:
                    self.add(key, net)
                for key, target in zip(path, path[1:]):
                    self.outs[key].add(target)
                tree.update(path)
                pending.remove(goal)

    def route(self, order=None):
        seed_cells,seed_owners=dict(self.cells),dict(self.owners)
        seed_outs={p:set(targets) for p,targets in self.outs.items()}
        self.route_phase(self.core_sinks)
        # Freeze the internal paths before adding input/output tails. A port may
        # grow a branch, but clearing its net restores this exact routed core.
        self.fixed_cells=set(self.cells)
        self.fixed_outs={p:set(targets) for p,targets in self.outs.items()}
        try:
            self.route_phase(self.sinks)
        except MapError:
            # A frozen internal wire can enclose an external contact. Restart
            # from gates/pins, allowing all wire nets to negotiate together.
            # Core metrics still include every resulting internal detour.
            self.io_conflict_fallback = True
            self.cells,self.owners=seed_cells,seed_owners
            self.outs={p:set(targets) for p,targets in seed_outs.items()}
            self.fixed_cells=set(seed_cells)
            self.fixed_outs={p:set(targets) for p,targets in seed_outs.items()}
            self.route_phase(self.sinks)
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
        for key in self.flexible_gates:
            if self.gates[key]['output']==net:
                self.outs[key]=set(self.fixed_outs.get(key,()))
        for key in [p for p,owner in self.owners.items() if owner == net]:
            if key in self.fixed_cells:
                self.outs[key] = set(self.fixed_outs[key])
            else:
                del self.cells[key],self.owners[key],self.outs[key]

    def validate(self):
        if any(not self.route_allowed(p) for p in self.cells):
            raise MapError('Провод вышел за внешнюю границу ввода/вывода')
        links, reverse = edges(self.cells), defaultdict(list)
        for key, targets in links.items():
            for target in targets:
                if key in destinations(target,self.cells[target]):
                    raise MapError(f"Вход стрелки расположен на её выходе: {key} → {target}")
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
                if (self.gates[pin]['output'] if pin in self.gates else self.owners[pin]) != net:
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
    from technology_mapping import map_native_gates,merge_duplicate_logic
    from native_adder_layout import try_native_adder
    from native_mux_layout import try_native_mux
    graph,rewrites=map_native_gates(netlist)
    graph,sharing=merge_duplicate_logic(graph)
    result=try_native_adder(graph,rewrites,max_cells) if not graph.get('_input_bus_config') else None
    mux_failure=None
    if result is None:
        try:
            result=try_native_mux(graph,max_cells)
        except MapError as error:
            mux_failure=str(error)
    if result is None:
        result=place_packed(graph,max_cells)
    cells,meta=result
    meta['logic_nodes']=len(netlist['nodes'])
    meta['technology_nodes']=meta.get('mapped_logic_nodes',len(graph['nodes']))
    if mux_failure is not None:
        meta['native_mux_rejected']=mux_failure
    meta['technology_mapping']=rewrites
    meta['shared_logic']=sharing
    return cells,meta


def router_manifest(graph,router,cells,layout):
    from signal_metadata import describe_signals
    return {'schema':1,'top':graph['top'],'map_hash':map_hash(cells),
            'profile':'GraphDLC-01232bd','verified_against_current_game':False,
            'inputs':router.inputs,'outputs':router.outputs,'settle_ticks':depth_of(cells)+2,
            'routing_limits':router.routing_limits,
            'output_search':getattr(router,'output_search',None),
            'cells':len(cells),'logic_nodes':len(graph['nodes']),'layout':layout,'bounds':bounds_of(cells),
            'port_layout':'fixed-sides','rerouted_nets':router.ripups,
            'io_conflict_fallback':router.io_conflict_fallback,
            'logic_core':logic_core_metrics(cells,router.gates,router.output_nets),
            'direct_gate_links':len(router.direct_nets),
            'shared_input_contacts':sum(len(consumers)>1 for consumers in router.pin_consumers.values()),
            'gate_labels':[{'at':list(key),'op':node['op'],'id':node['id'],'scope':node.get('scope','core')}
                           for key,node in router.gates.items()],
            'signals':describe_signals(graph,cells,router.owners,router.gates)}


def place_packed(graph,max_cells=100_000):
    from packed_layout import arrange_packed,group_of
    trace=lambda message:print(message,flush=True) if os.environ.get('ARROWSHDL_LAYOUT_TRACE')=='1' else None
    _,initial=arrange_packed(graph,frame=(100000,100000))
    frame=(max(96,sum(b['width']+4*math.ceil(math.sqrt(b['units']))+16 for b in initial)+32),
           max(96,sum(b['height']+4*math.ceil(math.sqrt(b['units']))+16 for b in initial)+32))
    producer={node['output']:group_of(node) for node in graph['nodes']}
    candidates,attempts=[],[]
    combine=len(graph['nodes'])<=96
    for aspect in (0.5,1.0,1.4,2.5,4.0):
        growth={};corridor=0
        for iteration in range(16):
            trace(f"packed: aspect={aspect}, local_growth={growth}, corridor={corridor}")
            router=None;blocks=initial
            try:
                placement,blocks=arrange_packed(graph,growth,corridor,aspect,frame,combine)
                from input_buses import apply_placement
                automatic=graph.get('_input_bus_config',{}).get('gap')=='auto'
                variant=dict(graph,_bus_gap={0.5:0,1.0:1,1.4:2,2.5:0,4.0:3}[aspect]) if automatic else graph
                placement=apply_placement(variant,placement)
                if graph.get('_input_bus_config',{}).get('groups'):
                    from output_layout import route_with_outputs
                    cells,router=route_with_outputs(variant,placement,max_cells)
                else:
                    # Default I/O banks are static across all core candidates.
                    # Explicit bus searches may optimize their outer interface.
                    router=Router(variant,1,max_cells,placement)
                    cells=router.route()
                meta=router_manifest(graph,router,cells,'compact-connected-modules-v1')
                meta['module_blocks']=blocks
                meta['output_search']=getattr(router,'output_search',None)
                meta['fixed_port_banks']=not bool(graph.get('_input_bus_config',{}).get('groups'))
                meta['bus_search_gap']=variant.get('_bus_gap',graph.get('_input_bus_config',{}).get('gap'))
                meta['packing']={'aspect':aspect,'local_expansion':dict(growth),'corridor':corridor,'port_margin':4,'fixed_frame':list(frame)}
                attempts.append(dict(meta['packing'],status='valid',core=meta['logic_core']))
                candidates.append((cells,meta))
                trace(f"packed: VALID core={meta['logic_core']['cells']}, ticks={meta['logic_core']['ticks']}")
                break
            except MapError as error:
                net=getattr(error,'net',None);goal=getattr(error,'goal',None)
                active={block['id'] for block in blocks}
                group=producer.get(net)
                if router is not None:
                    goals=[goal] if goal is not None else router.sinks.get(net,[])
                    target_groups=[group_of(router.gates[p]) for pin in goals for p in router.pin_consumers.get(pin,())]
                    choices=sorted(set(target_groups)&active,key=lambda g:(growth.get(g,0),g))
                    tree=router.tree(net) if net in router.roots else set()
                    can_escape=any(p not in router.cells and p not in router.reserved and wire_cell(start,router.outs.get(start,set())|{p}) is not None
                                   for start in tree for p in ((start[0]+dx,start[1]+dy) for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(2,0),(-2,0),(0,2),(0,-2),(1,1),(1,-1),(-1,1),(-1,-1))))
                    if choices and (can_escape or group not in active):group=choices[0]
                if group not in active:
                    group=min(active,key=lambda g:(growth.get(g,0),g)) if active else 'core'
                attempts.append({'aspect':aspect,'local_expansion':dict(growth),'corridor':corridor,
                                 'status':'rejected','group':group,'net':net,'reason':str(error)})
                trace(f"packed: rejected in {group}: {error}")
                if growth.get(group,0)<3:growth[group]=growth.get(group,0)+1
                elif corridor<15:corridor+=3
                else:break
    if not candidates:
        trace('packed: using legacy placement fallback')
        cells,meta=place_routed(graph,max_cells)
        meta['packing_attempts']=attempts
        return cells,meta
    min_area=max(1,min(m['logic_core']['bounds']['area'] for _,m in candidates))
    eligible=[(c,m) for c,m in candidates if m['logic_core']['bounds']['area']<=min_area*1.25]
    cells,meta=min(eligible,key=lambda cm:(cm[1]['logic_core']['cells'],cm[1]['logic_core']['ticks'],cm[1]['logic_core']['bounds']['area']))
    meta['optimization']={'objective':'connected_units_then_min_core_cells_and_ticks','io_in_objective':False,
                          'routing_order':'internal_then_fixed_io_with_conflict_fallback',
                          'path_search':'multi_source_A_star','local_growth':True,'attempts':attempts,
                          'aspect_candidates':[0.5,1.0,1.4,2.5,4.0],
                          'initial_corridor':0,'area_factor':1.25,'max_attempts_per_net_per_phase':6}
    if graph.get('_input_bus_config',{}).get('groups') and graph['_input_bus_config']['gap']=='auto':
        from output_layout import candidate_score, exterior_bounds
        selected=min(candidates,key=candidate_score)
        policy=meta['optimization']
        cells,meta=selected
        meta['full_bounds']=exterior_bounds(cells,meta['inputs'],meta['outputs'])
        meta['optimization']=dict(policy,objective='min_core_then_cells_full_area_and_ticks',io_in_objective=True,
                                  automatic_input_buses=True,
                                  bus_candidates=[{'gap':m.get('bus_search_gap'),'cells':len(c),'ticks':m['settle_ticks'],
                                                   'full_bounds':exterior_bounds(c,m['inputs'],m['outputs'])} for c,m in candidates])
    return cells,meta


def place_routed(netlist, max_cells=100_000):
    failures, candidates, attempts = [], [], []
    configs = [(pitch,seed) for pitch in (3,4,5) for seed in (0,1)]

    def trace(message):
        if os.environ.get('ARROWSHDL_LAYOUT_TRACE')=='1':
            print(message,flush=True)

    def attempt(pitch,seed):
        trace(f"layout: pitch={pitch}, seed={seed}, nodes={len(netlist['nodes'])}")
        started=time.perf_counter()
        try:
            cells,meta=candidate(pitch,seed)
        except MapError as error:
            failures.append(str(error))
            attempts.append({'pitch':pitch,'seed':seed,'status':'rejected','reason':str(error)})
            trace(f"layout: rejected after {time.perf_counter()-started:.1f}s: {error}")
            return False
        candidates.append((cells,meta))
        attempts.append({'pitch':pitch,'seed':seed,'status':'valid'})
        trace(f"layout: valid after {time.perf_counter()-started:.1f}s: core={meta['logic_core']['cells']}, ticks={meta['logic_core']['ticks']}")
        return True

    def candidate(pitch,seed):
        from input_buses import apply_placement
        placement=apply_placement(netlist,arrange_buses(netlist,pitch,"sides",seed,logic_first=True))
        from output_layout import route_with_outputs
        cells,router=route_with_outputs(netlist,placement,max_cells)
        manifest={
            "schema":1,"top":netlist["top"],"map_hash":map_hash(cells),
            "profile":"GraphDLC-01232bd","verified_against_current_game":False,
            "inputs":router.inputs,"outputs":router.outputs,
            "settle_ticks":depth_of(cells)+2,"cells":len(cells),
            "logic_nodes":len(netlist["nodes"]),"layout":"compact-logic-first-v3",
            "bounds":bounds_of(cells),"placement_pitch":pitch,
            "port_layout":"fixed-sides","placement_seed":seed,"rerouted_nets":router.ripups,
            "io_conflict_fallback":router.io_conflict_fallback,
            "logic_core":logic_core_metrics(cells,router.gates,router.output_nets),
            "gate_labels":[{"at":list(key),"op":node["op"],"id":node["id"]} for key,node in router.gates.items()],
        }
        from signal_metadata import describe_signals
        manifest['signals']=describe_signals(netlist,cells,router.owners,router.gates)
        return cells,manifest

    for pitch,seed in configs:
        attempt(pitch,seed)
    if not candidates:
        # The same fixed port banks surround a larger core when needed.
        for pitch in (6,8):
            if attempt(pitch,0):
                break
    if not candidates:
        raise MapError(f"Компактная трассировка не выполнена: {failures[-1]}")
    min_area = max(1,min(m["logic_core"]["bounds"]["area"] for _,m in candidates))
    min_cells = max(1,min(m["logic_core"]["cells"] for _,m in candidates))
    eligible = [(c,m) for c,m in candidates if m["logic_core"]["bounds"]["area"] <= min_area*1.25 and m["logic_core"]["cells"] <= min_cells*1.2]
    # If the two independent bounds have no common candidate, choose a balanced
    # Pareto compromise instead of silently disabling either size constraint.
    if not eligible:
        eligible = [min(candidates,key=lambda cm:max(cm[1]["logic_core"]["bounds"]["area"]/min_area,cm[1]["logic_core"]["cells"]/min_cells))]
    cells,manifest = min(eligible,key=lambda cm:(cm[1]["logic_core"]["cells"],cm[1]["logic_core"]["ticks"],cm[1]["logic_core"]["bounds"]["area"]))
    manifest["optimization"] = {"objective":"min_core_cells_then_ticks_with_compactness_limits",
        "path_search":"multi_source_A_star","routing_order":"internal_then_fixed_io_with_conflict_fallback",
        "io_in_objective":False,
        "max_attempts_per_net_per_phase":6,"attempts":attempts,
        "area_factor":1.25,"cell_factor":1.2,
        "candidates":[{"core":m["logic_core"],"cells":len(c),"area":m["bounds"]["area"],"ticks":m["settle_ticks"],"pitch":m["placement_pitch"],"seed":m["placement_seed"]} for c,m in candidates]}
    return cells,manifest
