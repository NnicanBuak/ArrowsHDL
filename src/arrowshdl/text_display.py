"""Signal-driven text: original font pixels in red, routing arrows in blue."""
from pathlib import Path
from collections import deque

from arrowshdl.arrowasm import Cell, MapError
from arrowshdl.arrow_layout import bounds_of, destinations, depth_of
from arrowshdl.fixed_wiring import FixedWiring
from arrowshdl.lettering import text_pixels
from arrowshdl.mapdata import map_hash
from arrowshdl.progress import report
from arrowshdl.compact_layout import wire_cell


def font_file(base, reference):
    if not isinstance(reference,str) or not reference: raise MapError('Font must be a nonempty filename or library:arrow4')
    if reference == 'library:arrow4':
        from arrowshdl.resources import PACKAGE
        return PACKAGE/'data/fonts/arrow4.json'
    path=Path(base)/reference
    if not path.is_file(): raise MapError(f'Font file not found: {path.resolve()}')
    return path


def compile_display(base, row):
    text=row.get('text')
    bitmap=row.get('bitmap')
    if bitmap is not None:
        if not isinstance(bitmap,list) or not bitmap or not all(isinstance(r,str) and r and len(r)==len(bitmap[0]) and set(r)<=set('.#') for r in bitmap):
            raise MapError('Display bitmap requires equal-width rows of . and #')
        pixels={(x,y) for y,r in enumerate(bitmap) for x,c in enumerate(r) if c=='#'}
        dimensions=(len(bitmap[0]),len(bitmap));font='bitmap';text=None
    else:
        if not isinstance(text,str) or not text: raise MapError('Text display requires nonempty text')
        font=font_file(base,row.get('font','library:arrow4'))
        pixels,dimensions=text_pixels(font,text,row.get('size',1))
    if not pixels: raise MapError('Text display contains no pixels')
    report(0,f'Connecting text display: {row["name"]}')
    cells={};reserved=set()
    # A directed red tree spans each connected stroke. Its pixels retain
    # the exact font raster, including solid strokes at integer scales.
    remaining=set(pixels);roots=[]
    neighbors=lambda p:[(p[0]+dx,p[1]+dy) for dx,dy in ((1,0),(0,1),(-1,0),(0,-1))]
    while remaining:
        root=min(remaining,key=lambda p:(p[1],p[0]));roots.append(root)
        remaining.remove(root);queue=deque([root])
        while queue:
            point=queue.popleft();children=[]
            for child in neighbors(point):
                if child in remaining:
                    remaining.remove(child);queue.append(child);children.append(child)
            if children:
                cell=wire_cell(point,set(children))
                if cell is None or cell.type not in (1,6,7,8): raise MapError('Text stroke requires an unsupported red branch')
                cells[point]=cell
                continue
            x,y=point
            for rotation,(dx,dy) in ((2,(0,1)),(1,(1,0)),(3,(-1,0)),(0,(0,-1))):
                guard=(x+dx,y+dy)
                if guard not in pixels:
                    cells[x,y]=Cell(1,rotation);reserved.add(guard);break
            else: raise MapError('Text stroke has no free emission space')
    contact=(-8,-6);fixture=(-9,-6)
    cells[contact]=Cell(12,1)
    source=(-7,-6)
    targets=[];claimed=set()
    offsets=((0,-2),(-2,0),(2,0),(-1,-1),(1,-1),(0,2),(-1,1),(1,1),(0,-1),(-1,0),(1,0),(0,1))
    frame=bounds_of(cells)
    def accessible(pin):
        seen={pin};queue=deque([pin])
        while queue and len(seen)<=256:
            p=queue.popleft()
            if not (frame['min'][0]<=p[0]<=frame['max'][0] and frame['min'][1]<=p[1]<=frame['max'][1]): return True
            for dx,dy in offsets:
                q=(p[0]+dx,p[1]+dy)
                if q not in seen and q not in cells and q not in reserved:
                    seen.add(q);queue.append(q)
        return bool(queue)
    for x,y in roots:
        choices=[(x+dx,y+dy) for dx,dy in offsets
                 if (x+dx,y+dy) not in cells and (x+dx,y+dy) not in reserved and (x+dx,y+dy) not in claimed
                 and accessible((x+dx,y+dy))]
        if not choices: raise MapError(f'No blue wire contact for text pixel {(x,y)}')
        pin=min(choices,key=lambda p:abs(p[0]-source[0])+abs(p[1]-source[1]))
        claimed.add(pin);targets.append((pin,(x,y)))
    router=FixedWiring(cells,reserved|{fixture})
    blue=[Cell(kind,rotation,mirrored) for kind in range(10,15)
          for rotation in range(4) for mirrored in (False,True)]
    def blue_wire(position,wanted):
        for cell in blue:
            actual=set(destinations(position,cell))
            if wanted<=actual and not ((actual-wanted)&router.cells.keys()): return cell
        return None
    router.wire_cell=blue_wire
    router.route_allowed=lambda p:p[0]>=contact[0]
    # A blue splitter delivers one signal to both adjacent parity grids.
    router.connection('text',source,targets)
    router.outs[source].add((-6,-6))
    router.reserved.discard((-6,-6))
    router.add((-6,-6),'text')
    router.outs[-6,-6]=set()
    cells=router.route_all()
    ticks=depth_of(cells)+2
    meta=dict(top=row['name'],inputs={'signal':[dict(index=0,contact=list(contact),fixture=list(fixture),rotation=1)]},outputs={},
        map_hash=map_hash(cells),cells=len(cells),bounds=bounds_of(cells),settle_ticks=ticks,
        timing={'state_boundaries':[]},display=dict(text=text,font=str(font),size=row.get('size',1),
        pixels=[list(p) for p in sorted(pixels)],pixel_color='red',wire_color='blue',dimensions=list(dimensions)))
    return cells,meta
