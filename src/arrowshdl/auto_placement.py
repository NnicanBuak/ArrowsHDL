"""Deterministic graph placement and ordered ports fitted to their endpoints.

The ordinary build uses a bounded number of improving swaps. Compact builds
may explore additional shapes and annealed placements; no circuit templates
or application-specific geometry participate in this backend.
"""
from collections import defaultdict
import math
import random
from statistics import median


def arrange(graph, macros, *, pitch=6, aspect=1.0, search=False, seed=0,cluster=True):
    nodes = graph['nodes']
    count = len(nodes)
    if cluster and count>256:
        grouped = arrange_modules(graph,macros,pitch,aspect,search,seed)
        if grouped is not None: return grouped
    columns = max(1, math.ceil(math.sqrt(max(1, count) * aspect)))
    # Each row and column fits the actual macro extent, including its pins.
    widths = [pitch] * columns
    heights = [pitch] * max(1, math.ceil(count / columns))
    extents = []
    for part, pins, _ in macros:
        points = list(part) + [p for p, _ in pins]
        extents.append((min(x for x, y in points), min(y for x, y in points),
                        max(x for x, y in points), max(y for x, y in points)))
    # Wide timing macros occupy their own fitting slots rather than enlarging
    # every slot according to the largest macro in the design.
    large = [i for i,(x0,y0,x1,y1) in enumerate(extents) if x1-x0>pitch-3 or y1-y0>pitch-3]
    preferred = sorted(range(len(heights)*columns),key=lambda i:(i%columns,i//columns))
    assignments = dict(zip(large,preferred))
    vacant = iter(i for i in range(len(heights)*columns) if i not in assignments.values())
    assignments.update({i:next(vacant) for i in range(count) if i not in assignments})
    for i, (x0,y0,x1,y1) in enumerate(extents):
        slot = assignments[i]
        widths[slot % columns] = max(widths[slot % columns], x1-x0+4)
        heights[slot // columns] = max(heights[slot // columns], y1-y0+4)
    xs = [sum(widths[:i]) for i in range(columns)]
    ys = [sum(heights[:i]) for i in range(len(heights))]
    slots = [(x, y) for y in ys for x in xs]
    positions = [slots[assignments[i]] for i in range(count)] + [slots[i] for i in range(len(slots)) if i not in assignments.values()]
    occupants = {p:i for i,p in enumerate(positions)}
    capacities = {(x,y):(widths[c]-4,heights[r]-4) for r,y in enumerate(ys) for c,x in enumerate(xs)}
    sources = {n['output']: i for i,n in enumerate(nodes)}
    neighbors = defaultdict(list)
    for i,n in enumerate(nodes):
        for net in n['inputs']:
            if net in sources and sources[net] != i:
                j = sources[net]
                neighbors[i].append(j); neighbors[j].append(i)

    def distance(a,b):
        return abs(a[0]-b[0])+abs(a[1]-b[1])

    def delta(a,b):
        pa,pb = positions[a],positions[b]
        return sum(distance(pb,positions[j])-distance(pa,positions[j]) for j in neighbors[a] if j!=b) + sum(
            distance(pa,positions[j])-distance(pb,positions[j]) for j in neighbors[b] if j!=a)

    def fits(node,position):
        if node>=count: return True
        x0,y0,x1,y1 = extents[node]
        w,h = capacities[position]
        return x1-x0<=w and y1-y0<=h

    if count:
        # Four sweeps cap default placement work; all accepted moves shorten
        # the graph's total internal wire length.
        for _ in range(4):
            changed = False
            for a in range(count):
                if not neighbors[a]: continue
                center = (median(positions[j][0] for j in neighbors[a]),
                          median(positions[j][1] for j in neighbors[a]))
                near_x = sorted(xs,key=lambda x:abs(x-center[0]))[:4]
                near_y = sorted(ys,key=lambda y:abs(y-center[1]))[:4]
                choices = [occupants[(x,y)] for x in near_x for y in near_y]
                choices = [b for b in choices if fits(a,positions[b]) and fits(b,positions[a])] or [a]
                b = min(choices, key=lambda b:(delta(a,b),b))
                if delta(a,b) < 0:
                    positions[a],positions[b] = positions[b],positions[a]
                    occupants[positions[a]],occupants[positions[b]] = a,b
                    changed = True
            if not changed: break
        if search and len(slots)>1:
            rng = random.Random(seed)
            best = positions[:]
            cost = sum(distance(positions[i],positions[j]) for i in range(count) for j in neighbors[i])//2
            best_cost = cost
            iterations = min(30000,max(2000,count*120))
            for step in range(iterations):
                a,b = rng.sample(range(len(slots)),2)
                if not fits(a,positions[b]) or not fits(b,positions[a]): continue
                change = delta(a,b)
                temperature = pitch*(1-step/iterations)**3 + 0.01
                if change <= 0 or rng.random() < math.exp(-change/temperature):
                    positions[a],positions[b] = positions[b],positions[a]; cost += change
                    if cost < best_cost: best,best_cost = positions[:],cost
            positions = best
    return [(x-extents[i][0],y-extents[i][1]) for i,(x,y) in enumerate(positions[:count])]


def arrange_modules(graph,macros,pitch,aspect,search,seed):
    """Keep elaborated module neighborhoods together in large designs."""
    logical = [instance for instance in graph.get('instances',())
               if not str(instance.get('module','')).startswith('arrows_')]
    membership = defaultdict(list)
    for instance in logical:
        for node in instance['nodes']: membership[node].append(instance['name'])
    groups = defaultdict(list); ownership = {}
    for i,node in enumerate(graph['nodes']):
        owner = max(membership[node['id']],key=lambda p:(p.count('.'),p)) if membership[node['id']] else node.get('scope','core')
        # Generated blocks can contain several logical modules. Their common
        # parent is a natural neighborhood, inferred from elaborated hierarchy.
        parts = owner.split('.')
        if len(parts)>1 and parts[-2].endswith(']'): owner = '.'.join(parts[:-1])
        ownership[node['output']] = owner; groups[owner].append(i)
    if len(groups)<4: return None
    producers = {node['output']:ownership[node['output']] for node in graph['nodes']}
    local = {}; shapes = []; names = list(groups)
    for name,indices in groups.items():
        sub = dict(nodes=[graph['nodes'][i] for i in indices])
        positions = arrange(sub,[macros[i] for i in indices],pitch=pitch,search=search,seed=seed,cluster=False)
        points = [(p[0]+q[0],p[1]+q[1]) for i,p in zip(indices,positions) for q in macros[i][0]]
        lo = min(x for x,y in points)-1,min(y for x,y in points)-1
        hi = max(x for x,y in points)+1,max(y for x,y in points)+1
        local[name] = {i:(p[0]-lo[0],p[1]-lo[1]) for i,p in zip(indices,positions)}
        shapes.append(({(0,0):None,(hi[0]-lo[0],hi[1]-lo[1]):None},[],(0,0)))
    edges = defaultdict(set)
    for name,indices in groups.items():
        for i in indices:
            edges[name].update(producers[net] for net in graph['nodes'][i]['inputs']
                               if net in producers and producers[net]!=name)
    block_graph = dict(nodes=[dict(id=name,output=name,inputs=sorted(edges[name])) for name in names])
    blocks = arrange(block_graph,shapes,pitch=pitch,aspect=aspect,search=search,seed=seed,cluster=False)
    positions = [None]*len(graph['nodes'])
    for name,offset in zip(names,blocks):
        for i,p in local[name].items(): positions[i] = p[0]+offset[0],p[1]+offset[1]
    return positions


def fit_ports(groups, endpoints, bounds, used=None, *, output=False, margin=5,step=2):
    """Choose a face per bus, keeping bits ordered and neighboring banks apart."""
    used = set() if used is None else used
    x0,y0 = bounds['min']; x1,y1 = bounds['max']
    result = {}
    faces = ('right','bottom','top','left') if output else ('left','top','bottom','right')
    for name,entries in groups.items():
        best = None
        for side in faces:
            vertical = side in ('left','right')
            axis = 1 if vertical else 0
            locations = [endpoints.get(e['net'],[(x0,y0)]) for e in entries]
            preferred = [median(p[axis] for p in points) for points in locations]
            start = round(median(p-i*step for i,p in enumerate(preferred)))
            length = max(0,(len(entries)-1)*step)
            lo,hi = (y0,y1) if vertical else (x0,x1)
            start = max(lo, min(start,max(lo,hi-length)))
            def point(along):
                return (x0-margin,along) if side=='left' else (x1+margin,along) if side=='right' else (along,y0-margin) if side=='top' else (along,y1+margin)
            while any(point(start+i*step+d) in used for i in range(len(entries)) for d in (-1,0,1)):
                start += 2
            trial = [point(start+i*step) for i in range(len(entries))]
            cost = sum(abs(p[0]-q[0])+abs(p[1]-q[1]) for p,points in zip(trial,locations) for q in points)
            # Account for a bank extending the whole map, not just gate-to-port
            # distances, so many small ports cannot grow an unbounded tail.
            cost += max(0,start+length-hi)*max(1,len(entries))
            if best is None or cost<best[0]: best = (cost,side,trial)
        _,side,trial = best
        inward = {'left':1,'top':2,'right':3,'bottom':0}[side]
        rotation = (inward+2)%4 if output else inward
        direction = {0:(0,-1),1:(1,0),2:(0,1),3:(-1,0)}[rotation]
        result[name] = []
        for entry,p in zip(entries,trial):
            dx,dy = direction
            fixture = (p[0]+dx,p[1]+dy) if output else (p[0]-dx,p[1]-dy)
            result[name].append(dict(index=entry['index'],contact=list(p),fixture=list(fixture),
                                     rotation=rotation,side=side))
            used.add(p)
    return result
