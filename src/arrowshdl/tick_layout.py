"""Automatic placement of native tick macros and ordinary Boolean gates."""
from collections import defaultdict
import math
import time

from arrowshdl.arrowasm import Cell, MapError
from arrowshdl.arrow_layout import GATE_TYPES, bounds_of, destinations
from arrowshdl.fixed_wiring import FixedWiring
from arrowshdl.mapdata import map_hash
from arrowshdl.physical import dependencies, _check_constraints
from arrowshdl.timing import propagation_bound


def macro(node):
    op = node['op']
    count = len(node['inputs'])
    if count > 11:
        raise MapError(f"{node['id']}: native receiver supports at most eleven incoming contacts")
    if op in ('REGISTER','LATCH'):
        if count!=2: raise MapError(op+' requires two inputs')
        # Equal-length control branches prevent a one-input reset when a write
        # level falls. The immutable macro preserves this timing after routing.
        cells={(0,0):Cell(7,1,True),(0,-1):Cell(1,1),
               (1,0):Cell(16 if op=='REGISTER' else 1,0),(1,-1):Cell(18,1)}
        return cells,[((-1,0),(0,0)),((1,1),(1,0))],(1,-1)
    if op == 'SET' and count != 2:
        raise MapError('SET requires two separate input contacts')
    if op in ('TIMER', 'EDGE', 'RISE', 'DETECTOR') and count != 1:
        raise MapError(f'{op} requires one input')
    if op in ('SOURCE', 'IMPULSE','CLOCK') and count:
        raise MapError(f'{op} does not accept ordinary inputs')
    if op == 'CLOCK':
        period = node['ticks']
        if type(period) is not int or not 16<=period<=4096 or period%4:
            raise MapError('arrows_clock.PERIOD: multiple of 4 from 16 to 4096')
        width,height = period//4-1,3
        ring = [(x,0) for x in range(width)]+[(width-1,y) for y in range(1,height)]+[(x,height-1) for x in reversed(range(width-1))]+[(0,y) for y in reversed(range(1,height-1))]
        directions = {(0,-1):0,(1,0):1,(0,1):2,(-1,0):3}
        cells = {}
        for i,p in enumerate(ring):
            q = ring[(i+1)%len(ring)]
            cells[p] = Cell(15 if i==0 else 1,directions[(q[0]-p[0],q[1]-p[1])])
        output = (1,0)
        cells[output] = Cell(7,1,True)
    elif op in ('EDGE', 'RISE'):
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
            raise MapError('arrows_timer.TICKS: expected an integer from 1 to 1024')
        cells = {(x,0):Cell(1,1) for x in range(ticks)}
        output = (ticks-1,0)
    else:
        type_id = {'SOURCE':2,'IMPULSE':9,'DELAY':4,'BUTTON':24}.get(op, GATE_TYPES.get(op))
        if type_id is None:
            raise MapError('Unsupported native operation: '+op)
        cells = {(0,0):Cell(type_id,1)}
        output = (0,0)
    pins = [(p,(0,0)) for p in ((-1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1),(-2,0),(0,-2),(0,2),(2,0))][:count]
    return cells, pins, output


