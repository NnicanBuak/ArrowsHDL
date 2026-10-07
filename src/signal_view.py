"""Portable coloured views of the actual exported arrow map.

Electrical nets change at operators. Input ancestry is a separate layer;
neither layer changes cell types, directions, or the game save.
"""
import argparse
import base64
import colorsys
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps, ImageEnhance

from arrowasm import MapError
from arrow_layout import bounds_of
from mapdata import map_hash, read_map
from map_preview import font
from test_harness import add_fixture

ROOT = Path(__file__).resolve().parents[1]


def net_color(index):
    rgb = colorsys.hls_to_rgb((index * 0.61803398875) % 1, .72, 1)
    return '#'+''.join(f'{round(channel*255):02x}' for channel in rgb)


def view_data(cells, manifest):
    if map_hash(cells) != manifest['map_hash']:
        raise MapError('Цветной предпросмотр: карта не соответствует метаданным')
    signals = manifest.get('signals')
    if not signals:
        raise MapError('Цветной предпросмотр: нет описания сигналов')
    nets = [dict(net, color=net_color(i)) for i,net in enumerate(signals['nets'])]
    buses = signals['input_buses']
    sources=[{'id':f"{bus['name']}:{bit}",'bus':bus['name'],'bit':bit,
              'label':f"{bus['name']}[{bit}]"} for bus in buses for bit in bus['bits']]
    for i,source in enumerate(sources):source['color']=net_color(len(nets)+2+i)
    net_at = {tuple(point):i for i,net in enumerate(nets) for point in net['cells']}
    if sum(len(net['cells']) for net in nets)!=len(cells) or set(net_at) != set(cells):
        raise MapError('Каждая стрелка должна принадлежать ровно одному сигналу')
    for source in sources:
        entry=next(e for e in manifest['inputs'][source['bus']] if e['index']==source['bit'])
        source['net']=nets[net_at[tuple(entry['contact'])]]['id']
    by_net={n['id']:n for n in nets}
    source_colours={s['net']:s['color'] for s in sources}
    def route_colour(net):
        if 'route_color' not in net:
            driver=net['driver']
            if driver and driver['op']=='BUF':
                net['route_color']=route_colour(by_net[net['inputs'][0]])
            else:net['route_color']=source_colours.get(net['id'],net['color'])
        return net['route_color']
    for net in nets:route_colour(net)
    modules=describe_modules(nets)
    drivers = {tuple(net['driver']['at']):net['driver'] for net in nets if net['driver']}
    # Add the normal test-port sprites only to the displayed map. Production
    # cells and the exported game save retain their original hash and count.
    display=add_fixture(cells,manifest)
    markers=[]
    for kind in ('inputs','outputs'):
        for name,entries in manifest[kind].items():
            for entry in entries:
                at=tuple(entry['fixture']);cell=display[at]
                markers.append({'at':list(at),'type':cell.type,'rotation':cell.rotation,'mirrored':cell.mirrored,
                                'net':net_at[tuple(entry['contact'])],'kind':kind,
                                'source':f"{name}:{entry['index']}",'label':f"{name}[{entry['index']}]",
                                'contact':entry['contact'],'gate':None})
    sprites={}
    for type_id in {cell.type for cell in display.values()}|{22,23}:
        asset=(ROOT / f'assets/sprites/arrow{type_id}.png').read_bytes()
        sprites[str(type_id)]='data:image/png;base64,'+base64.b64encode(asset).decode('ascii')
    return {'top':manifest['top'], 'hash':manifest['map_hash'],
            'core':manifest.get('logic_core'), 'bounds':bounds_of(display),'production_bounds':manifest['bounds'],
            'ports':{kind:manifest[kind] for kind in ('inputs','outputs')},
            'module_blocks':manifest.get('module_blocks',[]),
            'buses':buses, 'sources':sources, 'nets':nets, 'sprites':sprites,'markers':markers,'modules':modules,
            'cells':[{'at':list(at),'type':cell.type,'rotation':cell.rotation,'mirrored':cell.mirrored,
                      'net':net_at[at], 'gate':drivers.get(at),
                      'logic_gate':bool(drivers.get(at) and drivers[at]['op']!='BUF')}
                     for at,cell in sorted(cells.items())]}


def describe_modules(nets):
    """HDL ownership survives combined physical packing; sheets use logic edges."""
    by_id={n['id']:n for n in nets}
    def group(n):
        driver=n['driver']
        if not driver or driver['id'].startswith('port:'):return None
        return driver['scope'].split('.')[0]
    groups=sorted({group(n) for n in nets}-{None})
    modules=[]
    for name in groups:
        own=[n for n in nets if group(n)==name];ids={n['id'] for n in own}
        inputs=sorted({net for n in own for net in n['inputs'] if net not in ids})
        outputs=sorted({net for n in nets if group(n)!=name for net in n['inputs'] if net in ids})
        parents=sorted({group(by_id[net]) for net in inputs if net in by_id}-{None})
        modules.append({'id':name,'nodes':[n['id'] for n in own],'inputs':inputs,'outputs':outputs,'parents':parents})
    return modules


