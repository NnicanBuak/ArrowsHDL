"""Structural Verilog technology mapping with checked native electrical contacts."""
from collections import defaultdict
import re

from arrowshdl.arrowasm import Cell, MapError, validate_cell
from arrowshdl.arrow_layout import bounds_of, destinations
from arrowshdl.mapdata import map_hash


def parameter(value, default=0, signed=False):
    if value is None:
        return default
    if type(value) is int:
        return value
    if isinstance(value, str) and set(value) <= {"0", "1"}:
        result = int(value, 2)
        return result - (1 << len(value)) if signed and value[0] == '1' else result
    raise MapError(f"Nonconstant native gate parameter: {value}")


def normalize_physical(raw, top):
    module = raw['modules'][top]
    records = []
    for name, item in sorted(module.get('cells', {}).items()):
        kind = item['type']
        if kind == '$scopeinfo':
            continue
        declaration = raw['modules'].get(kind, {})
        native = kind == 'arrows_cell' or 'arrows_cell' in kind and kind.startswith('$paramod')
        if not native:
            raise MapError(f"{name}: structural map requires arrows_cell, received {kind}. Compile logical modules separately")
        params = dict(declaration.get('parameter_default_values', {}), **item.get('parameters', {}))
        def get(key, default=0):
            return parameter(params.get(key), default, signed=key in ('X', 'Y'))
        record = {'id': name, 'at': [get('X'), get('Y')], 'type': get('TYPE', 1),
                  'rotation': get('ROTATION'), 'mirrored': bool(get('MIRRORED')),
                  'connections': item['connections']}
        if get('MIRRORED') not in (0, 1):
            raise MapError(f"{name}: MIRRORED must be 0 or 1")
        records.append(record)
    if not records:
        raise MapError('Structural map is empty')
    return {'schema': 1, 'top': top, 'creator': raw.get('creator'), 'kind': 'physical',
            'ports': module.get('ports', {}), 'nodes': records}


