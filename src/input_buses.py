"""Explicit input grouping; gap counts empty cells, not coordinate distance."""
from arrowasm import MapError


def configure(graph, groups, gap):
    if gap != 'auto' and (type(gap) is not int or gap < 0):
        raise MapError('Промежуток шины: auto или целое число >= 0')
    normalized, used = [], set()
    for group in groups or []:
        names = group.split(',') if isinstance(group, str) else list(group)
        names = [name.strip() for name in names]
        if not names or any(not name for name in names):
            raise MapError('Пустая группа входов')
        for name in names:
            if name not in graph['inputs']:
                raise MapError(f'Неизвестный вход шины: {name}')
            if name in used:
                raise MapError(f'Вход указан в нескольких шинах: {name}')
            used.add(name)
        normalized.append(names)
    return {'groups': normalized, 'gap': gap}


def apply_contacts(graph, contacts, core_points=None):
    result = dict(contacts)
    config = graph.get('_input_bus_config', {'groups': [], 'gap': 0})
    points = list(core_points or [(c[0], c[1]) for c in contacts.values()])
    min_x, max_x = min(p[0] for p in points), max(p[0] for p in points)
    min_y, max_y = min(p[1] for p in points), max(p[1] for p in points)
    margin = graph.get('_port_margin',3)
    left = min_x - margin
    grouped = {e['net'] for names in config['groups'] for name in names for e in graph['inputs'][name]}
    used, cursor = set(), 0
    for group_index, names in enumerate(config['groups']):
        nets = [e['net'] for name in names for e in graph['inputs'][name]]
        gap = config['gap']
        if gap == 'auto':
            gap = graph.get('_bus_gaps',[graph.get('_bus_gap',0)]*len(config['groups']))[group_index]
        side = graph.get('_bus_sides',['left']*len(config['groups']))[group_index]
        length = (len(nets)-1)*(gap+1)
        start = cursor
        if graph.get('_bus_align') == 'center':
            start = ((min_y+max_y if side=='left' else min_x+max_x)-length)//2
        for i, net in enumerate(nets):
            along=start+i*(gap+1)
            if side=='top':
                x,y=along,min_y-margin
                fixture,rotation=(x,y-1),2
            elif side=='bottom':
                x,y=along,max_y+margin
                fixture,rotation=(x,y+1),0
            else:
                x,y=left,along
                fixture,rotation=(x-1,y),1
            if (x,y) in used:raise MapError('Шины пересекаются при выбранном размещении')
            result[net] = (x,y,fixture,rotation)
            used.add((x, y))
        cursor += len(nets) * (gap + 1) + 2
    for net, (x, y, fixture, rotation) in contacts.items():
        if net in grouped:
            continue
        if rotation == 0:
            y = max_y + 3
            while (x, y) in used: x += 1
            fixture = (x, y + 1)
        elif rotation == 2:
            y = min_y - 3
            while (x, y) in used: x += 1
            fixture = (x, y - 1)
        elif rotation == 3:
            x = max_x + 3
            while (x, y) in used: y += 1
            fixture = (x + 1, y)
        else:
            x = left
            y = max(min_y,min(y,max_y))
            while (x, y) in used: y += 1
            fixture = (x - 1, y)
        result[net] = (x, y, fixture, rotation)
        used.add((x, y))
    return result


