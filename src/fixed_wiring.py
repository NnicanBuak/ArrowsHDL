"""Route new connections around arbitrary immutable native cell maps."""
from collections import defaultdict
from compact_layout import Router
from arrow_layout import bounds_of
from arrow_layout import destinations
from compact_layout import wire_cell, manhattan
from negotiated_routing import CongestionRouting

class FixedWiring(CongestionRouting,Router):
    """Route only external wires. All original physical cells remain fixed."""
    def route_allowed(self,position):return True
    def __init__(self,cells,reserved=()):
        self.cells=dict(cells)
        self.owners={p:'internal' for p in cells}
        self.outs={}
        self.gates={};self.pins={};self.flexible_gates=set()
        self.roots={};self.sinks=defaultdict(list)
        self.reserved={q for p,c in cells.items() for q in destinations(p,c) if q not in cells}
        self.reserved.update(map(tuple,reserved))
        self.fixed_cells=set(cells);self.fixed_outs={}
        self.max_cells=990_000
        self.ripups=0
        b=bounds_of(cells);self.bounds=(*b['min'],*b['max'])
    def connection(self,name,source,targets):
        source=tuple(source)
        self.reserved.discard(source)
        self.add(source,name)
        self.roots[name]=source
        for target,contact in targets:
            target,contact=tuple(target),tuple(contact)
            self.reserved.discard(target)
            self.add(target,name)
            self.outs[target]={contact}
            self.sinks[name].append(target)
    def clear_net(self,net):
        self.route_attempts=getattr(self,'route_attempts',0)+1
        if self.route_attempts%25==0:
            print(f'External route {self.route_attempts}/{len(self.sinks)}: {net}, {len(self.cells)} cells',flush=True)
        super().clear_net(net)
    def path(self,tree,goal,margin,soft=False):
        # Seed the nearby branch contacts, rather than every arrow of a global
        # bus. Local bounds prevent an obstructed pin from flooding the board.
        candidates=sorted(tree,key=lambda p:manhattan(p,goal))[:96]
        old=self.bounds
        xs=[p[0] for p in candidates]+[goal[0]];ys=[p[1] for p in candidates]+[goal[1]]
        self.bounds=(min(xs)-130,min(ys)-130,max(xs)+130,max(ys)+130)
        try:path=super().path(set(candidates),goal,margin,soft)
        finally:self.bounds=old
        if path is None and margin>=32:
            return super().path(tree,goal,margin,soft)
        return path
    def route_all(self):
        self.fixed_cells=set(self.cells)
        self.fixed_outs={p:set(out) for p,out in self.outs.items()}
        # Fix boundary positions as well as internal cells.
        b=bounds_of(self.cells);self.bounds=(*b['min'],*b['max'])
        print(f'Routing {len(self.sinks)} external nets ({len(self.cells)} fixed cells)',flush=True)
        self.route_phase(self.sinks)
        print(f'Routed: {len(self.cells)} cells, {self.ripups} wire negotiations',flush=True)
        for p,targets in self.outs.items():
            if not targets:
                # A source without consumers is deliberately absent from this router.
                raise ValueError(f'Unused external source {p}')
            self.cells[p]=wire_cell(p,targets)
            if self.cells[p] is None:raise ValueError(f'Unsupported external branch {p}')
        # Exact destinations make jumps insulated. Also forbid the reverse edge
        # which would create an undeclared feedback loop in the compiled map.
        for p,targets in self.outs.items():
            for q in destinations(p,self.cells[p]):
                if q in self.cells and q not in targets:raise ValueError(f'Short {p}->{q}')
            for q in targets:
                if p in destinations(q,self.cells[q]):raise ValueError(f'Reversed edge {p}->{q}')
        return self.cells
