"""Route-driven placement search on units and HDL modules, never circuit names."""
from collections import defaultdict
from copy import deepcopy
from itertools import product
import os
import json

_CACHE={}

from arrowasm import Cell,MapError
from arrow_layout import GATE_TYPES,bounds_of,destinations
from packed_layout import arrange_packed,localize_unaries,units_of
from input_buses import apply_placement
from output_layout import exterior_bounds,route_with_outputs


def state_key(placement,graph):
    vertices,positions,_=placement
    return (tuple(positions),tuple((tuple(tuple(p) for p in v.get('pins',[])),v.get('rotation',1)) for v in vertices),
            tuple(graph.get('_bus_sides',[])),graph.get('_port_margin',0),
            tuple(sorted(graph.get('_contact_offsets',{}).items())))


def moves(placement,graph):
    vertices,positions,_=placement
    groups=defaultdict(list);modules=defaultdict(list)
    for i,v in enumerate(vertices):
        if 'pack_unit' not in v:continue
        groups[v['pack_unit']].append(i)
        if v['kind']=='gate':modules[v['node'].get('scope','core').split('.')[0]].append(i)
    if len(modules)>1:
        for name,ids in modules.items():groups['module:'+name]=ids
    shifts=((1,0),(-1,0),(0,1),(0,-1),(0,2),(0,-2),(0,3),(0,-3),(2,0),(-2,0))
    for name,ids in sorted(groups.items(),reverse=True):
        for dx,dy in shifts:
            candidate=deepcopy(placement)
            for i in ids:
                x,y=candidate[1][i];candidate[1][i]=(x+dx,y+dy)
                candidate[0][i]['pins']=[(x+dx,y+dy) for x,y in candidate[0][i].get('pins',[])]
            yield candidate,graph
        anchor=positions[ids[0]]
        for rotation in (1,2,3):
            candidate=deepcopy(placement)
            def rotate(p):
                x,y=p[0]-anchor[0],p[1]-anchor[1]
                for _ in range(rotation):x,y=-y,x
                return x+anchor[0],y+anchor[1]
            for i in ids:
                candidate[1][i]=rotate(candidate[1][i])
                candidate[0][i]['pins']=[rotate(p) for p in candidate[0][i].get('pins',[])]
                candidate[0][i]['rotation']=(candidate[0][i].get('rotation',1)+rotation)%4
            yield candidate,graph
    parents={v['node']['output']:i for i,v in enumerate(vertices) if v['kind']=='gate'}
    for i,v in enumerate(vertices):
        if v.get('pack_role')!='merge':continue
        node=v['node']
        roots=[next(destinations(positions[parents[net]],Cell(GATE_TYPES[vertices[parents[net]]['node']['op']],vertices[parents[net]].get('rotation',1)))) for net in node['inputs']]
        from compact_layout import wire_cell
        for dx,dy in shifts:
            candidate=deepcopy(placement);x,y=positions[i];at=(x+dx,y+dy)
            pins=[positions[parents[net]] if root==at else root for net,root in zip(node['inputs'],roots)]
            if any(pin!=positions[parents[net]] and wire_cell(pin,{at}) is None for net,pin in zip(node['inputs'],pins)):continue
            candidate[1][i]=at;candidate[0][i]['pins']=pins
            yield candidate,graph
    config=graph.get('_input_bus_config',{})
    if config.get('gap')=='auto':
        for es in graph['inputs'].values():
            for entry in es:
                net=entry['net']
                for delta in (-2,-1,1,2):
                    offsets=dict(graph.get('_contact_offsets',{}));offsets[net]=offsets.get(net,0)+delta
                    yield placement,dict(graph,_contact_offsets=offsets)
    sides=list(graph.get('_bus_sides',[]))
    for i in range(len(sides)):
        for side in ('left','top','bottom','right'):
            if side==sides[i]:continue
            candidate=sides[:];candidate[i]=side
            yield placement,dict(graph,_bus_sides=candidate)


def score_map(cells,meta):
    full=exterior_bounds(cells,meta['inputs'],meta['outputs'])
    return (len(cells),full['area'],meta['logic_core']['bounds']['area'],meta['logic_core']['cells'],meta['settle_ticks'])


def block_boxes(placement,compaction):
    from physical_compaction import rebase_blocks
    groups=defaultdict(list)
    for v,p in zip(placement[0],placement[1]):
        if v['kind']=='gate' and 'pack_unit' in v:groups[v['pack_unit']].append(p)
    blocks=[]
    for name,points in groups.items():
        b=bounds_of(points)
        blocks.append({'id':name,'at':b['min'],'width':b['width'],'height':b['height'],'operators':len(points)})
    return rebase_blocks(blocks,compaction)