def place_tick(graph, *, max_cells=1000000, constraints=None, automatic=False,
               pitch=6, aspect=1.0, search=False, seed=0):
    cells, expected, outputs, targets, labels, records = {}, {}, {}, defaultdict(list), [], []
    nodes = graph['nodes']
    macros = [macro(n) for n in nodes]
    panel=None
    if (constraints or {}).get('panel'):
        if not automatic: raise MapError('Module panels require --layout auto or --compact')
        from arrowshdl.panel_layout import prepare_panel
        panel=prepare_panel(graph,constraints['panel'],constraints['base'])
        cells.update(panel['cells']);expected.update(panel['expected'])
        for net,sinks in panel['targets'].items(): targets[net].extend(sinks)
    columns = max(1, math.ceil(math.sqrt(len(nodes))))
    by_net = {}
    if automatic:
        from arrowshdl.auto_placement import arrange
        origins = arrange(graph,macros,pitch=pitch,aspect=aspect,search=search,seed=seed)
        if panel:
            from arrowshdl.panel_layout import ring_positions
            origins=ring_positions(graph,macros,panel['metadata']['region'],pitch,aspect,search,seed)
    else:
        pitch = max(16, max((max(x for x,y in part)+8 for part,_,_ in macros), default=16))
        origins = [(i%columns*pitch+8,i//columns*16+8) for i in range(len(nodes))]
    for i, (node, (part, pins, output)) in enumerate(zip(nodes, macros)):
        origin = origins[i]
        def move(p): return p[0]+origin[0], p[1]+origin[1]
        placed = {move(p):c for p,c in part.items()}
        if cells.keys() & placed.keys():
            raise MapError('Overlapping native macros')
        cells.update(placed)
        local = dependencies(placed)
        for net, (pin, contact) in zip(node['inputs'], pins):
            pin, contact = move(pin), move(contact)
            targets[net].append((pin,contact))
            local[contact]['I'].add(pin)
        expected.update(local)
        output = move(output)
        outputs[node['output']] = next(q for q in destinations(output,cells[output]) if q not in placed)
        labels.append(dict(id=node['id'], op=node['op'], at=list(output), native=node.get('native',False),scope=node.get('scope','core')))
        by_net[node['output']] = list(output)
        records.extend(dict(id=node['id']+'.cell'+str(j), at=list(p)) for j,p in enumerate(placed))
    ports = {'inputs':{}, 'outputs':{}}
    if automatic:
        from arrowshdl.auto_placement import fit_ports
        frame = bounds_of(cells) if cells else dict(min=[0,0],max=[0,0])
        endpoints = {net:[pin for pin,contact in sinks] for net,sinks in targets.items()}
        used = set()
        config = graph.get('_input_bus_config',{'groups':[],'gap':'auto'})
        grouped = {name for group in config['groups'] for name in group}
        banks = {','.join(group):[e for name in group for e in graph['inputs'][name]] for group in config['groups']}
        banks.update({name:entries for name,entries in graph['inputs'].items() if name not in grouped})
        if panel:
            banks={name:entries for name,entries in banks.items() if name not in panel['inputs']}
        placed = fit_ports(banks,endpoints,frame,used,step=2 if config['gap']=='auto' else config['gap']+1)
        for bank,entries in placed.items():
            offset = 0
            for name in bank.split(','):
                width = len(graph['inputs'][name])
                ports['inputs'][name] = entries[offset:offset+width]; offset += width
        if panel: ports['inputs'].update(panel['inputs'])
        exposed={name:entries for name,entries in graph['outputs'].items() if not panel or name not in panel['consumed']}
        ports['outputs'] = fit_ports(exposed,{net:[tuple(p)] for net,p in by_net.items()},frame,used,output=True)
    input_index = 0
    for i,(name, entries) in enumerate(graph['inputs'].items()):
        if not automatic: ports['inputs'][name] = []
        for bit,entry in enumerate(entries):
            terminal = ports['inputs'][name][bit] if automatic else dict(index=entry['index'],contact=[-8,input_index*4],fixture=[-9,input_index*4],rotation=1)
            input_index += 1
            contact = tuple(terminal['contact'])
            if panel and name in panel['inputs']:
                outputs[entry['net']]=panel['roots'][entry['net']]
                continue
            cells[contact] = Cell(1,terminal['rotation'])
            outputs[entry['net']] = next(destinations(contact,cells[contact]))
            if not automatic: ports['inputs'][name].append(terminal)
            expected[contact] = {'I':set(),'B':set(),'S':set()}
    output_nets = {entry['net'] for entries in graph['outputs'].values() for entry in entries}
    for const_index,const in enumerate(('const0', 'const1')):
        if const in targets or const in output_nets:
            contact = (frame['min'][0]-2,frame['min'][1]-3-const_index*2) if automatic else (-8,input_index*4)
            input_index += 1
            cells[contact] = Cell(25 if const=='const0' else 2,1)
            outputs[const] = (contact[0]+1,contact[1])
            expected[contact] = {'I':set(),'B':set(),'S':set()}
    reserved = {tuple(e['fixture']) for entries in ports['inputs'].values() for e in entries}
    if panel: reserved.update(panel['reserved'])
    output_index = 0
    for name, entries in graph['outputs'].items():
        if panel and name in panel['consumed']: continue
        if not automatic: ports['outputs'][name] = []
        for bit,entry in enumerate(entries):
            # Every exported bit gets an independent terminal. A driving net
            # may also feed gates or another exported alias; its route is not
            # a vacant fixture and must never be overwritten by a probe.
            terminal = ports['outputs'][name][bit] if automatic else dict(index=entry['index'],contact=[columns*pitch+16,output_index*4],fixture=[columns*pitch+17,output_index*4],rotation=1)
            contact = tuple(terminal['contact'])
            output_index += 1
            fixture = tuple(terminal['fixture'])
            pin = (2*contact[0]-fixture[0],2*contact[1]-fixture[1])
            cells[contact] = Cell(1,terminal['rotation'])
            expected[contact] = {'I':{pin},'B':set(),'S':set()}
            targets[entry['net']].append((pin,contact))
            reserved.add(fixture)
            if not automatic: ports['outputs'][name].append(terminal)
    if len(cells) > max_cells:
        raise MapError('max_cells exceeded')
    router = FixedWiring(cells,reserved)
    if automatic: router.deadline = time.monotonic()+max(8,min(45,len(nodes)/20))
    if panel:
        router.deadline=time.monotonic()+60
        router.routing_order='fanout'
    router.max_cells = max_cells
    for net, sinks in targets.items():
        if net not in outputs:
            raise MapError('Signal has no driver: '+net)
        router.connection(net,outputs[net],sinks)
    if automatic:
        limits = [None,None,None,None]
        for direction in ('inputs','outputs'):
            for entries in ports[direction].values():
                for entry in entries:
                    if entry.get('panel'): continue
                    x,y=entry['contact']; fx,fy=entry['fixture']
                    axis = 0 if fx<x else 2 if fx>x else 1 if fy<y else 3
                    value = x if axis in (0,2) else y
                    limits[axis] = value if limits[axis] is None else (max(limits[axis],value) if axis<2 else min(limits[axis],value))
        router.route_allowed = lambda p: all(v is None or (q>=v if i<2 else q<=v) for i,(q,v) in enumerate(zip((p[0],p[1],p[0],p[1]),limits)))
    cells = router.route_all() if targets else cells
    actual = dependencies(cells)
    for p, declared in expected.items():
        if actual[p] != declared:
            raise MapError(f'Unexpected physical contact at native macro {p}')
    macro_sources = {q:n['output'] for n,label in zip(nodes,labels) for q in [tuple(label['at'])]}
    for p in router.outs:
        for q in actual[p]['I']:
            source = router.owners.get(q) if q in router.outs else macro_sources.get(q)
            if source is not None and source != router.owners[p]:
                raise MapError(f'Short circuit: {q} → {p}')
    _check_constraints({'nodes':records},constraints or {})
    memories = [tuple(label['at']) for label in labels if label['op'] in ('SET','TOGGLE','RANDOM','BUTTON','CLOCK','REGISTER','LATCH')]
    ticks = propagation_bound(cells,memories,margin=2)
    meta = dict(schema=1,top=graph['top'],layout='auto-graph-v1' if automatic else 'native-tick-auto-v1',cells=len(cells),
        logic_nodes=len(nodes),map_hash=map_hash(cells),bounds=bounds_of(cells),**ports,
        settle_ticks=ticks,gate_labels=labels,profile='GraphDLC-01232bd',verified_against_current_game=False,
        timing=dict(model='game-ticks',state_boundaries=[list(p) for p in memories],
                    contract='settle_ticks bounds propagation between state boundaries; stateful outputs need tick scenarios'),
        optimization=dict(native_macros_preserved=True,boolean_optimization=False))
    if panel: meta['panel']=panel['metadata']
    if automatic:
        from arrowshdl.input_buses import verify_exterior
        verify_exterior(cells,meta)
    return cells,meta
