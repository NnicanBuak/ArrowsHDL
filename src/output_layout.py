"""Route a core once, then place external output terminals around that core."""
from copy import deepcopy
from arrowasm import MapError
from arrow_layout import logic_core_metrics, edges, depth_of, bounds_of, destinations


def exterior_bounds(cells, inputs, outputs):
    """Include visible Source/Target cells when comparing complete map sizes."""
    points=set(cells)
    points.update(tuple(e['fixture']) for ports in (inputs,outputs)
                  for entries in ports.values() for e in entries)
    return bounds_of(points)


def candidate_score(candidate):
    """Compare core/bus layouts after each has selected its smallest output map."""
    cells,meta=candidate
    full=exterior_bounds(cells,meta['inputs'],meta['outputs'])
    return (meta['logic_core']['cells'],meta['logic_core']['bounds']['area'],
            len(cells),full['area'],meta['settle_ticks'])


def route_with_outputs(graph, placement, max_cells, routed_seed=None):
    from compact_layout import Router
    seed=deepcopy(routed_seed) if routed_seed is not None else Router(graph,1,max_cells,deepcopy(placement))
    old_terminals={p for p,n in seed.gates.items() if n['output'] in seed.output_nets}
    shared_pins={pin for p,pins in seed.pins.items() if p not in old_terminals for pin in pins}
    for p in old_terminals:
        node=seed.gates[p]
        for net,pin in zip(node['inputs'],seed.pins[p]):
            seed.sinks[net]=[q for q in seed.sinks[net] if q!=pin or q in shared_pins]
            if pin not in shared_pins and pin not in seed.roots.values() and pin not in seed.gates:
                seed.cells.pop(pin,None);seed.owners.pop(pin,None);seed.outs.pop(pin,None)
            elif pin in seed.outs:seed.outs[pin].discard(p)
        del seed.cells[p],seed.owners[p],seed.gates[p],seed.pins[p]
    input_fixtures={tuple(e['fixture']) for es in seed.inputs.values() for e in es}
    output_fixtures={tuple(e['fixture']) for es in seed.outputs.values() for e in es}
    seed.reserved.difference_update(output_fixtures-input_fixtures)
    seed.routing_limits=[None,None,None,None]
    for entries in seed.inputs.values():
        for entry in entries:
            x,y=entry['contact'];axis={1:0,2:1,3:2,0:3}[entry['rotation']]
            value=x if axis in (0,2) else y
            old=seed.routing_limits[axis]
            seed.routing_limits[axis]=value if old is None else (max(old,value) if axis<2 else min(old,value))
    seed.bounds=(min(p[0] for p in seed.cells),min(p[1] for p in seed.cells),
                 max(p[0] for p in seed.cells),max(p[1] for p in seed.cells))
    seed.fixed_cells=set(seed.cells)
    seed.fixed_outs={p:set(v) for p,v in seed.outs.items()}
    seed.route()
    internal={p for p,n in seed.gates.items() if n['output'] not in seed.output_nets}
    links=edges(seed.cells)
    reverse={p:[] for p in seed.cells}
    for p,targets in links.items():
        for q in targets:reverse[q].append(p)
    def reach(starts,graph):
        seen=set(starts);pending=list(starts)
        while pending:
            for q in graph[pending.pop()]:
                if q not in seen:seen.add(q);pending.append(q)
        return seen
    constants={p for p,c in seed.cells.items() if c.type==2}
    ancestors=reach(internal,reverse)
    fixed=reach(internal|constants,links)&ancestors
    primary={e['net'] for es in graph['inputs'].values() for e in es}
    vertices,positions,_=placement
    outputs=[i for i,v in enumerate(vertices) if v['kind']=='gate' and v['node']['output'] in seed.output_nets]
    terminals=old_terminals
    preserved=fixed|{p for p,net in seed.owners.items() if net in primary and p in ancestors}|constants
    preserved.update(seed.roots[n] for n in primary|{'const0','const1'} if n in seed.roots)
    preserved-=terminals
    perimeter=preserved
    minx,maxx=min(p[0] for p in perimeter),max(p[0] for p in perimeter)
    miny,maxy=min(p[1] for p in perimeter),max(p[1] for p in perimeter)
    trials=[];failures=[]
    input_faces={}
    for entries in seed.inputs.values():
        for entry in entries:
            side={1:'left',2:'top',0:'bottom',3:'right'}[entry['rotation']]
            input_faces[side]=entry['contact'][0 if side in ('left','right') else 1]
    # Outputs may share an exterior face with inputs, at another free slot.
    from itertools import product
    for (side,rotation),offset,align in product(
            (('right',1),('bottom',2),('top',0),('left',3)),(0,1),('driver','center','end')):
            candidate=deepcopy(placement)
            vs,ps,_=candidate
            for j,i in enumerate(outputs):
                driver=seed.roots[vertices[i]['node']['inputs'][0]]
                along=(driver[1] if side in ('right','left') else driver[0]) if align=='driver' else ((maxy+1 if side in ('right','left') else maxx+1) if align=='end' else ((miny+maxy)//2 if side in ('right','left') else (minx+maxx)//2))+j*2
                point=(maxx+offset,along) if side=='right' else (minx-offset,along) if side=='left' else (along,maxy+offset) if side=='bottom' else (along,miny-offset)
                if side in input_faces:
                    point=(input_faces[side],point[1]) if side in ('left','right') else (point[0],input_faces[side])
                dx,dy={1:(1,0),2:(0,1),0:(0,-1),3:(-1,0)}[rotation]
                pin=(point[0]-dx,point[1]-dy)
                net=vertices[i]['node']['inputs'][0]
                direct=next((p for p,n in seed.gates.items() if n['output']==net
                             and point in destinations(p,seed.cells[p])),None)
                if direct is not None:pin=direct
                vs[i]=dict(vs[i],rotation=rotation,pins=[pin])
                ps[i]=point
            try:
                if any(ps[i] in preserved for i in outputs):
                    raise MapError('Внешний контакт вывода занят сохранённой разводкой')
                router=Router(graph,1,max_cells,candidate)
                for p in preserved:
                    if p in router.cells and router.owners[p]!=seed.owners[p]:
                        raise MapError('Внешний вывод пересекает фиксированное ядро')
                    router.cells[p]=seed.cells[p]
                    router.owners[p]=seed.owners[p]
                    if p in seed.outs:router.outs[p]=set(seed.outs[p])-terminals
                router.fixed_cells=set(router.cells)
                router.fixed_outs={p:set(v) for p,v in router.outs.items()}
                router.core_sinks={}
                cells=router.route()
                metrics=logic_core_metrics(cells,router.gates,router.output_nets)
                actual_links=edges(cells)
                if any(cells[p]!=seed.cells[p] for p in internal):
                    raise MapError('Подключение вывода изменило ядро')
                if any({q for q in actual_links[p] if q in fixed}!={q for q in links[p] if q in fixed} for p in fixed):
                    raise MapError('Подключение вывода изменило внутренние соединения')
                trials.append((cells,router,{'side':side,'align':align,'offset':offset,'core':metrics,
                                            'bounds':exterior_bounds(cells,router.inputs,router.outputs),
                                            'ticks':depth_of(cells)+2}))
            except MapError as error:
                failures.append({'side':side,'align':align,'offset':offset,'reason':str(error)})
    if not trials:
        raise MapError(f'Вывод не подключён к фиксированному ядру: {failures[-1]["reason"]}')
    cells,router,selected=min(trials,key=lambda t:(t[2]['core']['cells'],t[2]['core']['bounds']['area'],
                                                  t[2]['bounds']['area'],len(t[0]),t[2]['ticks']))
    selected=dict(selected,cells=len(cells))
    router.output_search={'core_frozen':True,'core_connections_verified':True,'selected':selected,
                          'objective':'min_core_then_full_area_then_cells_and_ticks',
                          'candidates':[dict(m,cells=len(c)) for c,r,m in trials], 'rejected':failures}
    return cells,router
