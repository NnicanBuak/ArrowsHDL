"""Bind identical modules on a grid using the common immutable-map router."""
from fixed_wiring import FixedWiring


def contact(meta,origins,index,name,output=False):
    entry=meta['outputs' if output else 'inputs'][name][0]
    x,y=origins[index]
    return {key:(entry[key][0]+x,entry[key][1]+y) for key in ('contact','fixture')}


def connect_grid(cells,meta,origins,width,*,vertical_gap=False,row_scan=(),start_values=None,terminal_targets=None,broadcasts=None,reserved=()):
    """Horizontal direct contacts, optional row gutters, a row-major scan.

    All ports are named by the caller; signal functions are not inferred here.
    Additional wiring is counted separately from the repeated module footprint.
    """
    from arrowasm import Cell
    before=len(cells);cells=dict(cells)
    for name,value in (start_values or {}).items():
        p=contact(meta,origins,0,'W:'+name)['fixture']
        if value:
            if p in cells:raise ValueError('Neutral scan source is occupied: '+str(p))
            cells[p]=Cell(2,0)
    w=FixedWiring(cells,reserved=reserved);w.max_cells=2_000_000
    height=len(origins)//width
    if vertical_gap:
        for row in range(height-1):
            for col in range(width):
                a=row*width+col;b=a+width
                for side,source,target in (('S',a,b),('N',b,a)):
                    opposite='N' if side=='S' else 'S'
                    for name in meta['outputs']:
                        if not name.startswith(side+':'):continue
                        key=opposite+name[1:]
                        if key not in meta['inputs']:continue
                        out=contact(meta,origins,source,name,True)
                        inp=contact(meta,origins,target,key)
                        w.connection(f'grid:{source}:{name}',out['fixture'],[(inp['fixture'],inp['contact'])])
    for key in row_scan:
        for row in range(height-1):
            out=contact(meta,origins,(row+1)*width-1,'E:'+key,True)
            inp=contact(meta,origins,(row+1)*width,'W:'+key)
            w.connection(f'scan:{row}:{key}',out['fixture'],[(inp['fixture'],inp['contact'])])
    for name,(source,targets) in (broadcasts or {}).items():
        w.connection('broadcast:'+name,source,targets)
    for name,(source,targets) in (terminal_targets or {}).items():
        w.connection('terminal:'+name,source,targets)
    result=w.route_all()
    return result,dict(backend='ArrowsHDL.grid_wiring',added_cells=len(result)-before,
                       row_gutters=vertical_gap,scan_fields=list(row_scan))