def apply_placement(graph, placement):
    if graph.get('_adapt_bus'):
        return adapt_grouped_placement(graph,placement)
    # The general placer has already fixed the default port banks. Applying
    # their coordinates relative to each candidate core would move I/O during
    # local growth and consume the distribution corridor reserved for it.
    if not graph.get('_input_bus_config',{}).get('groups'):
        if graph.get('_adaptive_ports'):
            return adaptive_placement(graph,placement)
        return placement
    vertices, positions, sources = placement
    contacts = {v['net']: (*p, tuple(v['fixture']), v.get('rotation', 1))
                for v, p in zip(vertices, positions) if v['kind'] == 'input'}
    output_nets={e['net'] for es in graph['outputs'].values() for e in es}
    core_points = [p for v, p in zip(vertices, positions)
                   if v['kind'] != 'input' and v.get('node',{}).get('output') not in output_nets]
    if not core_points:core_points=[p for v,p in zip(vertices,positions) if v['kind']=='input'] or [(0,0)]
    contacts = apply_contacts(graph, contacts, core_points)
    for i, vertex in enumerate(vertices):
        if vertex['kind'] != 'input':
            continue
        x, y, fixture, rotation = contacts[vertex['net']]
        vertices[i] = dict(vertex, fixture=fixture, rotation=rotation)
        positions[i] = (x, y)
    return vertices, positions, sources


