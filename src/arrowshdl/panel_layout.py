"""Reserve a module's interaction panel before placing or routing its logic."""
from pathlib import Path
from collections import defaultdict
import math

from arrowshdl.arrowasm import Cell, MapError
from arrowshdl.arrow_layout import bounds_of, destinations
from arrowshdl.components import load_component, move
from arrowshdl.manifest import component_file
from arrowshdl.presentation import button_cells
from arrowshdl.fixed_wiring import FixedWiring
from arrowshdl.physical import dependencies


def prepare_panel(graph, config, base):
    button=config['button'];size=config.get('size',[7,7])
    if button not in graph['inputs'] or len(graph['inputs'][button])!=1:
        raise MapError('Panel button must refer to a scalar HDL input')
    w,h=size;at=(0,h//2);contact=(0,h//2+1)
    buttons=button_cells(at,2,size)
    cells={};displays={};targets=defaultdict(list);consumed=set()
    ports={};reserved=set(buttons);reserved.discard(at)
    right_target=None
    for side,item in ((s,config[s]) for s in ('left','right') if s in config):
        if 'file' in item:
            part,meta=load_component(component_file(Path(base),item['file']))
        else:
            from arrowshdl.text_display import compile_display
            part,meta=compile_display(Path(base),dict(name=side,bitmap=item['bitmap']))
        if meta['outputs'] or len(meta['inputs'])!=1:
            raise MapError('Panel display must have one input bus and no outputs')
        port=item['port'];entries=graph['outputs'].get(port)
        input_name=next(iter(meta['inputs']))
        if entries is None or len(entries)!=len(meta['inputs'][input_name]):
            raise MapError('Panel display width does not match HDL output: '+port)
        b=bounds_of(part)
        dx=(-w//2-4-b['max'][0]) if side=='left' else (w//2+4-b['min'][0])
        dy=-(b['min'][1]+b['max'][1])//2
        part,meta=move(part,meta,[dx,dy]);cells.update(part)
        displays[side]=dict(port=port,inputs=meta['inputs'],pixels=meta.get('display',{}).get('pixels',[]),
                           segment_pixels=meta.get('segment_pixels',[]))
        consumed.add(port)
        for bit,pin in zip(entries,meta['inputs'][input_name]):
            if side=='right':
                if len(entries)!=1: raise MapError('Right bitmap panel requires one input signal')
                right_target=(bit,dict(pin))
            else:
                targets[bit['net']].append((tuple(pin['fixture']),tuple(pin['contact'])))
                reserved.add(tuple(pin['fixture']))
    b=bounds_of(cells or buttons)
    if right_target:
        bit,pin=right_target
        p=(pin['fixture'][0],b['min'][1]-4)
        cells[p]=Cell(1,2);fixture=(p[0],p[1]-1)
        router=FixedWiring(cells,reserved|{at,fixture})
        router.connection('panel:indicator',next(destinations(p,cells[p])),[(pin['fixture'],pin['contact'])])
        cells=router.route_all()
        targets[bit['net']].append((fixture,p));reserved.add(fixture)
    b=bounds_of(cells or buttons);bottom=max(b['max'][1],contact[1])+1
    for y in range(contact[1],bottom):cells[0,y]=Cell(1,2)
    region=bounds_of({**cells,**buttons})
    # No unrelated signal may enter any empty position of the interaction area.
    empty={(x,y) for y in range(region['min'][1],region['max'][1]+1)
                  for x in range(region['min'][0],region['max'][0]+1)}-cells.keys()
    reserved.update(empty)
    terminal=dict(index=0,contact=list(contact),fixture=list(at),rotation=2,panel=True)
    ports[button]=[terminal]
    expected=dependencies(cells)
    for net,sinks in targets.items():
        for pin,dest in sinks: expected[dest]['I'].add(tuple(pin))
        for pin,dest in sinks: reserved.discard(tuple(pin))
    return dict(cells=cells,expected=expected,targets=targets,inputs=ports,
                roots={graph['inputs'][button][0]['net']:(0,bottom)},reserved=reserved,
                consumed=consumed,metadata=dict(region=region,button=[list(p) for p in buttons],
                    size=size,input=button,displays=displays))


def ring_positions(graph,macros,region,pitch,aspect,search,seed):
    """Fit the same generic graph slots around a rectangular interaction area."""
    from arrowshdl.auto_placement import arrange
    # Empty fixed slots cover the panel; movable gates use the remaining slots.
    x0,y0=region['min'];x1,y1=region['max']
    panel_columns=math.ceil((x1-x0+8)/pitch);panel_rows=math.ceil((y1-y0+8)/pitch)
    n=len(macros)
    border=max(1,math.ceil((math.sqrt((panel_columns+panel_rows)**2+4*n)-panel_columns-panel_rows)/4))
    columns=panel_columns+2*border;rows=panel_rows+2*border
    while columns*rows-panel_columns*panel_rows<n:
        if columns<rows*aspect: columns+=2
        else: rows+=2
    slots=[(x0-4-border*pitch+c*pitch,y0-4-border*pitch+r*pitch)
           for r in range(rows) for c in range(columns)
           if not (border<=c<border+panel_columns and border<=r<border+panel_rows)]
    # The regular placement supplies a graph-informed order, independent of HDL names.
    local=arrange(graph,macros,pitch=pitch,aspect=aspect,search=search,seed=seed,cluster=False)
    order=sorted(range(n),key=lambda i:(local[i][1],local[i][0]))
    positions=[None]*n
    for i,p in zip(order,slots):
        points=list(macros[i][0])+[pin for pin,contact in macros[i][1]]
        lo=(min(x for x,y in points),min(y for x,y in points))
        positions[i]=(p[0]-lo[0],p[1]-lo[1])
    producers={n['output']:i for i,n in enumerate(graph['nodes'])};neighbors=defaultdict(list)
    for i,node in enumerate(graph['nodes']):
        for net in node['inputs']:
            if net in producers:
                j=producers[net];neighbors[i].append(j);neighbors[j].append(i)
    distance=lambda a,b:abs(a[0]-b[0])+abs(a[1]-b[1])
    def delta(a,b):
        pa,pb=positions[a],positions[b]
        return sum(distance(pb,positions[j])-distance(pa,positions[j]) for j in neighbors[a] if j!=b)+sum(distance(pa,positions[j])-distance(pb,positions[j]) for j in neighbors[b] if j!=a)
    # Swaps keep every macro outside the fixed panel. Optimize the actual ring,
    # rather than assuming a solid rectangular placement has the same distances.
    for sweep in range(12 if search else 6):
        changed=False
        for a in range(n):
            if not neighbors[a]:continue
            center=tuple(sum(positions[j][k] for j in neighbors[a])/len(neighbors[a]) for k in (0,1))
            choices=sorted(range(n),key=lambda b:distance(center,positions[b]))[:16]
            b=min(choices,key=lambda b:(delta(a,b),b))
            if delta(a,b)<0:positions[a],positions[b]=positions[b],positions[a];changed=True
        if not changed:break
    return positions
