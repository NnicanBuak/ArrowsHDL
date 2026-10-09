"""Improve completed routes and gate directions without moving fixed blocks.

Each trial frees one whole net, routes its real receivers again and validates
the complete map. Native fixtures, input contacts and stateful arrows stay fixed.
Only accepted trials replace the previous valid routing.
"""
from collections import deque
from copy import deepcopy

from arrowasm import Cell, MapError
from arrow_layout import destinations


def choose_source_variant(variants, receivers):
    """Choose a native source exit using all receivers and its physical overhead.

    Variants are (name, position, native_cell_count). One diagonal or jump arrow
    transports at most two Manhattan units. This is a placement estimate; the
    subsequent router checks occupied cells and actual signal connectivity.
    """
    receivers = list(receivers)
    scores = []
    for name, point, count in variants:
        steps = [(abs(point[0]-p[0])+abs(point[1]-p[1])+1)//2 for p in receivers]
        scores.append((count+sum(steps), max(steps, default=0), name))
    return min(scores)[2], [dict(name=name, cost=cost, longest=longest)
                           for cost, longest, name in scores]


_STATE = ('cells', 'owners', 'outs', 'roots', 'fixed_cells', 'fixed_outs', 'direct_nets')


def _snapshot(router):
    return {name: deepcopy(getattr(router, name)) for name in _STATE}


def _restore(router, state):
    for name, value in state.items():
        setattr(router, name, deepcopy(value))


def _distances(router, net):
    source = router.source_positions.get(net, router.roots[net])
    if source not in router.cells:
        source = router.roots[net]
    pending = deque([source]); distance = {source: 0}
    while pending:
        point = pending.popleft()
        for target in destinations(point, router.cells[point]):
            if target not in router.cells or target in distance:
                continue
            if point in destinations(target, router.cells[target]):
                continue
            if router.owners.get(target) != net:
                continue
            distance[target] = distance[point]+1; pending.append(target)
    if any(p not in distance for p in router.sinks[net]):
        raise MapError('Disconnected optimized net: '+net)
    return [distance[p] for p in set(router.sinks[net])]


def _score(router, net):
    distances = _distances(router, net)
    return len(router.cells), sum(distances), max(distances, default=0)


def _full_score(router):
    distances = [d for net in router.roots if router.sinks.get(net)
                 for d in _distances(router, net)]
    return len(router.cells), sum(distances), max(distances, default=0)


def _rotate_output(router, point, rotation):
    node = router.gates[point]; net = node['output']
    old_root = router.roots[net]; old_cell = router.cells[point]
    cell = Cell(old_cell.type, rotation, old_cell.mirrored)
    root = next(destinations(point, cell))
    blockers = []
    if root in router.reserved or not router.route_allowed(root):
        raise MapError('Gate output is reserved')
    if root in router.pins[point] or root in router.gates:
        raise MapError('Gate output overlaps an input or another gate')
    if root in router.cells and router.owners.get(root) != net:
        blocker = router.owners[root]
        if root in router.fixed_cells or blocker not in router.roots:
            raise MapError('Gate output overlaps a fixed foreign contact')
        # A mutable neighbouring wire must not freeze a gate's output side.
        # Rebuild that whole net after the trial output, preserving its pins.
        blockers.append(blocker); router.clear_net(blocker)
    # A source root may also be an input contact of another gate. Retain that
    # receiver, but do not retain the old, arbitrary output stub as a fixture.
    if old_root != root and old_root not in router.sinks[net]:
        router.fixed_cells.discard(old_root)
        router.fixed_outs.pop(old_root, None)
    router.clear_net(net)
    router.cells[point] = cell
    if root not in router.cells:
        router.add(root, net)
    router.roots[net] = root
    router.fixed_cells.add(root)
    router.fixed_outs.setdefault(root, set(router.outs.get(root, ())))
    router.direct_nets.discard(net)
    return blockers


def _reroute(router, net, far_first=False, validate=True):
    router.clear_net(net)
    tree = router.tree(net)
    pending = set(router.sinks[net])-tree
    while pending:
        goal = min(pending, key=lambda p: (
            (-1 if far_first else 1)*min(abs(p[0]-s[0])+abs(p[1]-s[1]) for s in tree), p))
        path = router.path(tree, goal, 32)
        if path is None:
            raise MapError('No shorter safe route for '+net)
        for point in path[1:-1]:
            router.add(point, net)
        for point, target in zip(path, path[1:]):
            router.outs[point].add(target)
        tree.update(path); pending.remove(goal)
    if validate:router.finish()


def optimize_router(router, passes=2):
    """Compare all four outputs of combinational arrows on a routed map.

    Input pins remain fixed, including strict pulse-detector and adder macros.
    The output of an AND beside a NOT can rotate independently. Exact map
    validation rejects reversed links, foreign inputs and altered native blocks.
    Stateful arrows and public output ports cannot change their output direction.
    """
    if type(passes) is not int or not 1 <= passes <= 8:
        raise MapError('Route optimization passes must be an integer from 1 to 8')
    before = len(router.cells); trials = rejected = accepted = 0; changes = []
    old_active = getattr(router, '_route_optimization_active', False)
    old_history = getattr(router, 'routing_history', {})
    old_step = getattr(router, 'routing_jump_cost', 1.05)
    router._route_optimization_active = True
    router.routing_history = {}; router.routing_jump_cost = 1
    rounds = 0
    try:
        for round_index in range(passes):
            rounds += 1; improved = False
            for net in sorted(router.roots):
                if not router.sinks.get(net):
                    continue
                point = router.source_positions.get(net)
                gate = router.gates.get(point)
                rotatable = (gate is not None and point not in router.flexible_gates
                             and net not in router.output_nets
                             and router.roots[net] != point
                             and router.cells[point].type in (15, 16, 17, 20, 21))
                rotations = range(4) if rotatable else (None,)
                original = _snapshot(router); old_score = best_score = _full_score(router)
                best = original
                best_blockers = []
                old_rotation = router.cells[point].rotation if rotatable else None
                orders = (False, True) if len(set(router.sinks[net])) > 1 else (False,)
                for rotation in rotations:
                    for far_first in orders:
                        trials += 1; _restore(router, original)
                        try:
                            blockers = []
                            if rotation is not None:
                                blockers = _rotate_output(router, point, rotation)
                            _reroute(router, net, far_first, validate=False)
                            for blocker in blockers:
                                _reroute(router, blocker, far_first, validate=False)
                            router.finish()
                            score = _full_score(router)
                            if score < best_score:
                                best_score = score; best = _snapshot(router); best_blockers = blockers
                        except MapError:
                            rejected += 1
                _restore(router, best)
                if best_score < old_score:
                    improved = True; accepted += 1
                    changes.append(dict(net=net, before=list(old_score), after=list(best_score),
                                        rotation_before=old_rotation,
                                        rotation_after=router.cells[point].rotation if rotatable else None,
                                        rerouted_neighbors=best_blockers))
            if not improved:
                break
        router.validate()
        report = dict(backend='ArrowsHDL.route_optimization', before_cells=before,
                      after_cells=len(router.cells), passes=rounds, trials=trials,
                      rejected_trials=rejected, accepted_nets=accepted, changes=changes,
                      objective='min_cells_then_sum_all_receiver_ticks_then_longest_receiver_ticks',
                      gate_directions=4, fixed_native_blocks=True, fixed_receiver_contacts=True)
        router.route_optimization = report
        return router.cells
    finally:
        router._route_optimization_active = old_active
        router.routing_history = old_history; router.routing_jump_cost = old_step
