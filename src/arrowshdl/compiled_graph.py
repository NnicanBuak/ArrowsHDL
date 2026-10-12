"""Assemble immutable compiled modules; never synthesize individual instances."""
from collections import defaultdict
from copy import deepcopy
import hashlib
from pathlib import Path
import time
import math
import json

from arrowshdl.arrowasm import Cell,MapError
from arrowshdl.arrow_layout import bounds_of,destinations
from arrowshdl.auto_placement import arrange,fit_ports
from arrowshdl.components import load_component,move,keepout
from arrowshdl.fixed_wiring import FixedWiring
from arrowshdl.mapdata import map_hash,write_json
from arrowshdl.module_cache import compiled_module
from arrowshdl.presentation import port_bits
from arrowshdl.manifest import component_file
from arrowshdl.timing import propagation_bound
from arrowshdl.progress import report, phase


def assemble(project,out,timeout,layout,max_cells,compact):
    blocks={}; compiled={}; cache_records=[]
    total = len({(row['hdl'],json.dumps(row.get('parameters',{}),sort_keys=True),json.dumps(row.get('panel'),sort_keys=True)) for row in project.modules})
    for row in project.modules:
        specialization=(row['hdl'],json.dumps(row.get('parameters',{}),sort_keys=True),json.dumps(row.get('panel'),sort_keys=True))
        if specialization not in compiled:
            index = len(compiled)
            with phase(5+60*index/max(1,total),5+60*(index+1)/max(1,total),f"Compiling module {index+1}/{total}: {row['hdl']}"):
                part,desc,record=compiled_module(project,row,out,timeout,layout,max_cells,compact)
            compiled[specialization]=(part,desc)
            cache_records.append(record)
        blocks[row['name']]=compiled[specialization]
    for row in project.components:
        if row.get('kind')=='text':
            from arrowshdl.text_display import compile_display
            with phase(65,67,f'Preparing text display: {row["name"]}'):
                part,desc=compile_display(project.path.parent,row)
            desc.update(source_map_hash=map_hash(part),interface={'kind':'text display','protocol':'one level signal'})
            blocks[row['name']]=(part,desc)
        else:
            blocks[row['name']]=load_component(component_file(project.path.parent,row['file']))
    for name,(part,desc) in blocks.items():
        frame=bounds_of(part)
        for side in ('inputs','outputs'):
            for port,entries in desc[side].items():
                for entry in entries:
                    if entry.get('panel'): continue
                    x,y=entry['fixture']
                    if frame['min'][0]<=x<=frame['max'][0] and frame['min'][1]<=y<=frame['max'][1]:
                        raise MapError(f'{name}.{port}[{entry["index"]}]: connection fixture is inside the immutable block footprint; expose the port at its outer boundary')
    report(67, f'Placing {len(blocks)} compiled instances')
    names=list(blocks); connections=defaultdict(set)
    for row in project.connections:
        source=row['from'].partition('.')[0];target=row['to'].partition('.')[0]
        if source in blocks and source!=target: connections[target].add(source)
    graph=dict(nodes=[dict(id=name,output=name,inputs=sorted(connections[name])) for name in names])
    frames=[bounds_of(part) for part,desc in blocks.values()]
    failures=[]
    large=len(blocks)>16
    for gap in ((32,48,64) if large else (8,12,20,32,48)):
        macros=[]
        for frame in frames:
            macros.append(({(0,0):None,(frame['width']-1+gap,frame['height']-1+gap):None},[],(0,0)))
        origins=repeated_module_layout(project,blocks,names,frames,connections,gap)
        if origins is None: origins=arrange(graph,macros,pitch=8,cluster=False)
        try:
            with phase(67,90,f'Routing assembly, spacing {gap}'):
                cells,meta=route_project(project,blocks,names,origins,frames,cache_records,out,max_cells,compact,
                                        routing_order='short' if large or gap>=32 else 'fanout')
            meta['optimization']['assembly_gap']=gap
            meta['optimization']['rejected_placements']=failures
            return cells,meta
        except (MapError,ValueError) as error:
            failures.append(dict(gap=gap,reason=str(error)))
    raise MapError('Could not route compiled modules: '+failures[-1]['reason'])


