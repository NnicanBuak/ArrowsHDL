"""Recognize mux trees and minimize complete physical maps, including I/O.

Matching uses connectivity only. Input distribution is outside the logic strip.
The unchanged synthesis graph remains the compiler's exported logic artifact.
"""
from arrowasm import Cell, MapError
from arrow_layout import bounds_of, depth_of, logic_core_metrics
from mapdata import map_hash
from output_layout import candidate_score, exterior_bounds


def grouped_contacts(graph, contacts, core_points):
    from input_buses import apply_contacts
    return apply_contacts(graph, contacts, core_points)


def recognize_mux(graph):
    primary = {e['net'] for es in graph['inputs'].values() for e in es}
    outputs = [e['net'] for es in graph['outputs'].values() for e in es]
    if len(outputs) != 1:
        return None
    by_net = {n['output']: n for n in graph['nodes']}
    terminal = by_net.get(outputs[0])
    if not terminal or terminal['op'] != 'BUF' or len(terminal['inputs']) != 1:
        return None
    claimed = {terminal['id']}

    def descend(net, visiting):
        if net in primary:
            return [net], []
        if net in visiting:
            return None
        node = by_net.get(net)
        if not node or node['op'] != 'OR' or len(node['inputs']) != 2:
            return None
        arms = [by_net.get(n) for n in node['inputs']]
        if any(not n or n['op'] != 'AND' or len(n['inputs']) != 2 for n in arms):
            return None
        for low, high in (arms, arms[::-1]):
            for inverse in low['inputs']:
                neg = by_net.get(inverse)
                if not neg or neg['op'] != 'NOT' or len(neg['inputs']) != 1:
                    continue
                sel = neg['inputs'][0]
                if sel not in primary or sel not in high['inputs']:
                    continue
                a = low['inputs'][1 - low['inputs'].index(inverse)]
                b = high['inputs'][1 - high['inputs'].index(sel)]
                left, right = descend(a, visiting | {net}), descend(b, visiting | {net})
                if not left or not right or left[1] != right[1] or len(left[0]) != len(right[0]):
                    continue
                claimed.update(n['id'] for n in (node, low, high, neg))
                return left[0] + right[0], left[1] + [sel]
        return None

    result = descend(terminal['inputs'][0], set())
    if not result:
        return None
    data, select = result
    if not select or len(set(data + select)) != len(data + select):
        return None
    if set(data + select) != primary or claimed != {n['id'] for n in graph['nodes']}:
        return None
    return data, select, terminal


def try_native_mux(graph, max_cells):
    if not graph.get('_physical_optimize'):return _try_native_mux(graph,max_cells)
    baseline=_try_native_mux(dict(graph,_physical_optimize=False),max_cells)
    if baseline is None:return None
    optimized=_try_native_mux(graph,max_cells)
    if optimized is None:return baseline
    old,old_meta=baseline;cells,meta=optimized
    from physical_compaction import no_size_regression
    if no_size_regression(optimized,baseline):return optimized
    old_meta['physical_compaction']={'selected':'original','removed_relays':0,'coordinate_cuts':0,
                                     'rejected':'optimized search increases cells or area',
                                     'exact_edges_verified':True,'bus_constraints_preserved':True}
    return baseline


