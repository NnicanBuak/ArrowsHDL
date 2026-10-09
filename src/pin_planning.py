"""Match native incoming arrow contacts without factorial permutation search."""
from functools import lru_cache
from arrowasm import MapError


def incoming_contacts(position,excluded=()):
    from compact_layout import wire_cell
    x,y=position;excluded=set(excluded)
    points=[(x+dx,y+dy) for dx in range(-2,3) for dy in range(-2,3)
            if (dx or dy) and (x+dx,y+dy) not in excluded
            and wire_cell((x+dx,y+dy),{position}) is not None]
    return sorted(points,key=lambda p:(abs(p[0]-x)+abs(p[1]-y),p))


def choose_input_contacts(inputs,position,sources,compatible,*,excluded=(),preferred=None):
    """Minimum-distance distinct contacts, including diagonal and jump inputs.

    Compatibility is supplied by the physical router, not inferred from net names.
    The same native gate can receive independent one-step and two-step arrows
    from the same side. Its own output contacts remain excluded.
    """
    inputs=list(inputs);preferred=preferred or {}
    candidates=incoming_contacts(position,excluded)
    allowed=[[i for i,p in enumerate(candidates) if compatible(p,net)] for net in inputs]
    @lru_cache(None)
    def match(index,mask):
        if index==len(inputs):return 0,()
        best=None;net=inputs[index];source=sources[net]
        for i in allowed[index]:
            if mask&(1<<i):continue
            rest=match(index+1,mask|(1<<i))
            if rest is None:continue
            p=candidates[i]
            cost=abs(p[0]-source[0])+abs(p[1]-source[1])
            if preferred.get(net)==p:cost-=20
            value=(cost+rest[0],(p,)+rest[1])
            if best is None or value<best:best=value
        return best
    result=match(0,0)
    if result is None:raise MapError('Cannot assign native input contacts at '+str(position))
    return list(result[1])