def normalize_physical_hierarchy(raw, top, constraints=None):
    """Expand reusable RTLIL modules without flattening large boards in WASI.

    Origin attributes belong to module instances; electrical ports still come
    exclusively from HDL. No game-specific names, rules or save files are used.
    """
    modules, records = raw['modules'], []
    constraints=constraints or {}
    grids=[(row,re.compile(re.escape(row['instances']).replace(r'\[\*\]',r'\[(\d+)\]'))) for row in constraints.get('grids',())]
    placements={row['instance']:tuple(row['at']) for row in constraints.get('placements',())}
    next_net = 1
    assignments = {}
    local_minima = {}

    def placement_target(full):
        assigned = None
        for row, matcher in grids:
            match = matcher.fullmatch(full)
            if match:
                indices = list(map(int, match.groups()))
                if len(indices) != 2: raise MapError('Rectangular grid requires two [*] indices')
                base = row.get('origin', [0, 0])
                position = (base[0] + indices[1] * row['step'][0], base[1] + indices[0] * row['step'][1])
                if assigned is not None and assigned != position: raise MapError(f'Conflicting placement constraints for {full}')
                assigned = position
        if full in placements:
            if assigned is not None and assigned != placements[full]: raise MapError(f'Conflicting placement constraints for {full}')
            assigned = placements[full]
        return assigned

    def collect_assignments(kind, prefix, stack=()):
        if kind in stack:
            raise MapError(f'Recursive module instantiation: {kind}')
        for name, item in modules[kind].get('cells', {}).items():
            child_kind = item['type']
            if child_kind in ('$scopeinfo', '$buf') or child_kind == 'arrows_cell' or 'arrows_cell' in child_kind and child_kind.startswith('$paramod'):
                continue
            full = prefix + name
            if child_kind not in modules or modules[child_kind].get('attributes', {}).get('blackbox'):
                raise MapError(f'{full}: unknown native module {child_kind}')
            assigned = placement_target(full)
            if assigned is not None:
                assignments[full] = assigned
            collect_assignments(child_kind, full + '.', (*stack, kind))

    if grids or placements:
        collect_assignments(top, '')

    def local_minimum(kind, prefix, stack=()):
        if kind in stack:
            raise MapError(f'Recursive module instantiation: {kind}')
        # Absolute descendant constraints do not follow the parent's origin.
        descendants = frozenset(full[len(prefix):] for full in assignments if full.startswith(prefix))
        key = kind, descendants
        if key in local_minima:
            return local_minima[key]
        points = []
        for name, item in modules[kind].get('cells', {}).items():
            child_kind = item['type']
            if child_kind in ('$scopeinfo', '$buf'):
                continue
            full = prefix + name
            if full in assignments:
                continue
            if child_kind == 'arrows_cell' or 'arrows_cell' in child_kind and child_kind.startswith('$paramod'):
                params = dict(modules.get(child_kind, {}).get('parameter_default_values', {}), **item.get('parameters', {}))
                points.append(tuple(parameter(params.get(axis), signed=True) for axis in ('X', 'Y')))
            else:
                if child_kind not in modules or modules[child_kind].get('attributes', {}).get('blackbox'):
                    raise MapError(f'{name}: unknown native module {child_kind}')
                child_minimum = local_minimum(child_kind, full + '.', (*stack, kind))
                if child_minimum is not None:
                    attrs = item.get('attributes', {})
                    points.append(tuple(parameter(attrs.get('arrows_origin_' + axis), signed=True) + child_minimum[i]
                                        for i, axis in enumerate(('x', 'y'))))
        local_minima[key] = tuple(min(p[i] for p in points) for i in range(2)) if points else None
        return local_minima[key]

    def walk(kind, prefix, bindings, origin, stack):
        nonlocal next_net
        if kind in stack:
            raise MapError(f'Recursive module instantiation: {kind}')
        module, wires = modules[kind], dict(bindings)
        aliases = {}
        for item in module.get('cells', {}).values():
            if item['type'] == '$buf':
                connections = item['connections']
                if len(connections['A']) != len(connections['Y']):
                    raise MapError(f'{prefix}: invalid $buf width')
                aliases.update(zip(connections['Y'], connections['A']))
        for internal, external in bindings.items():
            visited = set()
            while internal in aliases:
                if internal in visited:
                    raise MapError(f'{prefix}: HDL alias cycle')
                visited.add(internal)
                internal = aliases[internal]
            if type(internal) is int:
                wires[internal] = external

        def wire(bit):
            nonlocal next_net
            visited = set()
            while bit in aliases:
                if bit in visited:
                    raise MapError(f'{prefix}: HDL alias cycle')
                visited.add(bit)
                bit = aliases[bit]
            if isinstance(bit, str):
                if bit not in ('0', '1'):
                    raise MapError(f'{prefix}: undefined bit {bit}')
                return bit
            if bit not in wires:
                wires[bit] = next_net
                next_net += 1
            return wires[bit]

        for name, item in sorted(module.get('cells', {}).items()):
            full = prefix + name
            connections = {port: [wire(v) for v in bits] for port,bits in item['connections'].items()}
            cell_kind = item['type']
            if cell_kind in ('$scopeinfo', '$buf'):
                continue
            if cell_kind == 'arrows_cell' or 'arrows_cell' in cell_kind and cell_kind.startswith('$paramod'):
                params = dict(modules.get(cell_kind, {}).get('parameter_default_values', {}), **item.get('parameters', {}))
                def get(key, default=0):
                    return parameter(params.get(key), default, signed=key in ('X', 'Y'))
                if get('MIRRORED') not in (0, 1):
                    raise MapError(f'{full}: MIRRORED must be 0 or 1')
                records.append(dict(id=full, at=[origin[0]+get('X'), origin[1]+get('Y')], type=get('TYPE', 1),
                                    rotation=get('ROTATION'), mirrored=bool(get('MIRRORED')), connections=connections,
                                    probe=item.get('attributes',{}).get('arrowshdl_probe')))
                continue
            if cell_kind not in modules or modules[cell_kind].get('attributes', {}).get('blackbox'):
                raise MapError(f'{full}: unknown native module {cell_kind}')
            child = modules[cell_kind]
            mapping = {}
            if set(connections) != set(child.get('ports', {})):
                raise MapError(f'{full}: incomplete module interface')
            for port, desc in child.get('ports', {}).items():
                if len(desc['bits']) != len(connections[port]):
                    raise MapError(f'{full}.{port}: incompatible port width')
                for internal, external in zip(desc['bits'], connections[port]):
                    if type(internal) is int:
                        mapping[internal] = external
            attrs = item.get('attributes', {})
            offset = tuple(parameter(attrs.get('arrows_origin_' + axis), signed=True) for axis in ('x', 'y'))
            child_origin=(origin[0]+offset[0],origin[1]+offset[1])
            assigned=assignments.get(full)
            if assigned is not None:
                # Placement anchors the bounds, including nested local offsets.
                minimum = local_minimum(cell_kind, full + '.') or (0, 0)
                child_origin = tuple(assigned[i] - minimum[i] for i in range(2))
            walk(cell_kind, full+'.', mapping, child_origin, (*stack, kind))
        return {name: dict(desc, bits=[wire(v) for v in desc['bits']]) for name,desc in module.get('ports', {}).items()}

    ports = walk(top, '', {}, (0, 0), ())
    graph=dict(schema=1, top=top, creator=raw.get('creator'), kind='physical', ports=ports, nodes=records)
    declared=modules[top].get('attributes',{}).get('arrowshdl_settle_ticks')
    if declared is not None:
        graph['settle_ticks']=parameter(declared)
        if graph['settle_ticks']<1: raise MapError('arrowshdl_settle_ticks must be positive')
    return graph


def dependencies(cells):
    """Separate normal, blocking and detector read dependencies."""
    incoming = {p: {'I': set(), 'B': set(), 'S': set()} for p in cells}
    for p, cell in cells.items():
        for q in destinations(p, cell):
            target = cells.get(q)
            if target is None or target.type == 25:
                continue
            if cell.type == 3:
                incoming[q]['B'].add(p)
            elif target.type not in (2, 5, 9, 21):
                incoming[q]['I'].add(p)
    for p, cell in cells.items():
        if cell.type == 5:
            front = next(destinations(p, cell))
            behind = (2*p[0] - front[0], 2*p[1] - front[1])
            if behind in cells:
                incoming[p]['S'].add(behind)
    return incoming


