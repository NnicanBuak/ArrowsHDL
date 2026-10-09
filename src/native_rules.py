"""Semantic dependencies of the audited GraphDLC arrow profile.

Emission geometry and behavioral dependencies are different: detectors
read behind themselves, blockers inhibit their target, and generators
do not use ordinary incoming signals. Reciprocal links are real feedback.
"""
from arrow_layout import destinations
from arrowasm import MapError


def validate_gate_rule(node):
    """Reject logical operations the selected native receiver cannot represent."""
    count=len(node['inputs']);op=node['op']
    required={'BUF':1,'AND':2,'MAJ':3}
    if op in required and count!=required[op]:
        raise MapError(f'{op} requires {required[op]} inputs, got {count}; native type 16 is a threshold of two')
    if count>11:
        raise MapError(f'Native receiver needs an output contact: at most 11 inputs, got {count}')


def dependency_links(cells):
    links={p:set() for p in cells}
    for p,c in cells.items():
        for q in destinations(p,c):
            if q not in cells:continue
            target=cells[q].type
            if target==25:continue
            if c.type==3:
                links[p].add(q)
            elif target not in (2,5,9,21):
                links[p].add(q)
        if c.type==5:
            front=next(destinations(p,c))
            behind=(2*p[0]-front[0],2*p[1]-front[1])
            if behind in cells:links[behind].add(p)
    return links


def remove_passive_walls(cells):
    """Type 25 is permanently zero and emits nothing, just like empty space.

    Coordinates stay fixed. A layout may retain the empty guard region as
    reserved space so subsequent wiring does not fill it with other signals.
    """
    return {p:c for p,c in cells.items() if c.type!=25}
