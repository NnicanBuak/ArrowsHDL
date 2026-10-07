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
    # The general placer has already fixed the default port banks. Applying
    # their coordinates relative to each candidate core would move I/O during
    # local growth and consume the distribution corridor reserved for it.
    if not graph.get('_input_bus_config',{}).get('groups'):
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
