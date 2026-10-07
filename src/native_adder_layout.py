"""Compact bit-slice template for any recognized native ripple-adder width.

There are no HDL names or fixed widths in this backend. Other graphs use the
general router. Three physical input signals implement MAJ and parity directly.
"""
from collections import Counter,defaultdict

from arrowasm import Cell,MapError,validate_cell
from arrow_layout import bounds_of,depth_of,validate_connections,logic_core_metrics
from mapdata import map_hash


def try_native_adder(graph,rewrites,max_cells):
    nodes=graph['nodes']
    by_id={n['id']:n for n in nodes}
    primary={e['net']:(name,e['index']) for name,es in graph['inputs'].items() for e in es}
    groups=[dict(r) for r in rewrites]
    claimed={r['sum_id'] for r in groups}|{r['cout_id'] for r in groups}
    # A genuine two-input half-adder can be the first stage of an unsigned chain.
    for carry in nodes:
        if carry['op']!='AND' or len(carry['inputs'])!=2 or not set(carry['inputs'])<=primary.keys():continue
        sums=[n for n in nodes if n['op']=='XOR' and len(n['inputs'])==2 and Counter(n['inputs'])==Counter(carry['inputs'])]
        if len(sums)!=1:continue
        s=sums[0]
        groups.append({'kind':'half_adder','a':carry['inputs'][0],'b':carry['inputs'][1],'cin':'const0',
                       'sum':s['output'],'cout':carry['output'],'sum_id':s['id'],'cout_id':carry['id']})
        claimed.update((s['id'],carry['id']))
    if not groups:return None
    if {n['id'] for n in nodes if n['op']!='BUF'}!=claimed:return None
    carries={g['cout']:g for g in groups}
    roots=[g for g in groups if g['cin'] not in carries]
    if len(roots)!=1:return None
    chain=[]
    current=roots[0]
    while current not in chain:
        chain.append(current)
        following=[g for g in groups if g['cin']==current['cout']]
        if not following:break
        if len(following)!=1:return None
        current=following[0]
    if len(chain)!=len(groups):return None
    initial=chain[0]['cin']
    ab=[net for g in chain for net in (g['a'],g['b'])]
    if len(set(ab))!=len(ab) or not set(ab)<=primary.keys():return None
    if initial not in primary and initial not in ('const0','const1'):return None
    if initial in ab:return None
    if set(ab)|({initial} if initial in primary else set())!=set(primary):return None
    buffers=defaultdict(list)
    for n in nodes:
        if n['op']=='BUF' and len(n['inputs'])==1:buffers[n['inputs'][0]].append(n)
    if any(len(buffers[g['sum']])!=1 for g in chain) or len(buffers[chain[-1]['cout']])!=1:return None
    expected_buffers=[buffers[g['sum']][0] for g in chain]+[buffers[chain[-1]['cout']][0]]
    if {n['id'] for n in nodes if n['op']=='BUF'}!={n['id'] for n in expected_buffers}:return None
    output_nets={e['net'] for es in graph['outputs'].values() for e in es}
    if {n['output'] for n in expected_buffers}!=output_nets:return None
    cells,owners,gates,pins,net_roots={}, {}, {}, {}, {}
    input_coords,output_coords={},{}

    def add(key,cell,owner):
        if key in cells:raise MapError(f"Конфликт шаблона сумматора: {key}")
        if len(cells)>=max_cells:raise MapError(f"Схема превышает лимит {max_cells} клеток")
        validate_cell(*key,cell)
        cells[key],owners[key]=cell,owner

    def gate(key,node,cell,arguments,input_pins):
        add(key,cell,'gate:'+node['id'])
        gates[key]=dict(node,inputs=arguments)
        pins[key]=input_pins

    previous=(-1,2) if initial!='const0' else None
    if previous is not None:
        add(previous,Cell(14,1,True),initial)
        net_roots[initial]=previous
        if initial in primary:
            input_coords[initial]={'contact':list(previous),'fixture':[-2,2],'rotation':1}
        else:add((-2,2),Cell(2,1),'constant:const1')
    for i,group in enumerate(chain):
        x=2*i
        a,b=sorted((group['a'],group['b']),key=lambda net:primary[net])
        top,bottom=(x,0),(x,3)
        add(top,Cell(12,2),a);add(bottom,Cell(12,0),b)
        input_coords[a]={'contact':list(top),'fixture':[x,-1],'rotation':2}
        input_coords[b]={'contact':list(bottom),'fixture':[x,4],'rotation':0}
        net_roots[a],net_roots[b]=top,bottom
        arguments,input_pins=[a,b],[top,bottom]
        if previous is not None:
            arguments.append(group['cin']);input_pins.append(previous)
        gate((x,1),by_id[group['sum_id']],Cell(17,1),arguments,input_pins)
        gate((x,2),by_id[group['cout_id']],Cell(16,1),arguments,input_pins)
        sum_wire=(x+1,1)
        add(sum_wire,Cell(10,2),group['sum']);net_roots[group['sum']]=sum_wire
        s= buffers[group['sum']][0]
        gate((x+1,3),s,Cell(1,2),[group['sum']],[sum_wire])
        output_coords[s['output']]={'contact':[x+1,3],'fixture':[x+1,4],'rotation':0}
        previous=(x+1,2)
        add(previous,Cell(14,1,True) if i<len(chain)-1 else Cell(1,1),group['cout'])
        net_roots[group['cout']]=previous
    cout=buffers[chain[-1]['cout']][0]
    x=2*len(chain)
    gate((x,2),cout,Cell(1,1),[chain[-1]['cout']],[previous])
    output_coords[cout['output']]={'contact':[x,2],'fixture':[x+1,2],'rotation':0}
    inputs={name:[{'index':e['index'],**input_coords[e['net']]} for e in es] for name,es in graph['inputs'].items()}
    outputs={name:[{'index':e['index'],**output_coords[e['net']]} for e in es] for name,es in graph['outputs'].items()}
    # Preserve a vector interface as one ordered bundle, including reversed indices.
    for ports in (inputs,outputs):
        for es in ports.values():
            if len(es)<2:continue
            points=[e['contact'] for e in es]
            steps={(b[0]-a[0],b[1]-a[1]) for a,b in zip(points,points[1:])}
            if len(steps)!=1:return None
            dx,dy=next(iter(steps))
            if not ((dx==0)!=(dy==0)) or abs(dx)+abs(dy)>2:return None
    validate_connections(cells,owners,gates,pins,net_roots)
    meta={'schema':1,'top':graph['top'],'map_hash':map_hash(cells),'profile':'GraphDLC-01232bd',
          'verified_against_current_game':False,'inputs':inputs,'outputs':outputs,'settle_ticks':depth_of(cells)+2,
          'cells':len(cells),'layout':'compact-native-adder-v1','port_layout':'parallel-bit-slices',
          'bounds':bounds_of(cells),'adder_bits':len(chain),
          'logic_core':logic_core_metrics(cells,gates,output_nets),
          'gate_labels':[{'at':list(p),'op':n['op'],'id':n['id']} for p,n in gates.items()],
          'optimization':{'objective':'native_threshold_and_parity_bit_slices','logical_gates_per_bit':2,'io_in_objective':False}}
    from signal_metadata import describe_signals
    meta['signals']=describe_signals(graph,cells,owners,gates)
    return cells,meta