def repeated_module_layout(project,blocks,names,frames,parents,gap):
    """Place repeated compiled units in a regular array with their leaf I/O.

    This is inferred from identical compiled maps and the connection graph;
    it does not depend on HDL names or application-specific tile templates.
    """
    families=defaultdict(list)
    for row in project.modules: families[map_hash(blocks[row['name']][0])].append(row['name'])
    family=max(families.values(),key=len,default=[])
    if len(family)<4: return None
    indices={name:i for i,name in enumerate(names)}
    outgoing={row['from'].partition('.')[0] for row in project.connections}
    children=defaultdict(list)
    for row in project.components:
        name=row['name']
        if len(parents[name])==1 and name not in outgoing:
            parent=next(iter(parents[name]))
            if parent in family: children[parent].append(name)
    sizes={name:(frames[indices[name]]['width'],frames[indices[name]]['height']) for name in names}
    widths={name:sizes[name][0]+sum(sizes[c][0]+gap for c in children[name]) for name in family}
    width=max(widths.values())+gap+4
    height=max(max([sizes[name][1]]+[sizes[c][1] for c in children[name]]) for name in family)+gap+4
    columns=max(1,math.ceil(math.sqrt(len(family))))
    rows=math.ceil(len(family)/columns)
    positions={}
    for i,name in enumerate(family):
        x,y=i%columns*width,i//columns*height;positions[name]=(x,y)
        cursor=x+sizes[name][0]+gap
        for child in children[name]:
            positions[child]=(cursor,y+(sizes[name][1]-sizes[child][1])//2)
            cursor+=sizes[child][0]+gap
    cursor=0
    for name in names:
        if name not in positions:
            positions[name]=(-sizes[name][0]-gap-4,max(0,(rows*height-sizes[name][1])//2)+cursor)
            cursor+=sizes[name][1]+gap+4
    return [positions[name] for name in names]


def route_project(project,blocks,names,origins,frames,cache_records,out,max_cells,compact,routing_order='fanout'):
    cells={}; placed={}; originals={}; reserved=set(); memories=[]; labels=[]
    for name,origin,frame in zip(names,origins,frames):
        part,desc=move(*blocks[name],[origin[0]-frame['min'][0],origin[1]-frame['min'][1]])
        if cells.keys() & part.keys(): raise MapError('Overlapping compiled modules: '+name)
        cells.update(part);placed[name]=desc;originals[name]=part
        reserved.update(keepout(part)-part.keys())
        memories.extend(desc.get('state_boundaries',desc.get('timing',{}).get('state_boundaries',())))
        labels.extend(dict(g,id=name+'.'+g['id'],scope=name) for g in desc.get('gate_labels',()))
        for side in ('inputs','outputs'):
            reserved.update(tuple(e['fixture']) for es in desc[side].values() for e in es)

    public={row['name']:[dict(index=i,net=f"input:{row['name']}:{i}") for i in range(row.get('width',1))] for row in project.inputs}
    endpoints=defaultdict(list); input_sinks=defaultdict(list)
    def target(reference):
        name,separator,port=reference.partition('.')
        if not separator or name not in placed: raise MapError('Unknown input: '+reference)
        return [(name,e) for e in port_bits(placed[name]['inputs'],port)]
    def public_bits(reference):
        try: return port_bits(public,reference)
        except MapError: return None
    for row in project.connections:
        bits=public_bits(row['from'])
        if bits is not None:
            sinks=target(row['to'])
            if len(bits)!=len(sinks): raise MapError('Incompatible width: '+row['from']+' → '+row['to'])
            for bit,(_,entry) in zip(bits,sinks):
                endpoints[bit['net']].append(tuple(entry['fixture']));input_sinks[bit['net']].append(entry)
    frame=bounds_of(cells); used=set()
    inputs=fit_ports(public,endpoints,frame,used)
    exported_inputs={bit['net'] for row in project.outputs for bit in (public_bits(row['from']) or [])}
    direct_inputs=set()
    for name,entries in inputs.items():
        for i,entry in enumerate(entries):
            net=f"input:{name}:{entry['index']}"
            if len(input_sinks[net])==1 and net not in exported_inputs:
                entries[i]=dict(input_sinks[net][0],index=entry['index'])
                direct_inputs.add(net)
    roots={}; targets=defaultdict(list); driven=set(); source_entries={}
    for name,entries in inputs.items():
        for entry in entries:
            net=f"input:{name}:{entry['index']}"
            if net in direct_inputs: continue
            p=tuple(entry['contact']);cells[p]=Cell(1,entry['rotation'])
            roots[net]=next(destinations(p,cells[p]))
            reserved.add(tuple(entry['fixture']))
    constants={}
    def source(reference):
        bits=public_bits(reference)
        if bits is not None: return [(bit['net'],bit['index']) for bit in bits]
        if reference in ('0','1'):
            if reference not in constants:
                p=(frame['min'][0]+2+int(reference)*3,frame['min'][1]-3)
                cells[p]=Cell(25 if reference=='0' else 2,1)
                net='constant:'+reference; roots[net]=(p[0]+1,p[1]);constants[reference]=net
            return [(constants[reference],0)]
        name,separator,port=reference.partition('.')
        if not separator or name not in placed: raise MapError('Unknown output: '+reference)
        result=[]
        for entry in port_bits(placed[name]['outputs'],port):
            p=tuple(entry['fixture']);net=f"block:{name}:{p}"
            roots[net]=p;source_entries[net]=entry; result.append((net,entry['index']))
        return result
    for row in project.connections:
        outputs=source(row['from']);sinks=target(row['to'])
        if len(outputs)!=len(sinks): raise MapError('Incompatible width: '+row['from']+' → '+row['to'])
        for (net,_),(name,entry) in zip(outputs,sinks):
            key=(name,tuple(entry['contact']))
            if key in driven: raise MapError('Multiple drivers: '+row['to'])
            driven.add(key)
            # An un-driven input contact is permanently zero. Reserve its
            # fixture instead of routing a board-wide inactive constant bus.
            if net!='constant:0' and net not in direct_inputs: targets[net].append((entry['fixture'],entry['contact']))
    for name,desc in placed.items():
        for port,entries in desc['inputs'].items():
            if any((name,tuple(e['contact'])) not in driven for e in entries):
                raise MapError('Unconnected input: '+name+'.'+port)
    exports={row['name']:[dict(index=i,net=net) for i,(net,_) in enumerate(source(row['from']))] for row in project.outputs}
    aliases={}; claimed=set()
    for name,entries in exports.items():
        if all(e['net'] in source_entries and not targets[e['net']] and e['net'] not in claimed for e in entries):
            aliases[name]=[dict(source_entries[e['net']],index=e['index']) for e in entries]
            claimed.update(e['net'] for e in entries)
    output_ports=fit_ports({name:entries for name,entries in exports.items() if name not in aliases},
        {net:[root] for net,root in roots.items()},frame,used,output=True)
    for name,entries in output_ports.items():
        for bit,entry in enumerate(entries):
            p=tuple(entry['contact']);fixture=tuple(entry['fixture'])
            cells[p]=Cell(1,entry['rotation']);pin=(2*p[0]-fixture[0],2*p[1]-fixture[1])
            targets[exports[name][bit]['net']].append((pin,p));reserved.add(fixture)
    output_ports.update(aliases)
    # An output indicator emits beyond its fixture. Keep that destination
    # empty so adding production I/O cannot feed an unrelated routed net.
    for entries in output_ports.values():
        for entry in entries:
            fixture=tuple(entry['fixture'])
            guard=next(destinations(fixture,Cell(1,entry['rotation'])))
            if guard in cells:
                raise MapError(f'Output indicator has no free emission space: {fixture}')
            reserved.add(guard)
    if len(cells)>max_cells: raise MapError('Scheme exceeds --max-cells')
    router=FixedWiring(cells,reserved);router.max_cells=max_cells
    router.routing_order=routing_order
    router.deadline=time.monotonic()+max(15,min(240,len(cells)/400))
    for net,sinks in targets.items():
        if sinks: router.connection(net,roots[net],sinks)
    cells=router.route_all() if any(targets.values()) else cells
    for name,part in originals.items():
        if any(cells.get(p)!=c for p,c in part.items()): raise MapError('Compiled scheme was modified: '+name)
    meta=dict(schema=1,top=project.top,layout='compiled-module-assembly-v1',inputs=inputs,outputs=output_ports,
        profile='GraphDLC-01232bd',verified_against_current_game=False,
        cells=len(cells),bounds=bounds_of(cells),map_hash=map_hash(cells),gate_labels=labels,
        settle_ticks=propagation_bound(cells,memories,margin=2),
        timing=dict(model='game-ticks',state_boundaries=memories),
        compiled_modules=cache_records,instances={name:dict(inputs=desc['inputs'],outputs=desc['outputs'],
            map_hash=map_hash(originals[name]),cells=len(originals[name]),panel=desc.get('panel')) for name,desc in placed.items()},
        components={row['name']:dict(inputs=placed[row['name']]['inputs'],outputs=placed[row['name']]['outputs'],
                    interface=placed[row['name']].get('interface',{}),display=placed[row['name']].get('display'),
                    source_map_hash=placed[row['name']]['source_map_hash']) for row in project.components},
        optimization=dict(mode='compact' if compact else 'default',templates=False,
            directly_exposed_inputs=len(direct_inputs),directly_exposed_outputs=sum(len(es) for es in aliases.values()),
            compiled_cells_immutable=True,unique_modules=len(cache_records),instances=len(project.modules)),
        project_graph=dict(modules=list(project.modules),components=list(project.components),
            inputs=list(project.inputs),outputs=list(project.outputs),connections=list(project.connections)),
        project_sha256=hashlib.sha256(project.path.read_bytes()).hexdigest(),
        sources=[dict(name=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in project.sources])
    Path(out).mkdir(parents=True,exist_ok=True)
    write_json(Path(out)/f'{project.top}.layout.json',meta['project_graph'])
    write_json(Path(out)/f'{project.top}.logic.json',dict(format='arrowshdl-module-graph',version=2,
        **meta['project_graph'],compiled_modules=cache_records))
    return cells,meta
