"""Pack connected gate chains and shared-input pairs inside HDL module blocks.

Local growth changes spacing between units, never the direct links inside a
chain or the shared pins of a native pair. Port banks are fixed for the search.
"""
from collections import defaultdict
from itertools import product
import math
import re

from arrowasm import MapError


def group_of(node):
    return node.get('scope','core').split('.')[0]


def units_of(graph):
    output_nets={entry['net'] for entries in graph['outputs'].values() for entry in entries}
    nodes=[node for node in graph['nodes'] if node['output'] not in output_nets]
    by_net={node['output']:node for node in nodes}
    consumers=defaultdict(list)
    depth={net:0 for net in ('const0','const1')}
    depth.update({entry['net']:0 for entries in graph['inputs'].values() for entry in entries})
    for node in graph['nodes']:
        depth[node['output']]=1+max(depth[net] for net in node['inputs'])
        for net in node['inputs']:consumers[net].append(node)
    paired=set();units=[]
    buckets=defaultdict(dict)
    for node in nodes:
        if node['op'] in ('XOR','AND','MAJ'):
            buckets[group_of(node),tuple(sorted(node['inputs']))][node['op']]=node
    for (group,arguments),ops in sorted(buckets.items()):
        threshold='MAJ' if len(arguments)==3 else 'AND'
        if 'XOR' in ops and threshold in ops and len(set(arguments))==len(arguments):
            pair=[ops['XOR'],ops[threshold]]
            arguments=list(arguments)
            if len(arguments)==3:
                carry=[net for net in arguments if by_net.get(net,{}).get('op')=='MAJ']
                if carry:
                    cin=carry[0];arguments=[net for net in arguments if net!=cin]+[cin]
            units.append({'group':group,'kind':'shared_pair','nodes':[dict(node,inputs=arguments) for node in pair]})
            paired.update(node['id'] for node in pair)
    remaining={node['id']:node for node in nodes if node['id'] not in paired}
    predecessor,successor={},{}
    for node in nodes:
        if node['id'] not in remaining:continue
        choices=[by_net[net] for net in node['inputs'] if net in by_net and by_net[net]['id'] in remaining
                 and len(consumers[net])==1 and group_of(by_net[net])==group_of(node)]
        if choices:
            parent=max(choices,key=lambda n:(depth[n['output']],n['id']))
            predecessor[node['id']]=parent['id'];successor[parent['id']]=node['id']
    used=set()
    for node in nodes:
        if node['id'] not in remaining or node['id'] in predecessor:continue
        chain=[];current=node['id']
        while current in remaining and current not in used:
            chain.append(remaining[current]);used.add(current)
            if len(chain)==8:
                units.append({'group':group_of(node),'kind':'chain','nodes':chain});chain=[]
            current=successor.get(current)
        if chain:units.append({'group':group_of(node),'kind':'chain','nodes':chain})
    for node in nodes:
        if node['id'] not in used and node['id'] not in paired:
            units.append({'group':group_of(node),'kind':'chain','nodes':[node]})
    constants=[net for net in ('const0','const1') if any(net in node['inputs'] for node in graph['nodes'])]
    for net in constants:units.append({'group':'constants','kind':'constant','net':net,'nodes':[]})
    unit_for={node['output']:i for i,unit in enumerate(units) for node in unit['nodes']}
    unit_for.update({unit['net']:i for i,unit in enumerate(units) if unit['kind']=='constant'})
    for i,unit in enumerate(units):
        produced={node['output'] for node in unit['nodes']}
        unit['inputs']=sorted({net for node in unit['nodes'] for net in node['inputs'] if net not in produced})
        unit['parents']={unit_for[net] for net in unit['inputs'] if net in unit_for and unit_for[net]!=i}
    ordered=[];visiting=set();visited=set()
    def visit(i):
        if i in visited:return
        if i in visiting:raise MapError('Цикл в графе упаковки операторов')
        visiting.add(i)
        for parent in sorted(units[i]['parents']):visit(parent)
        visiting.remove(i);visited.add(i);ordered.append(i)
    terminal_by_net={node['output']:node for node in graph['nodes']}
    for entries in graph['outputs'].values():
        for entry in entries:
            terminal=terminal_by_net[entry['net']]
            for net in terminal['inputs']:
                if net in unit_for:visit(unit_for[net])
    for i in range(len(units)):visit(i)
    return [units[i] for i in ordered]


