"""Automatic placement of native tick macros and ordinary Boolean gates."""
from collections import defaultdict
import math

from arrowshdl.arrowasm import Cell, MapError
from arrowshdl.arrow_layout import GATE_TYPES, bounds_of, destinations
from arrowshdl.fixed_wiring import FixedWiring
from arrowshdl.mapdata import map_hash
from arrowshdl.physical import dependencies, _check_constraints
from arrowshdl.timing import propagation_bound


def macro(node):
    op = node['op']
    count = len(node['inputs'])
    if count > 3:
        raise MapError(f"{node['id']}: автоматическое нативное размещение поддерживает до трёх входов; используйте шаблон")
    if op == 'SET' and count != 2:
        raise MapError('SET требует два отдельных входных контакта')
    if op in ('TIMER', 'EDGE', 'RISE', 'DETECTOR') and count != 1:
        raise MapError(f'{op} требует один вход')
    if op in ('SOURCE', 'IMPULSE') and count:
        raise MapError(f'{op} не принимает обычных входов')
    if op in ('EDGE', 'RISE'):
        # A direct jump and a one-tick branch meet at a parity/threshold gate.
        cells = {(0,0):Cell(12,1), (1,0):Cell(15 if op == 'RISE' else 1,1),
                 (2,0):Cell(16 if op == 'RISE' else 17,1)}
        output = (2,0)
    elif op == 'DETECTOR':
        cells = {(0,0):Cell(1,2), (0,1):Cell(5,2)}
        output = (0,1)
    elif op == 'TIMER':
        ticks = node['ticks']
        if type(ticks) is not int or not 1 <= ticks <= 1024:
            raise MapError('arrows_timer.TICKS: целое число 1..1024')
        cells = {(x,0):Cell(1,1) for x in range(ticks)}
        output = (ticks-1,0)
    else:
        type_id = {'SOURCE':2,'IMPULSE':9,'DELAY':4,'BUTTON':24}.get(op, GATE_TYPES.get(op))
        if type_id is None:
            raise MapError('Неподдерживаемая нативная операция '+op)
        cells = {(0,0):Cell(type_id,1)}
        output = (0,0)
    pins = [((-1,0),(0,0)), ((0,-1),(0,0)), ((0,1),(0,0))][:count]
    return cells, pins, output


def place_tick(graph, *, max_cells=1000000, constraints=None):
    cells, expected, outputs, targets, labels, records = {}, {}, {}, defaultdict(list), [], []
    nodes = graph['nodes']
    macros = [macro(n) for n in nodes]
    columns = max(1, math.ceil(math.sqrt(len(nodes))))
    by_net = {}
    pitch = max(16, max((max(x for x,y in part)+8 for part,_,_ in macros), default=16))
    for i, (node, (part, pins, output)) in enumerate(zip(nodes, macros)):
        origin = (i%columns*pitch+8, i//columns*16+8)
        def move(p): return p[0]+origin[0], p[1]+origin[1]
        placed = {move(p):c for p,c in part.items()}
        if cells.keys() & placed.keys():
            raise MapError('Пересечение нативных макросов')
        cells.update(placed)
        local = dependencies(placed)
        for net, (pin, contact) in zip(node['inputs'], pins):
            pin, contact = move(pin), move(contact)
            targets[net].append((pin,contact))
            local[contact]['I'].add(pin)
        expected.update(local)
        output = move(output)
        outputs[node['output']] = next(destinations(output, cells[output]))
        labels.append(dict(id=node['id'], op=node['op'], at=list(output), native=node.get('native',False)))
        by_net[node['output']] = list(output)
        records.extend(dict(id=node['id']+'.cell'+str(j), at=list(p)) for j,p in enumerate(placed))
    ports = {'inputs':{}, 'outputs':{}}
    for i,(name, entries) in enumerate(graph['inputs'].items()):
        ports['inputs'][name] = []
        for entry in entries:
            contact = (-8, len(outputs)*4)
            cells[contact] = Cell(1,1)
            outputs[entry['net']] = (contact[0]+1,contact[1])
            fixture = (contact[0]-1,contact[1])
            ports['inputs'][name].append(dict(index=entry['index'],contact=list(contact),fixture=list(fixture),rotation=1))
            expected[contact] = {'I':set(),'B':set(),'S':set()}
    output_nets = {entry['net'] for entries in graph['outputs'].values() for entry in entries}
    for const in ('const0', 'const1'):
        if const in targets or const in output_nets:
            contact = (-8,len(outputs)*4)
            cells[contact] = Cell(25 if const=='const0' else 2,1)
            outputs[const] = (contact[0]+1,contact[1])
            expected[contact] = {'I':set(),'B':set(),'S':set()}
    reserved = {tuple(e['fixture']) for entries in ports['inputs'].values() for e in entries}
    output_index = 0
    for name, entries in graph['outputs'].items():
        ports['outputs'][name] = []
        for entry in entries:
            # Every exported bit gets an independent terminal. A driving net
            # may also feed gates or another exported alias; its route is not
            # a vacant fixture and must never be overwritten by a probe.
            contact = (columns*pitch+16, output_index*4)
            output_index += 1
            pin, fixture = (contact[0]-1,contact[1]), (contact[0]+1,contact[1])
            cells[contact] = Cell(1,1)
            expected[contact] = {'I':{pin},'B':set(),'S':set()}
            targets[entry['net']].append((pin,contact))
            reserved.add(fixture)
            ports['outputs'][name].append(dict(index=entry['index'],contact=list(contact),fixture=list(fixture),rotation=0))
    if len(cells) > max_cells:
        raise MapError('Превышен max_cells')
    router = FixedWiring(cells,reserved)
    router.max_cells = max_cells
    for net, sinks in targets.items():
        if net not in outputs:
            raise MapError('Сигнал без источника '+net)
        router.connection(net,outputs[net],sinks)
    cells = router.route_all() if targets else cells
    actual = dependencies(cells)
    for p, declared in expected.items():
        if actual[p] != declared:
            raise MapError(f'Посторонний физический контакт нативного макроса {p}')
    macro_sources = {q:n['output'] for n,label in zip(nodes,labels) for q in [tuple(label['at'])]}
    for p in router.outs:
        for q in actual[p]['I']:
            source = router.owners.get(q) if q in router.outs else macro_sources.get(q)
            if source is not None and source != router.owners[p]:
                raise MapError(f'Короткое замыкание {q} → {p}')
    _check_constraints({'nodes':records},constraints or {})
    memories = [tuple(label['at']) for label in labels if label['op'] in ('SET','TOGGLE','RANDOM','BUTTON')]
    ticks = propagation_bound(cells,memories,margin=2)
    return cells, dict(schema=1,top=graph['top'],layout='native-tick-auto-v1',cells=len(cells),
        logic_nodes=len(nodes),map_hash=map_hash(cells),bounds=bounds_of(cells),**ports,
        settle_ticks=ticks,gate_labels=labels,profile='GraphDLC-01232bd',verified_against_current_game=False,
        timing=dict(model='game-ticks',state_boundaries=[list(p) for p in memories],
                    contract='settle_ticks bounds propagation between state boundaries; stateful outputs need tick scenarios'),
        optimization=dict(native_macros_preserved=True,boolean_optimization=False))
