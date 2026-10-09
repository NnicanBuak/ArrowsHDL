"""Reuse verified physical wires when only a subset of a netlist changes."""
from arrow_layout import destinations
from arrowasm import MapError


def prune_dead_wires(cells,protected):
    """Trim wire leaves which cannot reach a retained gate, pin or native block."""
    from compact_layout import wire_cell
    protected=set(protected)
    if not protected<=cells.keys():raise MapError('Protected cell is absent')
    reverse={p:[] for p in cells}
    for p,c in cells.items():
        for q in destinations(p,c):
            if q in cells:reverse[q].append(p)
    live=set(protected);pending=list(protected)
    while pending:
        for p in reverse[pending.pop()]:
            if p not in live:live.add(p);pending.append(p)
    wire_types={1,6,7,8,10,11,12,13,14}
    result={p:c for p,c in cells.items() if p in live or c.type not in wire_types}
    for p,c in list(result.items()):
        if p in protected or c.type not in wire_types:continue
        targets={q for q in destinations(p,c) if q in result}
        replacement=wire_cell(p,targets)
        if replacement is None:raise MapError('Cannot trim wire branch at '+str(p))
        result[p]=replacement
    return result


def changed_nets(before, after):
    old={n['output']:n for n in before['nodes']}
    new={n['output']:n for n in after['nodes']}
    affected=set()
    for net in old.keys() | new.keys():
        a,b=old.get(net),new.get(net)
        if a and b and (a['op'],a['inputs'])==(b['op'],b['inputs']):continue
        affected.add(net)
        affected.update((a or {}).get('inputs',[]))
        affected.update((b or {}).get('inputs',[]))
    return affected


def restore_wires(router, cells, owners, affected):
    """Keep compatible paths mutable, preserve the new placement's fixed pins.

    The caller installs native black boxes before restoring and supplies their
    normal validator. Changed branches are rebuilt, and retained buses can
    participate in congestion repair. Physical validation remains mandatory.
    """
    affected=set(affected)
    router.fixed_cells=set(router.cells)
    router.fixed_outs={p:set(qs) for p,qs in router.outs.items()}
    for p,c in cells.items():
        owner=owners.get(p)
        if owner in affected or owner not in router.roots or p in router.fixed_cells:continue
        router.cells[p]=c;router.owners[p]=owner
        router.outs[p]=set(destinations(p,c))
    for p in router.fixed_cells:
        net=router.owners[p]
        if p in router.flexible_gates:net=router.gates[p]['output']
        if net not in affected and p in router.outs and p in cells:
            old_net=owners.get(p)
            if old_net==router.owners[p]:
                router.outs[p]=set(destinations(p,cells[p]))
    router.initial_routing_nets=affected
    # Detect truncated or incompatible snapshot ownership before routing.
    for net in router.roots:
        if net in affected:continue
        if any(p not in router.tree(net) for p in router.sinks[net]):
            router.initial_routing_nets.add(net)
    return len(cells)-len(router.cells)