def _selector(pattern):
    return re.compile('^' + re.escape(pattern).replace(r'\[\*\]', r'\[(\d+)\]') + '$')


def place_physical(graph, *, max_cells=1000000, constraints=None):
    if len(graph['nodes']) > max_cells:
        raise MapError(f"Exceeded limit: {max_cells} cells")
    cells, sources, records = {}, {}, {}
    for node in graph['nodes']:
        at = tuple(node['at'])
        cell = Cell(node['type'], node['rotation'], node['mirrored'])
        validate_cell(*at, cell)
        if not 1 <= cell.type <= 25:
            raise MapError(f"{node['id']}: unknown physical type {cell.type}")
        if at in cells:
            raise MapError(f"{node['id']}: overlapping cells at {at}")
        connections = node['connections']
        if set(connections) != {'I', 'B', 'S', 'O'} or len(connections['O']) != 1:
            raise MapError(f"{node['id']}: invalid arrows_cell ports")
        net = connections['O'][0]
        if type(net) is not int or net in sources:
            raise MapError(f"{node['id']}: output must have a separate wire")
        sources[net] = at
        cells[at], records[at] = cell, node
    expected = dependencies(cells)
    external = {v for p in graph['ports'].values() if p['direction'] == 'input' for v in p['bits']}
    for at, node in records.items():
        for port in ('I', 'B', 'S'):
            nets = node['connections'][port]
            actual = set()
            for net in nets:
                if net == '0' or net in external and net not in sources:
                    continue
                if net not in sources:
                    raise MapError(f"{node['id']}.{port}: signal has no native driver: {net}")
                actual.add(sources[net])
            if actual != expected[at][port]:
                raise MapError(f"{node['id']}.{port}: HDL and geometry differ at {at}: HDL {sorted(actual)}, map {sorted(expected[at][port])}")
    _check_constraints(graph, constraints or {})
    ports = {direction: {} for direction in ('inputs', 'outputs')}
    for name, port in graph['ports'].items():
        if port['direction'] == 'output':
            ports['outputs'][name] = [dict(index=i, contact=list(sources[v])) for i,v in enumerate(port['bits']) if v in sources]
    manifest = dict(schema=1, top=graph['top'], layout='fixed-native-verilog', cells=len(cells),
                    logic_nodes=len(cells), map_hash=map_hash(cells), bounds=bounds_of(cells), **ports)
    if 'settle_ticks' in graph:
        manifest['settle_ticks']=graph['settle_ticks']
    manifest['probes']={((node['id'].rpartition('.')[0]+'.') if '.' in node['id'] else '')+node['probe']:node['at']
                        for node in graph['nodes'] if node.get('probe')}
    groups=defaultdict(dict)
    for node in graph['nodes']:
        if '.' in node['id']: groups[node['id'].rpartition('.')[0]][tuple(node['at'])]=cells[tuple(node['at'])]
    manifest['instances']={name:dict(bounds=bounds_of(part),cells=len(part),map_hash=map_hash(part)) for name,part in groups.items()}
    return cells, manifest


def _check_constraints(graph, constraints):
    groups = defaultdict(list)
    for node in graph['nodes']:
        # Every real module/generate boundary is available for grid selection.
        parts = node['id'].split('.')
        for end in range(1, len(parts)):
            groups['.'.join(parts[:end])].append(tuple(node['at']))
    for row in constraints.get('placements', []):
        points = groups.get(row['instance'])
        if not points:
            raise MapError(f"layout.placements: missing instance {row['instance']}")
        origin = [min(x for x,y in points), min(y for x,y in points)]
        if origin != row['at']:
            raise MapError(f"{row['instance']}: origin {origin}, expected {row['at']}. Update instance X/Y in HDL")
    for row in constraints.get('grids', []):
        matcher = _selector(row['instances'])
        matches = [(name, matcher.fullmatch(name), points) for name,points in groups.items() if matcher.fullmatch(name)]
        if not matches:
            raise MapError(f"layout.grids: no matching instances for {row['instances']}")
        origin = row.get('origin', [0, 0])
        for name, match, points in matches:
            indices = list(map(int, match.groups()))
            if len(indices) != 2:
                raise MapError('Rectangular grid requires two [*] indices: row and column')
            bounds = bounds_of(dict.fromkeys(points))
            expected = [origin[0]+indices[1]*row['step'][0], origin[1]+indices[0]*row['step'][1]]
            if bounds['min'] != expected:
                raise MapError(f"{name}: origin {bounds['min']}, expected {expected}")
            if 'max_cell_size' in row and (bounds['width'] > row['max_cell_size'][0] or bounds['height'] > row['max_cell_size'][1]):
                raise MapError(f"{name}: max_cell_size exceeded")