def search_placement(graph,max_cells=100000):
    key=(json.dumps(graph,sort_keys=True,separators=(',',':')),max_cells)
    if key in _CACHE:return deepcopy(_CACHE[key])
    result=_search_placement(graph,max_cells)
    if len(_CACHE)>=16:_CACHE.pop(next(iter(_CACHE)))
    _CACHE[key]=deepcopy(result)
    return result


def _search_placement(graph,max_cells=100000):
    """Search flat and hierarchical compositions, with shared/local NOT variants."""
    from compact_layout import router_manifest
    base=dict(graph,_pack_cones=True,_adapt_bus=True,_adaptive_ports=True,_port_margin=0)
    variants=[base,localize_unaries(base)]
    if not any(u['kind']=='join' for variant in variants for u in units_of(variant)) and not graph.get('instances'):return None
    trace=lambda msg:print(msg,flush=True) if os.environ.get('ARROWSHDL_LAYOUT_TRACE')=='1' else None
    visited=set();attempts=valid=0;best=None;beam=[];failed=[];summaries=[]
    def evaluate(placement,variant):
        nonlocal attempts,valid,best
        key=state_key(placement,variant)
        if key in visited:return None
        visited.add(key);attempts+=1
        try:
            actual=apply_placement(variant,deepcopy(placement))
            cells,router=route_with_outputs(variant,actual,max_cells)
            meta=router_manifest(variant,router,cells,'compact-graph-search-v1')
            score=score_map(cells,meta);valid+=1
            summaries.append({'cells':len(cells),'ticks':meta['settle_ticks'],'core':meta['logic_core'],
                              'bounds':meta['bounds'],'full_bounds':exterior_bounds(cells,meta['inputs'],meta['outputs']),
                              'layout':meta['layout']})
            record=(score,placement,variant,cells,meta)
            if best is None or score<best[0]:
                best=record;trace(f'graph search: cells={len(cells)}, full area={score[1]}, core area={score[2]}, attempts={attempts}')
            return record
        except MapError:return None
    groups=graph.get('_input_bus_config',{}).get('groups',[])
    side_choices=lambda:product(('left','top','bottom','right'),repeat=len(groups))
    compositions=(True,False) if len({n.get('scope','core').split('.')[0] for n in graph['nodes']})>1 else (True,)
    for variant in variants:
        for combine,aspect in product(compositions,(0.5,1.0,1.4,2.5)):
            variant=dict(variant,_flatten_modules=combine)
            try:placement,_=arrange_packed(variant,corridor=0,aspect=aspect,frame=(100000,100000),combine=combine)
            except MapError:continue
            for sides in side_choices():
                trial=dict(variant,_bus_sides=sides)
                result=evaluate(placement,trial)
                if result:beam.append(result)
                else:failed.append((placement,trial))
    # Repair crowded seeds by changing connected units, not by adding a global
    # empty corridor. Top/bottom/left/right contact trials share the same core.
    for placement,variant in failed:
        for candidate,other in moves(placement,variant):
            result=evaluate(candidate,other)
            if result:beam.append(result)
    if not beam:return None
    def shortlist(records):
        selected=[];keys=set()
        for record in sorted(records,key=lambda r:r[0]):
            key=state_key(record[1],record[2])
            if key in keys:continue
            keys.add(key);selected.append(record)
            if len(selected)==3:break
        return selected
    beam=shortlist(beam);stalls=0;rounds=0
    while stalls<6:
        previous=best[0];records=list(beam);rounds+=1
        for _,placement,variant,_,_ in beam:
            for candidate,other in moves(placement,variant):
                result=evaluate(candidate,other)
                if result:records.append(result)
        beam=shortlist(records)
        stalls=stalls+1 if best[0]>=previous else 0
        trace(f'graph search: round={rounds}, attempts={attempts}, valid={valid}, best={best[0]}')
    _,placement,variant,cells,meta=best
    meta['module_blocks']=block_boxes(placement,meta.get('physical_compaction'))
    meta['full_bounds']=exterior_bounds(cells,meta['inputs'],meta['outputs'])
    meta['mapped_logic_nodes']=len(variant['nodes'])
    meta['placement_search']={'attempts':attempts,'valid':valid,'rounds':rounds,'beam_width':3,
                              'localized_unaries':variant.get('_localized_unaries',0),
                              'bus_sides':list(variant.get('_bus_sides',[])),
                              'contact_offsets':variant.get('_contact_offsets',{}),
                              'flat_composition':variant.get('_flatten_modules',True),
                              'composition_modes':list(compositions),
                              'objective':'min_cells_then_full_area_core_area_core_cells_and_ticks',
                              'operations':['unit_translation','unit_rotation','merge_position','module_translation','module_rotation','bus_face','individual_auto_pitch'],
                              'external_ports_only':True}
    meta['optimization']={'objective':meta['placement_search']['objective'],
                          'io_in_objective':True,'automatic_input_buses':graph.get('_input_bus_config',{}).get('gap')=='auto',
                          'fixed_input_bus':bool(groups),'candidates':summaries}
    return cells,meta
