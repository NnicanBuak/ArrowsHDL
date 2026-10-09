"""Reuse one digit from the supplied map; unsigned input is limited to 0..7."""
import json
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
PROJECT=HERE.parents[1]
sys.path.insert(0,str(PROJECT/'src'))
from arrowasm import Cell
from arrow_layout import edges,bounds_of
from input_buses import verify_exterior
from mapdata import read_map,write_map,write_json,map_hash

SOURCE_URL='https://logic-arrows.io/map-0TNlFXRQa6Y'
SEGMENTS=[(78,-66),(81,-64),(81,-58),(78,-56),(75,-58),(75,-64),(78,-60)]


def build():
    original=read_map(HERE/'reference/original.save.txt')
    reverse={p:[] for p in original}
    for p,targets in edges(original).items():
        for q in targets:reverse[q].append(p)
    for p,c in original.items():
        if c.type!=5:continue
        dx,dy=0,1
        for _ in range(c.rotation):dx,dy=-dy,dx
        q=p[0]+dx,p[1]+dy
        if q in original:reverse[p].append(q)
    # Follow real dependencies of the seven segment drivers, including detector
    # observations. Rectangular crops alone cut shared contacts on the left.
    seen=set();todo=[(x,-48) for x in range(74,81)]
    while todo:
        p=todo.pop()
        if p in seen or not -48<=p[1]<=-28:continue
        seen.add(p);todo.extend(reverse[p])
    selected={p:c for p,c in original.items() if p in seen or (74<=p[0]<=81 and -66<=p[1]<=-49)}
    for p in ((68,-28),(69,-28),(69,-27),(71,-27),(72,-27)):selected[p]=original[p]
    # The original bit-3 input at (68,-28) has no external driver: it stays zero.
    # Bring the three remaining contacts onto one exterior bottom face.
    for x in (69,71,72):selected[x,-26]=Cell(1,0)
    cells={(x-68,y+66):c for (x,y),c in selected.items()}
    inputs={'n':[{'index':i,'contact':[x-68,40],'fixture':[x-68,41],'rotation':0}
                 for i,x in enumerate((72,71,69))]}
    meta={'schema':1,'top':'digit3','profile':'GraphDLC-01232bd','map_hash':map_hash(cells),
          'cells':len(cells),'bounds':bounds_of(cells),'inputs':inputs,'outputs':{},
          'source_url':SOURCE_URL,'reference_map_hash':map_hash(original),
          'layout':'reused-seven-segment-module','input_range':[0,7],
          'fixed_most_significant_bit':0,'binary_to_bcd_converter':False,
          'segments':[list((x-68,y+66)) for x,y in SEGMENTS],
          'segment_order':['a','b','c','d','e','f','g'],
          'requested_bus_gap':'auto','input_pitches':[1,2]}
    verify_exterior(cells,meta)
    folder=HERE/'build';write_map(folder,'digit3',cells);write_json(folder/'digit3.build.json',meta)
    test=dict(cells)
    for p in inputs['n']:test[tuple(p['fixture'])]=Cell(22,0)
    write_map(folder,'digit3.test',test)
    for value in range(8):
        preset=dict(cells)
        for i,p in enumerate(inputs['n']):
            x,y=p['fixture']
            preset[x,y]=Cell(1,0);preset[x,y+1]=Cell(1,0)
            if value&(1<<i):preset[x,y+2]=Cell(2,0)
        write_map(folder/'presets',f'digit{value}',preset)
    return cells,meta


if __name__=='__main__':
    cells,meta=build();print(f'digit3: {len(cells)} cells; one digit, three inputs')
