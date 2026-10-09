"""Physical causal timing on native arrows, with explicit state boundaries."""
from collections import deque, defaultdict
from heapq import heappop, heappush
from arrowasm import MapError
from arrow_layout import destinations
from native_rules import dependency_links


def effective_links(cells, memories=()):
    """Use native semantic dependencies and cut explicitly declared state inputs."""
    memory=set(map(tuple,memories))
    links=dependency_links(cells)
    return {p:[q for q in qs if q not in memory] for p,qs in links.items()}


def causal_depths(cells, memories=(), sources=None, *, source_times=None):
    """Longest combinational propagation, optionally from named coordinates.

    DELAY and RANDOM cost two ticks; ordinary paths and gates cost one.
    This is a propagation bound, not a proof for arbitrary feedback, toggle
    inputs or asynchronous handshakes. Those require their own contracts.
    """
    links=effective_links(cells,memories)
    degree=dict.fromkeys(cells,0)
    for targets in links.values():
        for q in targets:degree[q]+=1
    if source_times is not None:sources=source_times
    selected=set(cells) if sources is None else set(map(tuple,sources))
    if selected-set(cells):raise MapError('Источник анализа отсутствует в карте')
    depths={p:(source_times[p] if source_times is not None else 1) if p in selected else None for p in cells}
    queue=deque(p for p,d in degree.items() if d==0);seen=0
    while queue:
        p=queue.popleft();seen+=1
        for q in links[p]:
            if depths[p] is not None:
                candidate=depths[p]+(2 if cells[p].type in (4,20) else 1)
                depths[q]=max(depths[q] or 0,candidate)
            degree[q]-=1
            if degree[q]==0:queue.append(q)
    if seen!=len(cells):raise MapError('Неожиданная комбинационная обратная связь')
    return depths


def level_arrivals(cells, sources, memories=()):
    """First activation of a positive, initially zero native level network.

    Sources are activation times. OR paths activate on the first parent;
    Native threshold/SET on the second. XOR, NOT, RANDOM and TOGGLE are barriers. Explicit
    state boundaries prevent propagation into unrelated state machines.
    This contract is suitable for permanent phase broadcasts, not pulses.
    """
    links=effective_links(cells,memories)
    heap=[(t,tuple(p)) for p,t in sources.items()]
    from heapq import heapify
    heapify(heap)
    arrivals={};incoming=defaultdict(dict)
    while heap:
        t,p=heappop(heap)
        if p in arrivals:continue
        arrivals[p]=t
        for q in links[p]:
            c=cells[q]
            if c.type in (3,5,9,15,17,19,20,21,24,25):continue
            incoming[q][p]=t
            threshold=2 if c.type in (16,18) else 1
            if len(incoming[q])<threshold:continue
            parent=sorted(incoming[q].values())[threshold-1]
            heappush(heap,(parent+(2 if c.type==4 else 1),q))
    return arrivals


def propagation_bound(cells, memories=(), *, sources=None, sinks=None, margin=10):
    depths=causal_depths(cells,memories,sources)
    targets=cells if sinks is None else list(map(tuple,sinks))
    if set(targets)-set(cells):raise MapError('Приёмник анализа отсутствует в карте')
    values=[depths[p] for p in targets if depths[p] is not None]
    if not values:raise MapError('Нет причинного пути от источников к приёмникам')
    return max(values)+margin