def shape(unit):
    """Cells occupied by a unit, including exact pin names and direct links."""
    points={};vertices=[]
    def wire(at,net,targets=()):
        old=points.get(at)
        points[at]=('wire',net,set(targets)|(old[2] if old and old[0]=='wire' else set()))
    if unit['kind']=='constant':
        points[(0,0)]=('gate','constant:'+unit['net'],set())
        points[(1,0)]=('wire',unit['net'],set())
        if unit['net']=='const1':
            for p in ((-1,0),(0,-1),(0,1)):points[p]=('clear',unit['net'],set())
        vertices=[({'kind':'constant','net':unit['net']},(0,0))]
    elif unit['kind']=='shared_pair':
        arguments=unit['nodes'][0]['inputs']
        pins=[(0,-1),(0,2)]+([(-1,1)] if len(arguments)==3 else [])
        for y,node in enumerate(unit['nodes']):
            at=(0,y);points[at]=('gate',node['id'],set())
            wire((1,y),node['output'])
            for net,pin in zip(arguments,pins):wire(pin,net,[at])
            vertices.append(({'kind':'gate','node':node,'pins':pins},at))
    else:
        chain=unit['nodes']
        for i,original in enumerate(chain):
            arguments=list(original['inputs'])
            previous=chain[i-1]['output'] if i else None
            if previous in arguments:
                arguments.remove(previous);arguments.insert(0,previous)
                pins=[(i-1,0)]+([(i,-1)] if len(arguments)>1 else [])+([(i,1)] if len(arguments)>2 else [])
            elif len(arguments)==1:pins=[(i-1,0)]
            elif len(arguments)==2:pins=[(i,-1),(i,1)]
            else:pins=[(i-1,0),(i,-1),(i,1)]
            node=dict(original,inputs=arguments);at=(i,0)
            points[at]=('gate',node['id'],set())
            for net,pin in zip(arguments,pins):
                if previous!=net:wire(pin,net,[at])
            if i==len(chain)-1:wire((i+1,0),node['output'])
            vertices.append(({'kind':'gate','node':node,'pins':pins},at))
    return points,vertices


def pack_group(units,gap=0,aspect=1.0,fanout=None):
    from compact_layout import wire_cell
    shaped=[(unit,*shape(unit)) for unit in units]
    area=sum(len(points) for _,points,_ in shaped)
    widest=max(max(x for x,y in points)-min(x for x,y in points)+1 for _,points,_ in shaped)
    tallest=max(max(y for x,y in points)-min(y for x,y in points)+1 for _,points,_ in shaped)
    width=max(widest+2,math.ceil(math.sqrt(max(area,1))*aspect*1.15)+gap*math.ceil(math.sqrt(len(units))))
    height=max(tallest+2,math.ceil(area*1.4/width)+gap*math.ceil(math.sqrt(len(units))))
    for growth in range(24):
        occupied,placed,boxes,roots={},[],[],{}
        root_at={}
        for unit,points,vertices in shaped:
            minx,miny=min(x for x,y in points),min(y for x,y in points)
            maxx,maxy=max(x for x,y in points),max(y for x,y in points)
            best=None
            for y in range(-miny,height-maxy):
                for x in range(-minx,width-maxx):
                    box=(x+minx,y+miny,x+maxx,y+maxy)
                    if gap and any(not(box[2]+gap<b[0] or b[2]+gap<box[0] or box[3]+gap<b[1] or b[3]+gap<box[1]) for b in boxes):continue
                    shifted={(x+px,y+py):(kind,net,{(x+tx,y+ty) for tx,ty in targets}) for (px,py),(kind,net,targets) in points.items()}
                    shared=0;valid=True
                    for p,(kind,net,targets) in shifted.items():
                        if p not in occupied:continue
                        other=occupied[p]
                        if kind!='wire' or other[0]!='wire' or net!=other[1] or wire_cell(p,targets|other[2]) is None:
                            valid=False;break
                        shared+=1
                    if not valid:continue
                    for p,entry in list(shifted.items()):
                        if p in occupied:shifted[p]=(entry[0],entry[1],entry[2]|occupied[p][2])
                    moves=((1,0),(-1,0),(0,1),(0,-1),(2,0),(-2,0),(0,2),(0,-2),(1,1),(1,-1),(-1,1),(-1,-1))
                    check_roots={root_at[q] for p in shifted for q in ((p[0]+dx,p[1]+dy) for dx,dy in moves) if q in root_at}
                    prospective=dict(roots)
                    for vertex,(gx,gy) in vertices:
                        net=vertex.get('net',vertex.get('node',{}).get('output'))
                        prospective[net]=(x+gx+1,y+gy);check_roots.add(net)
                    for net in check_roots:
                        root=prospective[net];entry=shifted.get(root,occupied.get(root))
                        if not entry or entry[:2]!=('wire',net):continue
                        if fanout and fanout.get(net,0)<=len(entry[2]):continue
                        accessible=any(q not in shifted and q not in occupied and wire_cell(root,entry[2]|{q}) is not None
                                       for q in ((root[0]+dx,root[1]+dy) for dx,dy in moves))
                        if not accessible:
                            valid=False;break
                    if not valid:continue
                    cost=0
                    for vertex,(gx,gy) in vertices:
                        if vertex['kind']!='gate':continue
                        for net,pin in zip(vertex['node']['inputs'],vertex['pins']):
                            if net in roots:
                                cost+=abs(x+pin[0]-roots[net][0])+abs(y+pin[1]-roots[net][1])
                    right=max([box[2]]+[b[2] for b in boxes]);bottom=max([box[3]]+[b[3] for b in boxes])
                    score=cost+0.035*(right+1)*(bottom+1)-2*shared
                    candidate=(score,y,x)
                    if best is None or candidate<best[0]:best=(candidate,shifted,box)
            if best is None:break
            (_,y,x),shifted,box=best;boxes.append(box)
            for p,entry in shifted.items():
                if p in occupied:entry=(entry[0],entry[1],entry[2]|occupied[p][2])
                occupied[p]=entry
            for vertex,(gx,gy) in vertices:
                value=dict(vertex)
                if 'pins' in value:value['pins']=[(x+px,y+py) for px,py in value['pins']]
                placed.append((value,(x+gx,y+gy)))
                if value['kind']=='gate':roots[value['node']['output']]=(x+gx+1,y+gy)
                else:roots[value['net']]=(x+gx+1,y+gy)
            root_at={p:net for net,p in roots.items()}
        else:
            return placed,max(x for x,y in occupied)+1,max(y for x,y in occupied)+1
        if width<=height*aspect:width+=2
        else:height+=2
    raise MapError('Не удалось упаковать связанные операторы в локальную область')