def render_poster(cells, manifest, path, mode='nets', whole=False):
    data = view_data(cells, manifest)
    bounds=data['bounds'] if whole else (data['core'] or {}).get('bounds')
    if not bounds or bounds.get('min') is None:bounds=data['bounds']
    minx,miny=bounds['min'];maxx,maxy=bounds['max']
    minx-=2;miny-=2;maxx+=2;maxy+=2
    size=34 if whole else 42
    while size>14 and (maxx-minx+1)*size*(maxy-miny+1)*size>12_000_000:size-=2
    left,top=24,56
    width=max(600,left+(maxx-minx+1)*size+24)
    board_bottom=top+(maxy-miny+1)*size
    by_net={net['id']:net for net in data['nets']}
    legend=[{'label':s['label'],'color':by_net[s['net']]['route_color' if mode=='routing' else 'color']} for s in data['sources']]
    legend.extend({'label':m['label'],'color':data['nets'][m['net']]['route_color' if mode=='routing' else 'color']}
                  for m in data['markers'] if m['kind']=='outputs')
    legend_rows=math.ceil(len(legend)/max(1,(width-48)//105))
    height=board_bottom+24+34*legend_rows
    im=Image.new('RGB',(width,height),'#101925');draw=ImageDraw.Draw(im)
    draw.text((24,12),data['top'],font=font(27),fill='#ffffff')
    def pixel(point):return left+(point[0]-minx)*size,top+(point[1]-miny)*size
    for x in range(minx,maxx+2):
        px,_=pixel((x,miny));draw.line((px,top,px,board_bottom),fill='#243447')
    for y in range(miny,maxy+2):
        _,py=pixel((minx,y));draw.line((left,py,width-24,py),fill='#243447')
    source_colors={(source['bus'],source['bit']):source['color'] for source in data['sources']}
    def colors_of(net):
        return [net['route_color'] if mode=='routing' else net['color']]
    drawn=data['cells']+data['markers']
    visible={tuple(cell['at']) for cell in drawn if minx<=cell['at'][0]<=maxx and miny<=cell['at'][1]<=maxy}
    for marker in data['markers']:
        a,b=(marker['at'],marker['contact']) if marker['kind']=='inputs' else (marker['contact'],marker['at'])
        data['nets'][marker['net']]['edges']=data['nets'][marker['net']]['edges']+[[a,b]]
    for net in data['nets']:
        colors=colors_of(net) or ['#818a97']
        for a,b in net['edges']:
            if tuple(a) not in visible or tuple(b) not in visible:continue
            ax,ay=pixel(a);bx,by=pixel(b)
            vx,vy=bx-ax,by-ay;length=max(1,(vx*vx+vy*vy)**.5)
            for j,color in enumerate(colors):
                offset=(j-(len(colors)-1)/2)*1.25 if mode=='routing' else 0
                ox,oy=-vy/length*offset,vx/length*offset
                if max(abs(a[0]-b[0]),abs(a[1]-b[1]))>1:
                    for i in range(0,10,2):
                        draw.line((ax+size/2+ox+vx*i/10,ay+size/2+oy+vy*i/10,
                                   ax+size/2+ox+vx*(i+1)/10,ay+size/2+oy+vy*(i+1)/10),fill=color,width=1 if mode=='routing' else 2)
                else:draw.line((ax+size/2+ox,ay+size/2+oy,bx+size/2+ox,by+size/2+oy),fill=color,width=1 if mode=='routing' else 3)
    sprites={}
    for cell in drawn:
        point=tuple(cell['at'])
        if point not in visible:continue
        px,py=pixel(point);net=data['nets'][cell['net']]
        colors=colors_of(net)
        colors=colors or ['#818a97']
        logic_gate=cell.get('logic_gate',False)
        factor=.75 if logic_gate or cell.get('kind') else .38
        for i,color in enumerate(colors):
            fill=tuple(round(int(color[j:j+2],16)*factor) for j in (1,3,5))
            draw.rectangle((px+2+i*(size-4)/len(colors),py+2,px+2+(i+1)*(size-4)/len(colors),py+size-2),fill=fill)
        dim=not logic_gate and not cell.get('kind')
        token=cell['type'],cell['rotation'],cell['mirrored'],dim
        if token not in sprites:
            sprite=Image.open(ROOT/f"assets/sprites/arrow{cell['type']}.png").convert('RGBA')
            if dim:sprite=ImageEnhance.Brightness(sprite).enhance(.8)
            if cell['mirrored']:sprite=ImageOps.mirror(sprite)
            sprites[token]=sprite.rotate(-90*cell['rotation']).resize((size-10,size-10),Image.Resampling.LANCZOS)
        im.paste(sprites[token],(px+5,py+5),sprites[token])
        if logic_gate:
            draw.rectangle((px+2,py+2,px+size-2,py+size-2),outline='#ffffff',width=1)
    for block in data['module_blocks']:
        x,y=pixel(block['at']);w,h=block['width']*size,block['height']*size
        draw.rectangle((x+1,y+1,x+w-1,y+h-1),outline='#ffffff',width=1)
    y=board_bottom+18
    if legend:
        x=24
        for source in legend:
            if x+100>width-24:x=24;y+=34
            draw.rectangle((x,y+4,x+18,y+22),fill=source['color'])
            draw.text((x+26,y),source['label'],font=font(17),fill='#ffffff');x+=105
    im.save(path)


def export_views(cells, manifest, folder, stem):
    data=view_data(cells,manifest)
    template=(ROOT/'assets/circuit_view.html').read_text(encoding='utf-8')
    payload=json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    (folder/f'{stem}.viewer.html').write_text(template.replace('__MAP_DATA__',payload),encoding='utf-8')
    render_poster(cells,manifest,folder/f'{stem}.signals.preview.png')
    render_poster(cells,manifest,folder/f'{stem}.routing.preview.png','routing')
    render_poster(cells,manifest,folder/f'{stem}.routing.full.preview.png','routing',whole=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Цветные PNG и HTML из сохранения и build.json')
    parser.add_argument('save',type=Path);parser.add_argument('manifest',type=Path)
    parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads(args.manifest.read_text(encoding='utf-8'))
    export_views(read_map(args.save),manifest,args.out,manifest['top'])
