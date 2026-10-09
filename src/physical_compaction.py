"""Compact a routed DAG using exact arrow connectivity, independent of HDL ops.

Relays may disappear only when every predecessor can emit precisely the new
edges. Coordinate cuts must preserve all edges, fan-in, fixtures and bus order.
This is a physical optimization: it does not rewrite the Boolean graph.
"""
from collections import defaultdict
from copy import deepcopy

from arrowasm import Cell
from arrow_layout import bounds_of, destinations, edges


def no_size_regression(candidate,baseline):
    from output_layout import exterior_bounds
    cells,meta=candidate;old,before=baseline
    return (len(cells)<=len(old)
            and exterior_bounds(cells,meta['inputs'],meta['outputs'])['area']<=exterior_bounds(old,before['inputs'],before['outputs'])['area']
            and meta['logic_core']['cells']<=before['logic_core']['cells']
            and meta['logic_core']['bounds']['area']<=before['logic_core']['bounds']['area'])


def compact_router(router, move=True):
    from compact_layout import wire_cell
    from input_buses import verify_exterior
    cells=dict(router.cells)
    gates=dict(router.gates)
    ports=[entry for kind in (router.inputs,router.outputs) for es in kind.values() for entry in es]
    fixtures={tuple(e['fixture']):Cell(22,e['rotation']) for es in router.inputs.values() for e in es}
    fixtures.update({tuple(e['fixture']):Cell(23,0) for es in router.outputs.values() for e in es})
    physical=dict(cells)
    physical.update(fixtures)
    links={p:set(qs) for p,qs in edges(physical).items()}
    protected=set(gates)|set(fixtures)|{tuple(e['contact']) for e in ports}
    owner=dict(router.owners)
    origin={p:p for p in physical}
    removed=cuts=0
    transformations=[]

    def encode(points,arcs):
        result={}
        for p,cell in points.items():
            targets=arcs[p]
            if cell.type in (1,6,7,8,10,11,12,13,14) and targets:
                value=wire_cell(p,targets)
            elif cell.type in (15,16,17,22) and targets:
                value=next((Cell(cell.type,r,cell.mirrored) for r in range(4)
                            if set(destinations(p,Cell(cell.type,r,cell.mirrored)))==targets),None)
            else:value=cell
            if value is None:return None
            result[p]=value
        actual={p:set(qs) for p,qs in edges(result).items()}
        if actual!=arcs:return None
        if any(p in arcs[q] for p,qs in arcs.items() for q in qs):return None
        return result

    def prune():
        nonlocal physical,links,removed
        changed=True
        while changed:
            changed=False
            incoming=defaultdict(set)
            for p,qs in links.items():
                for q in qs:incoming[q].add(p)
            for p in sorted(physical):
                if p in protected or physical[p].type not in (1,6,7,8,10,11,12,13,14):continue
                # Single-input relays preserve the function of every logical
                # merge. Multi-input arrows stay in place even if unlabelled.
                if len(incoming[p])!=1 or not links[p]:continue
                previous=next(iter(incoming[p]))
                if any(q in links[previous] for q in links[p]):continue
                if previous in gates and gates[previous]['op'] not in ('OR','BUF'):continue
                targets=(links[previous]-{p})|links[p]
                if physical[previous].type not in (1,6,7,8,10,11,12,13,14):continue
                value=wire_cell(previous,targets)
                if value is None or any(previous in links[q] for q in targets):continue
                # The removed relay has one predecessor. Only that emission
                # changes; exact wire encoding cannot introduce other edges.
                physical[previous]=value;links[previous]=targets
                del physical[p],links[p]
                removed+=1;changed=True
                break

    def mapped_ports(mapping):
        return {kind:{name:[dict(e,contact=list(mapping[tuple(e['contact'])]),
                                fixture=list(mapping[tuple(e['fixture'])])) for e in es]
                      for name,es in values.items()}
                for kind,values in (('inputs',router.inputs),('outputs',router.outputs))}

    def bus_valid(meta):
        config=router.netlist.get('_input_bus_config',{})
        groups=config.get('groups',[])
        # Unspecified banks and explicit numeric gaps keep their exact pitch.
        constraints=groups if groups else [[name] for name in router.inputs]
        for names in constraints:
            old=[e for name in names for e in router.inputs[name]]
            new=[e for name in names for e in meta['inputs'][name]]
            if len(old)<2:continue
            old_steps=[(b['fixture'][0]-a['fixture'][0],b['fixture'][1]-a['fixture'][1]) for a,b in zip(old,old[1:])]
            new_steps=[(b['fixture'][0]-a['fixture'][0],b['fixture'][1]-a['fixture'][1]) for a,b in zip(new,new[1:])]
            if config.get('gap')=='auto' and groups:
                axis=1 if old[0]['rotation'] in (1,3) else 0
                if any(step[1-axis]!=0 or step[axis]<=0 for step in new_steps):return False
            elif old_steps!=new_steps:return False
        # Output buses also retain order and pitch.
        for name,old in router.outputs.items():
            new=meta['outputs'][name]
            if any((b['contact'][0]-a['contact'][0],b['contact'][1]-a['contact'][1])!=
                   (d['contact'][0]-c['contact'][0],d['contact'][1]-c['contact'][1])
                   for a,b,c,d in zip(old,old[1:],new,new[1:])):return False
        return True

    prune()
    if move and len(physical)<=512:
        while True:
            best=None
            for axis in (0,1):
                coordinates={p[axis] for p in physical}
                for boundary in sorted({v for p in coordinates for v in (p,p+1) if min(coordinates)<v<=max(coordinates)}):
                    mapping={p:tuple(v-(i==axis and v>=boundary) for i,v in enumerate(p)) for p in physical}
                    if len(set(mapping.values()))!=len(mapping):continue
                    arcs={mapping[p]:{mapping[q] for q in qs} for p,qs in links.items()}
                    points={mapping[p]:cell for p,cell in physical.items()}
                    result=encode(points,arcs)
                    if result is None:continue
                    original_to_new={p:mapping[q] for p,q in origin.items() if q in mapping}
                    meta=mapped_ports(original_to_new)
                    if not bus_valid(meta):continue
                    actual={p:c for p,c in result.items() if c.type not in (22,23)}
                    try:verify_exterior(actual,meta)
                    except ValueError:continue
                    score=(bounds_of(result)['area'],bounds_of(actual)['area'],axis,boundary)
                    if best is None or score<best[0]:best=score,mapping,result,arcs
            if best is None:break
            _,mapping,physical,links=best
            transformations.append(best[0][2:])
            origin={p:mapping[q] for p,q in origin.items() if q in mapping}
            gates={mapping[p]:node for p,node in gates.items()}
            protected={mapping[p] for p in protected}
            cuts+=1
            prune()

    # Rebuild routing metadata from exact final arcs, including eliminated pins.
    inverse={q:p for p,q in origin.items() if q in physical}
    router.cells={p:c for p,c in physical.items() if c.type not in (22,23)}
    router.gates=gates
    router.owners={p:owner[inverse[p]] for p in router.cells}
    router.inputs,router.outputs=(mapped_ports(origin)[k] for k in ('inputs','outputs'))
    reverse=defaultdict(list)
    for p,qs in links.items():
        for q in qs:
            if p in router.cells:reverse[q].append(p)
    def net_of(p):return gates[p]['output'] if p in gates else router.owners[p].removeprefix('constant:')
    router.pins={p:[next(q for q in reverse[p] if net_of(q)==net) for net in node['inputs']]
                 for p,node in gates.items()}
    router.roots={net:origin[p] for net,p in router.roots.items() if p in origin and origin[p] in router.cells}
    for p,node in gates.items():
        if node['output'] not in router.roots:router.roots[node['output']]=p
    router.flexible_gates={p for p,n in gates.items() if n['op'] in ('OR','BUF')
                           and n['output'] not in router.output_nets and router.roots[n['output']]==p}
    router.outs={p:set(links[p]) for p in router.cells if (p not in gates and router.cells[p].type!=2) or p in router.flexible_gates}
    router.sinks=defaultdict(list);router.pin_consumers=defaultdict(list)
    for p,node in gates.items():
        for net,pin in zip(node['inputs'],router.pins[p]):
            router.sinks[net].append(pin);router.pin_consumers[pin].append(p)
    router.source_positions={net:origin[p] for net,p in router.source_positions.items() if p in origin and origin[p] in router.cells}
    router.routing_limits=[None,None,None,None]
    for kind in (router.inputs,router.outputs):
        for es in kind.values():
            for e in es:
                x,y=e['contact'];fx,fy=e['fixture']
                axis=0 if fx<x else 2 if fx>x else 1 if fy<y else 3
                value=x if axis in (0,2) else y;old=router.routing_limits[axis]
                router.routing_limits[axis]=value if old is None else max(old,value) if axis<2 else min(old,value)
    router.reserved={p for p,c in physical.items() if c.type in (22,23)}
    router.fixed_cells=set(router.cells);router.fixed_outs={p:set(qs) for p,qs in router.outs.items()}
    router.bounds=tuple(bounds_of(router.cells)[k][i] for k in ('min','max') for i in (0,1))
    router.core_sinks={}
    router.validate()
    router.physical_compaction={'removed_relays':removed,'coordinate_cuts':cuts,
                                'coordinate_transforms':[list(t) for t in transformations],
                                'exact_edges_verified':True,'bus_constraints_preserved':True}
    return router.cells