def adapt_grouped_placement(graph,placement):
    """Align external buses after gate packing, fitting individual bit pitches."""
    vertices,positions,sources=placement
    terminals={e['net'] for es in graph['outputs'].values() for e in es}
    consumers={e['net']:[] for es in graph['inputs'].values() for e in es};points=[]
    for v,p in zip(vertices,positions):
        if v['kind']=='input' or v.get('node',{}).get('output') in terminals:continue
        points.append(p);points.extend(tuple(q) for q in v.get('pins',[]))
        for net,pin in zip(v.get('node',{}).get('inputs',[]),v.get('pins',[p]*3)):
            if net in consumers:consumers[net].append(tuple(pin))
    if not points:return placement
    lo_x,lo_y=min(p[0] for p in points),min(p[1] for p in points)
    hi_x,hi_y=max(p[0] for p in points),max(p[1] for p in points)
    margin=graph.get('_port_margin',0);used=set();contacts={}
    config=graph.get('_input_bus_config',{'groups':[],'gap':'auto'})
    grouped={name for names in config['groups'] for name in names}
    groups=[[e['net'] for name in names for e in graph['inputs'][name]] for names in config['groups']]
    groups.extend([[e['net']] for name,es in graph['inputs'].items() if name not in grouped for e in es])
    for j,nets in enumerate(groups):
        requested=graph.get('_bus_sides',[])
        sides=[requested[j]] if j<len(requested) else ['left','top','bottom','right']
        best=None
        for side in sides:
            axis=1 if side in ('left','right') else 0
            preferred=[sorted(p[axis] for p in consumers[net])[len(consumers[net])//2] if consumers[net] else (lo_y if axis else lo_x) for net in nets]
            gap=config['gap'];step=1 if gap=='auto' else gap+1
            if gap=='auto':preferred=[v+graph.get('_contact_offsets',{}).get(net,0) for net,v in zip(nets,preferred)]
            start=sorted(v-i*step for i,v in enumerate(preferred))[len(nets)//2]
            trial={};previous=None;cost=0
            for i,net in enumerate(nets):
                along=preferred[i] if gap=='auto' else start+i*step
                if previous is not None:along=max(along,previous+step)
                def point(a):return (lo_x-margin,a) if side=='left' else (hi_x+margin,a) if side=='right' else (a,lo_y-margin) if side=='top' else (a,hi_y+margin)
                if gap=='auto':
                    while point(along) in used:along+=1
                if point(along) in used:trial={};break
                p=point(along);rotation={'left':1,'top':2,'bottom':0,'right':3}[side]
                dx,dy={'left':(-1,0),'top':(0,-1),'bottom':(0,1),'right':(1,0)}[side]
                trial[net]=(*p,(p[0]+dx,p[1]+dy),rotation)
                cost+=sum(abs(p[0]-q[0])+abs(p[1]-q[1]) for q in consumers[net]);previous=along
            if trial and (best is None or cost<best[0]):best=cost,trial
        if best is None:raise MapError('Нет свободной внешней стороны для шины')
        contacts.update(best[1]);used.update((v[0],v[1]) for v in best[1].values())
    for i,v in enumerate(vertices):
        if v['kind']!='input':continue
        x,y,fixture,rotation=contacts[v['net']]
        positions[i]=(x,y);vertices[i]=dict(v,fixture=fixture,rotation=rotation)
    return vertices,positions,sources


def adaptive_placement(graph,placement):
    """Place ungrouped contacts near their physical consumers on any face."""
    vertices,positions,sources=placement
    terminals={e['net'] for es in graph['outputs'].values() for e in es}
    consumers={e['net']:[] for es in graph['inputs'].values() for e in es}
    core=[]
    for v,p in zip(vertices,positions):
        if v['kind']=='input' or v.get('node',{}).get('output') in terminals:continue
        core.append(p)
        for net,pin in zip(v.get('node',{}).get('inputs',[]),v.get('pins',[p]*3)):
            if net in consumers:consumers[net].append(tuple(pin))
    if not core:return placement
    lo_x,lo_y=min(p[0] for p in core),min(p[1] for p in core)
    hi_x,hi_y=max(p[0] for p in core),max(p[1] for p in core)
    margin=graph.get('_port_margin',1);occupied={}
    # Ordered vector banks can occupy different faces, without forcing all
    # ports into one distribution corridor. Explicit bus flags use their own
    # constraints in apply_contacts instead of this free-port search.
    for i,v in sorted(enumerate(vertices),key=lambda iv:iv[1].get('net','')):
        if v['kind']!='input':continue
        targets=consumers[v['net']] or core
        best=None
        for side,rotation in (('left',1),('top',2),('bottom',0),('right',3)):
            horizontal=side in ('top','bottom')
            alongs=sorted({max(lo_x,min(t[0],hi_x)) if horizontal else max(lo_y,min(t[1],hi_y)) for t in targets})
            for along in alongs:
                p=(along,lo_y-margin) if side=='top' else (along,hi_y+margin) if side=='bottom' else (lo_x-margin,along) if side=='left' else (hi_x+margin,along)
                if p in occupied:continue
                cost=sum(abs(p[0]-t[0])+abs(p[1]-t[1]) for t in targets)
                candidate=(cost,side,p,rotation)
                if best is None or candidate<best:best=candidate
        if best is None:raise MapError('Нет свободного внешнего контакта для входа')
        _,side,p,rotation=best
        dx,dy={1:(-1,0),2:(0,-1),0:(0,1),3:(1,0)}[rotation]
        fixture=(p[0]+dx,p[1]+dy)
        occupied[p]=v['net'];positions[i]=p
        vertices[i]=dict(v,fixture=fixture,rotation=rotation)
    return vertices,positions,sources


def describe(graph, meta):
    config = graph.get('_input_bus_config', {'groups': [], 'gap': 0})
    meta['input_buses']=[]
    for names in config['groups']:
        entries=[e for name in names for e in meta['inputs'][name]]
        points=[e['fixture'] for e in entries]
        pitches=[sum(abs(a-b) for a,b in zip(p,q)) for p,q in zip(points,points[1:])]
        pitch=pitches[0] if pitches and len(set(pitches))==1 else (1 if not pitches else None)
        meta['input_buses'].append({'ports':names,'gap':pitch-1 if pitch is not None else None,'pitch':pitch,
                                   'pitches':pitches,'gaps':[p-1 for p in pitches],
                                   'requested_gap':config['gap'], 'rotation':entries[0]['rotation'],
                                   'fixtures':points})


def verify_exterior(cells, meta):
    """Independent check of final serialized coordinates, including all backends."""
    for kind in ('inputs','outputs'):
        for name, entries in meta[kind].items():
            for entry in entries:
                x,y=entry['contact']; fx,fy=entry['fixture']
                outside=lambda p: p[0]<=fx if fx<x else p[0]>=fx if fx>x else p[1]<=fy if fy<y else p[1]>=fy
                invalid=next((p for p in cells if outside(p)),None)
                if invalid is not None:
                    raise MapError(f'Трасса {invalid} находится за внешним портом {name}[{entry["index"]}] {entry["fixture"]}')
    meta['io_boundary_verified']=True
