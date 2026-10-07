"""Search tight mux trees with direct jump inputs and routed OR operators.

Geometry is generated from connectivity and channel count, never from a saved
reference map. A logical OR can use any ordinary routing arrow or splitter.
"""
from itertools import product
from arrowasm import MapError
from arrow_layout import bounds_of,depth_of,logic_core_metrics
from input_buses import verify_exterior
from mapdata import map_hash
from output_layout import exterior_bounds


def dense_candidates(graph,max_cells):
    from native_mux_layout import recognize_mux
    data,select,_=recognize_mux(graph)
    config=graph.get('_input_bus_config',{})
    # A combined explicit bank must stay a single ordered bank. Keep the older
    # bank-aware placer for that constraint; independent banks can hug the core.
    for names in config.get('groups',[]):
        ordered=[e['net'] for name in names for e in graph['inputs'][name]]
        nets=set(ordered)
        if nets & set(data) and nets & set(select):return []
        expected=[net for net in (data if nets & set(data) else select) if net in nets]
        if ordered!=expected:return []
    levels=len(select)
    columns=set()
    for stride in (2,3,4):
        base=tuple(1+i*stride for i in range(levels))
        columns.add(base)
        if levels>2:
            for last_step in (1,2):columns.add(base[:-1]+(base[-2]+last_step,))
    candidates=[]
    for pair_pitch,xs,sel_pitch,merges in product((3,4,5),sorted(columns),(1,2,3),('convergent','bottom')):
        try:candidates.append(dense_candidate(graph,max_cells,pair_pitch,xs,sel_pitch,merges))
        except MapError:pass
    return candidates


def dense_candidate(graph,max_cells,pair_pitch,xs,sel_pitch,merges):
    from native_mux_layout import recognize_mux
    from compact_layout import Router,wire_cell
    from signal_metadata import describe_signals
    data,select,terminal=recognize_mux(graph)
    nodes=[];vertices=[];positions=[];blocks=[];source_at={}
    rows=[1+(i//2)*pair_pitch+i%2 for i in range(len(data))]
    contacts={net:(0,y,(-1,y),1) for net,y in zip(data,rows)}
    contacts.update({net:(1+i*sel_pitch,0,(1+i*sel_pitch,-1),2) for i,net in enumerate(select)})
    config=graph.get('_input_bus_config',{})
    if config.get('groups') and config['gap']!='auto':
        for names in config['groups']:
            nets=[e['net'] for name in names for e in graph['inputs'][name]]
            for i,net in enumerate(nets):
                if net in data:
                    y=1+i*(config['gap']+1);contacts[net]=(0,y,(-1,y),1)
                else:
                    x=1+i*(config['gap']+1);contacts[net]=(x,0,(x,-1),2)
    source_at.update({net:(c[0],c[1]) for net,c in contacts.items()})
    def gate(op,args,point,pins,output=None):
        net=output or f'dense:{len(nodes)}'
        node={'id':f'mux-dense:{len(nodes)}','op':op,'inputs':args,'output':net}
        nodes.append(node)
        vertices.append({'kind':'gate','node':node,'rotation':1,'pins':pins,
                         'flexible_output':op=='OR'})
        positions.append(point);source_at[net]=point
        return net
    def data_pin(net,target):
        source=source_at[net]
        return source if wire_cell(source,{target}) is not None else (target[0]-2,target[1])
    stage=list(zip(data,rows))
    for level,sel in enumerate(select):
        following=[];x=xs[level]
        for i in range(0,len(stage),2):
            (a,ya),(b,yb)=stage[i:i+2];y=(ya+yb)//2
            neg=gate('NOT',[sel],(x,y),[(x,y-1)])
            low=gate('AND',[a,neg],(x+1,y),[data_pin(a,(x+1,y)),(x,y)])
            high=gate('AND',[b,sel],(x+1,y+1),[data_pin(b,(x+1,y+1)),(x,y+1)])
            oy=y if merges=='convergent' and (i//2)%2 else y+1
            low_pin=(x+1,y) if oy==y else (x+2,y)
            high_pin=(x+1,y+1) if oy==y+1 else (x+2,y+1)
            out=gate('OR',[low,high],(x+2,oy),[low_pin,high_pin],
                     output=terminal['output'] if level==len(select)-1 else None)
            following.append((out,oy))
            blocks.append({'id':f'mux{level}:{i//2}','at':[x,y],'width':3,'height':2,'operators':4})
        stage=following
    for net,(x,y,fixture,rotation) in contacts.items():
        vertices.append({'kind':'input','net':net,'fixture':fixture,'rotation':rotation})
        positions.append((x,y))
    technology=dict(graph,nodes=nodes)
    router=Router(technology,1,max_cells,(vertices,positions,{}))
    cells=router.route()
    core=logic_core_metrics(cells,router.gates,router.output_nets)
    full=exterior_bounds(cells,router.inputs,router.outputs)
    selected={'side':'right','align':'driver','fused':True,'core':core,'bounds':full,
              'cells':len(cells),'ticks':depth_of(cells)+2}
    meta={'schema':1,'top':graph['top'],'map_hash':map_hash(cells),
          'profile':'GraphDLC-01232bd','verified_against_current_game':False,
          'inputs':router.inputs,'outputs':router.outputs,'routing_limits':router.routing_limits,
          'settle_ticks':depth_of(cells)+2,'cells':len(cells),'bounds':bounds_of(cells),
          'full_bounds':full,'logic_core':core,'layout':'compact-dense-mux-v1',
          'port_layout':'adaptive-input-buses','io_conflict_fallback':router.io_conflict_fallback,
          'mux_inputs':len(data),'mapped_logic_nodes':len(nodes),'module_blocks':blocks,
          'select_bank':'adaptive-near-gates','pair_pitch':pair_pitch,'stage_columns':list(xs),
          'select_pitch':sel_pitch,'merge_positions':merges,'fused_output':True,
          'output_search':{'core_frozen':not router.io_conflict_fallback,
                           'core_connections_verified':True,'selected':selected,'candidates':[selected]},
          'gate_labels':[{'at':list(p),'op':n['op'],'id':n['id']} for p,n in router.gates.items()],
          'signals':describe_signals(technology,cells,router.owners,router.gates)}
    verify_exterior(cells,meta)
    return cells,meta