def arrange_packed(graph,expansion=None,corridor=3,aspect=1.0,frame=None,combine=False):
    expansion=expansion or {}
    units=units_of(graph)
    grouped=defaultdict(list)
    for unit in units:grouped[unit['group']].append(unit)
    if combine and units:grouped={'core':units}
    by_net={node['output']:group_of(node) for node in graph['nodes'] if not node['id'].startswith('port:')}
    for unit in units:
        if unit['kind']=='constant':by_net[unit['net']]='constants'
    parents={group:{by_net[net] for unit in us for net in unit['inputs'] if net in by_net and by_net[net]!=group} for group,us in grouped.items()}
    levels={};pending=set(grouped)
    while pending:
        ready=sorted(group for group in pending if parents[group]<=levels.keys())
        if not ready:
            # Shared logic can make the module-level graph cyclic while the
            # actual Boolean graph remains acyclic. Pack that graph as one bin.
            grouped={'core':units};parents={'core':set()};levels={'core':0};break
        for group in ready:levels[group]=max((levels[parent]+1 for parent in parents[group]),default=0)
        pending-=set(ready)
    fanout=defaultdict(int)
    for node in graph['nodes']:
        for net in node['inputs']:fanout[net]+=1
    layouts={group:pack_group(us,expansion.get(group,0),aspect,fanout) for group,us in grouped.items()}
    source_order={scope['name']:scope.get('instance_source','') for scope in graph.get('instances',[])}
    def order(group):
        number=re.search(r':(\d+)\.',source_order.get(group,''))
        return int(number.group(1)) if number else 10**9,group
    stage_width={level:max(layouts[group][1] for group in grouped if levels[group]==level) for level in set(levels.values())}
    # Leave an external distribution corridor inside the port boundary. Its
    # length does not enter the core objective; I/O must not force core detours.
    port_margin=4
    x_offsets={};cursor=port_margin
    for level in sorted(stage_width):x_offsets[level]=cursor;cursor+=stage_width[level]+corridor
    placements=[];blocks=[]
    core_bottom=port_margin
    for level in sorted(stage_width):
        y=port_margin
        for group in sorted((group for group in grouped if levels[group]==level),key=order):
            vertices,width,height=layouts[group];x=x_offsets[level]
            for vertex,(px,py) in vertices:
                value=dict(vertex)
                if 'pins' in value:value['pins']=[(x+ax,y+ay) for ax,ay in value['pins']]
                placements.append((value,(x+px,y+py)))
            blocks.append({'id':group,'at':[x,y],'width':width,'height':height,'expansion':expansion.get(group,0),
                           'units':len(grouped[group]),'operators':sum(len(unit['nodes']) for unit in grouped[group])})
            y+=height+corridor
        core_bottom=max(core_bottom,y-corridor)
    frame=frame or (max(64,cursor+32),max(64,core_bottom+32))
    if cursor>frame[0]-3 or core_bottom>frame[1]-3:raise MapError('Ядро вышло за фиксированную рамку портов')
    vertices=[];positions=[];sources={}
    offset=0
    for name,entries in sorted(graph['inputs'].items(),key=lambda item:(-len(item[1]),item[0])):
        for entry in entries:
            sources[entry['net']]=len(vertices)
            vertices.append({'kind':'input','net':entry['net'],'fixture':(-4,offset),'rotation':1})
            positions.append((-3,offset));offset+=2
        offset+=2
    for vertex,position in placements:
        sources[vertex.get('net',vertex.get('node',{}).get('output'))]=len(vertices)
        vertices.append(vertex);positions.append(position)
    output_nets={entry['net'] for entries in graph['outputs'].values() for entry in entries}
    terminals={node['output']:node for node in graph['nodes'] if node['output'] in output_nets}
    offset=0
    for name,entries in sorted(graph['outputs'].items(),key=lambda item:(-len(item[1]),item[0])):
        for entry in entries:
            sources[entry['net']]=len(vertices)
            vertices.append({'kind':'gate','node':terminals[entry['net']],'rotation':1})
            positions.append((frame[0]+3,offset));offset+=2
        offset+=2
    return (vertices,positions,sources),blocks