def _try_native_mux(graph, max_cells):
    matched = recognize_mux(graph)
    if matched is None:
        return None
    count = len(matched[0])
    candidates, failures = [], []
    for compact_block in (True, False):
        for pitch in ((2, 3, 4, 5) if compact_block else (3, 4, 5, 6)):
            for leaf_pitch in (1, 2):
                for mirrored in (False, True):
                    try:
                        candidates.append(tree_candidate(graph, max_cells, pitch, mirrored,
                                                         compact_block=compact_block, leaf_pitch=leaf_pitch))
                    except MapError as error:
                        failures.append(str(error))
    for columns in sorted({2, min(4, count), count}):
        for snake in (False, True) if columns < count else (False,):
            for bank in ('fixed',):
                try:
                    cells, meta = mux_candidate(graph, max_cells, columns, snake, bank)
                    candidates.append((cells, meta))
                except MapError as error:
                    failures.append(str(error))
    if not candidates:
        raise MapError(failures[-1])
    best_tree = min((cm for cm in candidates if cm[1]['layout']=='compact-native-mux-tree-v2'),
                    key=candidate_score,default=None)
    if best_tree is not None:
        best=best_tree[1]
        for margin in (4,5,6,8):
            try:
                variant=dict(graph,_port_margin=margin)
                candidates.append(tree_candidate(variant,max_cells,best['block_pitch'],best['alternate_reflection'],
                                                 compact_block=best['compact_block'],leaf_pitch=best['leaf_pitch']))
            except MapError as error:
                failures.append(str(error))
        config=graph.get('_input_bus_config',{})
        if config.get('groups') and config.get('gap')=='auto':
            from itertools import product
            groups=config['groups']
            gaps=[(gap,)*len(groups) for gap in (0,1,2,3)]
            if len(groups)==2:gaps.extend(((0,1),(1,0),(1,2),(2,1)))
            sides=list(product(('left','top','bottom'),repeat=len(groups))) if len(groups)<=2 else [('left',)*len(groups)]
            best=min(candidates,key=candidate_score)[1]
            if best['layout']!='compact-native-mux-tree-v2':best=best_tree[1]
            for spacing in gaps:
                for placement in sides:
                    for align in ('start','center'):
                        try:
                            variant=dict(graph,_bus_gaps=spacing,_bus_sides=placement,_bus_align=align,
                                         _port_margin=best.get('port_margin',3))
                            candidates.append(tree_candidate(variant,max_cells,best['block_pitch'],best['alternate_reflection'],
                                                             compact_block=best['compact_block'],leaf_pitch=best['leaf_pitch']))
                        except MapError as error:
                            failures.append(str(error))
    cells, meta = min(candidates, key=candidate_score)
    meta['full_bounds']=exterior_bounds(cells,meta['inputs'],meta['outputs'])
    meta['optimization'] = {'objective': 'min_core_then_cells_full_area_and_ticks',
                            'fixed_input_bus': bool(graph.get('_input_bus_config')),
                            'io_in_objective': True,
                            'automatic_input_buses': graph.get('_input_bus_config',{}).get('gap')=='auto',
                            'candidates': [{'cells': len(c), 'ticks': m['settle_ticks'],
                                            'bounds': m['bounds'],
                                            'full_bounds':exterior_bounds(c,m['inputs'],m['outputs']), 'layout': m['layout'],
                                            'core':m['logic_core'],
                                            'term_columns': m.get('term_columns'),
                                            'block_pitch': m.get('block_pitch'),
                                            'compact_block': m.get('compact_block'),
                                            'leaf_pitch': m.get('leaf_pitch'),
                                            'port_margin': m.get('port_margin',3),
                                            'bus_settings':m.get('bus_settings'),
                                            'alternate_reflection': m.get('alternate_reflection', False),
                                            'snake_rows': m.get('snake_rows', False), 'select_bank': m['select_bank']}
                                           for c, m in candidates]}
    return cells, meta