def rebase_blocks(blocks,compaction):
    """Project visual block boxes through the same cuts as physical cells."""
    def project(p):
        p=list(p)
        for axis,boundary in (compaction or {}).get('coordinate_transforms',[]):
            p[axis]-=p[axis]>=boundary
        return p
    result=[]
    for block in blocks:
        x,y=block['at'];end=project((x+block['width']-1,y+block['height']-1));start=project((x,y))
        result.append(dict(block,at=start,width=end[0]-start[0]+1,height=end[1]-start[1]+1))
    return result


def compact_manifest(cells,manifest,graph):
    """Common final pass for backends that do not expose a Router instance."""
    from compact_layout import Router
    from arrow_layout import depth_of,logic_core_metrics
    from mapdata import map_hash
    from signal_metadata import describe_signals
    from output_layout import exterior_bounds
    signals=manifest.get('signals')
    if not signals:return cells,manifest
    router=Router.__new__(Router)
    router.native_links=set();router.native_initial={}
    router.netlist=graph
    router.cells=dict(cells);router.gates={};router.owners={}
    for net in signals['nets']:
        driver=net['driver']
        if driver:
            p=tuple(driver['at'])
            router.gates[p]=dict(driver,inputs=net['inputs'],output=net['id'])
        for p in net['cells']:router.owners[tuple(p)]=net['id']
    for p,node in router.gates.items():router.owners[p]='gate:'+node['id']
    router.inputs=deepcopy(manifest['inputs']);router.outputs=deepcopy(manifest['outputs'])
    router.output_nets={node['output'] for p,node in router.gates.items()
                        if p in {tuple(e['contact']) for es in router.outputs.values() for e in es}}
    router.roots={node['output']:p for p,node in router.gates.items()}
    for name,es in graph['inputs'].items():
        for source,entry in zip(es,router.inputs[name]):router.roots[source['net']]=tuple(entry['contact'])
    for net in signals['nets']:
        if net['id'] in ('const0','const1') and net['cells']:
            router.roots[net['id']]=tuple(net['cells'][0])
    router.source_positions=dict(router.roots)
    before={'cells':len(cells),'bounds':manifest['bounds'],'core':manifest['logic_core'],
            'ticks':manifest['settle_ticks']}
    compact_router(router)
    result=deepcopy(manifest)
    result.update(cells=len(router.cells),bounds=bounds_of(router.cells),inputs=router.inputs,outputs=router.outputs,
                  map_hash=map_hash(router.cells),settle_ticks=depth_of(router.cells)+2,
                  routing_limits=router.routing_limits,
                  logic_core=logic_core_metrics(router.cells,router.gates,router.output_nets),
                  physical_compaction=dict(router.physical_compaction,before=before),
                  gate_labels=[dict(at=list(p),op=n['op'],id=n['id'],scope=n.get('scope','core')) for p,n in router.gates.items()])
    available={e['net'] for es in graph['inputs'].values() for e in es}|{'const0','const1'}
    pending=list(router.gates.values());ordered=[]
    while pending:
        ready=[n for n in pending if set(n['inputs'])<=available]
        if not ready:raise ValueError('Physical compaction left an undriven net')
        for n in ready:ordered.append(n);available.add(n['output']);pending.remove(n)
    physical_graph=deepcopy(dict(graph,nodes=ordered))
    result['signals']=describe_signals(physical_graph,router.cells,router.owners,router.gates)
    if 'module_blocks' in result:
        result['module_blocks']=rebase_blocks(result['module_blocks'],router.physical_compaction)
    result['full_bounds']=exterior_bounds(router.cells,router.inputs,router.outputs)
    return router.cells,result
