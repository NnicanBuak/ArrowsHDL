"""General-purpose placement with a fast default and optional compact search."""
from arrowshdl.arrowasm import MapError
from arrowshdl.tick_layout import place_tick
from arrowshdl.progress import report, phase


def place_auto(graph, *, max_cells=1000000, constraints=None, compact=False):
    source_nodes = len(graph['nodes'])
    sharing, mapping = [], []
    from arrowshdl.technology_mapping import map_native_gates, merge_duplicate_logic,fold_or_cones
    graph,mapping = map_native_gates(graph)
    graph,sharing = merge_duplicate_logic(graph)
    graph,folding=fold_or_cones(graph)
    mapping.extend(folding)
    attempts = []

    def attempt(pitch,aspect=1.0,search=False,seed=0):
        report(0, f'Placement candidate: pitch={pitch}, aspect={aspect:g}, search={search}')
        try:
            cells,meta = place_tick(graph,max_cells=max_cells,constraints=constraints,
                                   automatic=True,pitch=pitch,aspect=aspect,search=search,seed=seed)
        except (MapError,ValueError) as error:
            attempts.append(dict(pitch=pitch,aspect=aspect,search=search,status='rejected',reason=str(error)))
            return None
        attempts.append(dict(pitch=pitch,aspect=aspect,search=search,status='valid',
                             cells=len(cells),area=meta['bounds']['area'],ticks=meta['settle_ticks']))
        return cells,meta

    baseline = None
    with phase(0,20 if compact else 95,'Finding a valid baseline placement'):
        for pitch in (6,8,10,12):
            baseline = attempt(pitch)
            if baseline is not None: break
    if baseline is None:
        raise MapError('Automatic routing failed: '+attempts[-1]['reason'])
    candidates = [baseline]
    if compact:
        for i,(pitch,aspect,seed) in enumerate(((5,1.0,0),(6,0.7,1),(6,1.5,2),(7,1.0,3))):
            with phase(20+18*i,38+18*i,f'Compact search {i+1}/4'):
                candidate = attempt(pitch,aspect,True,seed)
            if candidate is not None and len(candidate[0])<=len(baseline[0]) and candidate[1]['bounds']['area']<=baseline[1]['bounds']['area']:
                candidates.append(candidate)
    cells,meta = min(candidates,key=lambda cm:(len(cm[0]),cm[1]['bounds']['area'],cm[1]['settle_ticks']))
    report(98, 'Validated placement and selected final scheme')
    meta['logic_nodes'] = source_nodes
    meta['technology_nodes'] = len(graph['nodes'])
    meta['technology_mapping'] = mapping
    meta['shared_logic'] = sharing
    meta['optimization'] = dict(mode='compact' if compact else 'default',
        objective='total_arrows_then_total_area_then_propagation_ticks',
        io_in_objective=True,templates=False,attempts=attempts,
        baseline=dict(cells=len(baseline[0]),bounds=baseline[1]['bounds']),
        native_macros_preserved=True)
    return cells,meta