def tree_candidate(graph, max_cells, pitch, mirrored, compact_block=False, leaf_pitch=2):
    """Orient Shannon mux blocks towards the following stage and nearby ports."""
    from compact_layout import Router
    data, select, terminal = recognize_mux(graph)
    nodes, vertices, positions, contacts, blocks = [], [], [], {}, []

    def gate(op, args, point, pins, rotation=1, output=None):
        net = output or f'tree:{len(nodes)}'
        n = {'id': f'mux-tree:{len(nodes)}', 'op': op, 'inputs': args, 'output': net}
        nodes.append(n)
        vertices.append({'kind': 'gate', 'node': n, 'rotation': rotation, 'pins': pins})
        positions.append(point)
        return net

    stage = [(net, i * leaf_pitch) for i, net in enumerate(data)]
    for level, sel in enumerate(select):
        following = []
        for i in range(0, len(stage), 2):
            a, ya = stage[i]
            b, yb = stage[i + 1]
            x, y = level * pitch, (ya + yb) // 2
            blocks.append({'id':f'mux{level}:{i//2}','at':[x,y],
                           'width':3 if compact_block else 4,'height':2,'operators':4})
            flip = mirrored and (i // 2) % 2
            def p(dx, dy):
                return x + dx, y + (1 - dy if flip else dy)
            if level == 0:
                contacts[a] = (*p(1, -1), p(1, -2), 0 if flip else 2)
                contacts[b] = (*p(1, 2), p(1, 3), 2 if flip else 0)
            neg = gate('NOT', [sel], p(0, 0), [p(-1, 0)])
            low = gate('AND', [a, neg], p(1, 0), [p(1, -1), p(0, 0)])
            high = gate('AND', [b, sel], p(1, 1), [p(1, 2), p(0, 1)])
            if compact_block:
                # High AND connects directly to OR. Only the low arm needs
                # one turning wire: five core cells inside a 3x2 block.
                out = gate('OR', [low, high], p(2, 1), [p(2, 0), p(1, 1)])
                output_y = p(2, 1)[1]
            else:
                out = gate('OR', [low, high], p(3, 0), [p(2, 0), p(2, 1)])
                output_y = p(3, 0)[1]
            following.append((out, output_y))
        stage = following
    last_x, last_y = positions[-1]
    gate('BUF', [stage[0][0]], (last_x + 1, last_y), [(last_x, last_y)], output=terminal['output'])
    for i, sel in enumerate(select):
        sx, sy = i * pitch - 1, -3
        contacts[sel] = (sx, sy, (sx, sy - 1), 2)
    contacts = grouped_contacts(graph, contacts, positions[:-1])
    # Horizontal buses may extend beyond the core's last column. Keep the
    # output on the perimeter as well, routing its terminal tail afterwards.
    border=max(p[0] for p in contacts.values())
    if border>=positions[-1][0]:
        ox,oy=positions[-1]
        positions[-1]=(border+2,oy)
        vertices[-1]['pins']=[(border+1,oy)]
    for net, (cx, cy, fixture, rot) in contacts.items():
        vertices.append({'kind': 'input', 'net': net, 'fixture': fixture, 'rotation': rot})
        positions.append((cx, cy))
    technology = dict(graph, nodes=nodes)
    from output_layout import route_with_outputs
    cells,router = route_with_outputs(technology,(vertices,positions,{}),max_cells)
    from physical_compaction import rebase_blocks
    blocks=rebase_blocks(blocks,getattr(router,'physical_compaction',None))
    meta = {'schema': 1, 'top': graph['top'], 'map_hash': map_hash(cells),
            'profile': 'GraphDLC-01232bd', 'verified_against_current_game': False,
            'inputs': router.inputs, 'outputs': router.outputs,
            'routing_limits': router.routing_limits,
            'physical_compaction':getattr(router,'physical_compaction',None),
            'output_search':router.output_search,
            'settle_ticks': depth_of(cells) + 2, 'cells': len(cells),
            'bounds': bounds_of(cells), 'layout': 'compact-native-mux-tree-v2',
            'port_layout': 'explicit-input-buses', 'mux_inputs': len(data),
            'mapped_logic_nodes': len(nodes), 'logic_core': logic_core_metrics(cells, router.gates, router.output_nets),
            'module_blocks':blocks,
            'block_pitch': pitch, 'alternate_reflection': mirrored, 'select_bank': 'fixed-left',
            'compact_block': compact_block, 'leaf_pitch': leaf_pitch,
            'port_margin': graph.get('_port_margin',3),
            'bus_settings':{'gaps':list(graph.get('_bus_gaps',[graph.get('_bus_gap',0)]*len(graph.get('_input_bus_config',{}).get('groups',[])))),
                            'sides':list(graph.get('_bus_sides',[])), 'align':graph.get('_bus_align','start')},
            'gate_labels': [{'at': list(p), 'op': n['op'], 'id': n['id']} for p, n in router.gates.items()]}
    from signal_metadata import describe_signals
    meta['signals']=describe_signals(technology,cells,router.owners,router.gates)
    return cells, meta


def mux_candidate(graph, max_cells, columns, snake, bank):
    matched = recognize_mux(graph)
    if matched is None:
        return None
    from compact_layout import Router
    data, select, terminal = matched
    nodes, vertices, positions, sources = [], [], [], {}
    contacts = {}

    def gate(op, args, x, y, rotation, pins, output=None):
        net = output or f'strip:{len(nodes)}'
        node = {'id': f'mux-strip:{len(nodes)}', 'op': op, 'inputs': args, 'output': net}
        nodes.append(node)
        sources[net] = len(vertices)
        vertices.append({'kind': 'gate', 'node': node, 'rotation': rotation, 'pins': pins})
        positions.append((x, y))
        return net

    x, accumulated, last_merge = 0, None, None
    blocks = []
    for index, net in enumerate(data):
        start_vertex = len(vertices)
        start_x = x
        term, previous = net, None
        for bit, control in enumerate(select):
            positive = (index >> bit) & 1
            if bit == 0:
                if positive:
                    contacts[net] = (x, 1, (x, 2), 0)
                    previous = (x, 1)
                    x += 1
                else:
                    contacts[net] = (x, 2, (x, 3), 0)
                    previous = (x, 2)
            if not positive:
                # NOR(~term, sel) = term & ~sel. All controls stay below
                # the strip; no inverse-control bus or upper-row inverter.
                term = gate('NOT', [term], x, 1, 1, [previous])
                previous = (x, 1)
                x += 1
            last = bit == len(select) - 1
            term = gate('AND' if positive else 'NOT', [term, control],
                        x, 1, 0 if last else 1, [previous, (x, 2)])
            previous = (x, 1)
            if not last:
                x += 1
        args, pins = [term], [(x, 1)]
        if accumulated is not None:
            args.append(accumulated)
            pins.append((x - 1, 0))
        accumulated = gate('OR', args, x, 0, 1, pins)
        last_merge = x
        x += 1
        blocks.append((start_vertex, len(vertices), start_x, x - start_x, net))
    gate('BUF', [accumulated], x, 0, 1, [(last_merge, 0)], terminal['output'])
    folded = columns < len(data)
    if folded:
        pitch = max(b[3] for b in blocks) + 2
        def transform(point, index):
            px, py = point
            row, col = divmod(index, columns)
            local_x = px - blocks[index][2]
            if snake and row % 2:
                col = columns - 1 - col
                return col * pitch + pitch - 3 - local_x, row * 6 + 1 - py
            return col * pitch + local_x, row * 6 + py
        for index, (begin, end, _, _, net) in enumerate(blocks):
            reverse = snake and (index // columns) % 2
            for vi in range(begin, end):
                positions[vi] = transform(positions[vi], index)
                vertices[vi]['pins'] = [transform(p, index) for p in vertices[vi]['pins']]
                if reverse:
                    vertices[vi]['rotation'] = (vertices[vi]['rotation'] + 2) % 4
            cx, cy, fixture, rotation = contacts[net]
            tx, ty = transform((cx, cy), index)
            contacts[net] = (tx, ty, transform(fixture, index), (rotation + (2 if reverse else 0)) % 4)
        positions[-1] = transform(positions[-1], len(data) - 1)
        vertices[-1]['pins'] = [transform(p, len(data) - 1) for p in vertices[-1]['pins']]
        if snake and ((len(data) - 1) // columns) % 2:
            vertices[-1]['rotation'] = (vertices[-1]['rotation'] + 2) % 4
    max_x = max(p[0] for p in positions)
    max_y = max(p[1] for p in positions)
    for i, control in enumerate(select):
        if bank == 'center':
            sx, sy = max_x // 2 + 2 * i, max_y + 5
            contacts[control] = (sx, sy, (sx, sy + 1), 0)
        else:
            contacts[control] = (-3, 4 + 2 * i, (-4, 4 + 2 * i), 1)
    contacts = grouped_contacts(graph, contacts, positions[:-1])
    for net, (cx, cy, fixture, rotation) in contacts.items():
        sources[net] = len(vertices)
        vertices.append({'kind': 'input', 'net': net, 'fixture': fixture, 'rotation': rotation})
        positions.append((cx, cy))
    technology = dict(graph, nodes=nodes)
    router = Router(technology, 1, max_cells, (vertices, positions, sources))
    # Keep routing of every inter-gate wire inside the two physical rows.
    if not folded:
        router.reserved.update((px, py) for px in range(-2, x + 2) for py in (-1, 2)
                               if (px, py) not in router.cells)
    external_reserved = set(router.reserved)
    _, lo_y, _, hi_y = router.bounds
    if not folded:
        router.reserved.update((px, py) for px in range(-2, x + 2)
                               for py in range(lo_y - 32, hi_y + 33) if py not in (0, 1)
                               and (px, py) not in router.cells)
    router.route_phase(router.core_sinks)
    router.reserved = external_reserved
    router.fixed_cells = set(router.cells)
    router.fixed_outs = {p: set(v) for p, v in router.outs.items()}
    # The already verified strip is immutable during external distribution.
    router.core_sinks = {}
    cells = router.route()
    from output_layout import route_with_outputs
    cells,router=route_with_outputs(technology,(vertices,positions,sources),max_cells,routed_seed=router)
    core = logic_core_metrics(cells, router.gates, router.output_nets)
    if not folded and core['bounds']['height'] != 2:
        raise MapError('Размещение мультиплексора вышло за две строки')
    meta = {'schema': 1, 'top': graph['top'], 'map_hash': map_hash(cells),
            'profile': 'GraphDLC-01232bd', 'verified_against_current_game': False,
            'inputs': router.inputs, 'outputs': router.outputs,
            'routing_limits': router.routing_limits,
            'physical_compaction':getattr(router,'physical_compaction',None),
            'settle_ticks': depth_of(cells) + 2, 'cells': len(cells),
            'bounds': bounds_of(cells), 'layout': 'compact-native-mux-oriented-v2',
            'port_layout': 'explicit-input-buses', 'logic_core': core,
            'output_search':router.output_search,
            'mux_inputs': len(data), 'mapped_logic_nodes': len(nodes),
            'term_columns': columns, 'snake_rows': snake, 'select_bank': bank,
            'gate_labels': [{'at': list(p), 'op': n['op'], 'id': n['id']} for p, n in router.gates.items()],
            'optimization': {'objective': 'two_row_mux_core', 'io_in_objective': False}}
    from signal_metadata import describe_signals
    meta['signals']=describe_signals(technology,cells,router.owners,router.gates)
    return cells, meta
