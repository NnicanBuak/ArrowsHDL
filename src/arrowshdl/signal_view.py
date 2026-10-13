"""Portable coloured views of the actual exported arrow map.

Electrical nets change at operators. Input ancestry is a separate layer;
neither layer changes cell types, directions, or the game save.
"""
import argparse
import base64
import colorsys
import json
import math
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps, ImageEnhance

from arrowshdl.arrowasm import MapError
from arrowshdl.arrow_layout import bounds_of
from arrowshdl.mapdata import map_hash, read_map
from arrowshdl.map_preview import font
from arrowshdl.test_harness import add_fixture

from arrowshdl.resources import SPRITES, TEMPLATES
ROOT = Path(__file__).resolve().parents[2]


def net_color(index):
    rgb = colorsys.hls_to_rgb((index * 0.61803398875) % 1, .72, 1)
    return '#'+''.join(f'{round(channel*255):02x}' for channel in rgb)


def signal_tile_color(color):
    """Lighten a route colour for its arrow tile while retaining its hue."""
    rgb=[int(color[index:index+2],16) for index in (1,3,5)]
    return '#'+''.join(f'{round(255*.68+channel*.32):02x}' for channel in rgb)


def signal_sprite_color(color):
    """Keep route arrow glyphs darker than their tinted tile backgrounds."""
    return tuple(round(int(color[index:index+2],16)*.72) for index in (1,3,5))


def view_data(cells, manifest):
    if map_hash(cells) != manifest['map_hash']:
        raise MapError('Signal preview: map does not match metadata')
    signals = manifest.get('signals')
    if not signals:
        raise MapError('Signal preview: signal description is missing')
    nets = [dict(net, color=net_color(i)) for i,net in enumerate(signals['nets'])]
    buses = signals['input_buses']
    sources=[{'id':f"{bus['name']}:{bit}",'bus':bus['name'],'bit':bit,
              'label':f"{bus['name']}[{bit}]"} for bus in buses for bit in bus['bits']]
    for i,source in enumerate(sources):source['color']=net_color(len(nets)+2+i)
    net_at = {tuple(point):i for i,net in enumerate(nets) for point in net['cells']}
    if sum(len(net['cells']) for net in nets)!=len(cells) or set(net_at) != set(cells):
        raise MapError('Each arrow must belong to exactly one signal')
    for source in sources:
        entry=next(e for e in manifest['inputs'][source['bus']] if e['index']==source['bit'])
        source['net']=nets[net_at[tuple(entry['contact'])]]['id']
    by_net={n['id']:n for n in nets}
    source_colours={s['net']:s['color'] for s in sources}
    net_order={net['id']:i for i,net in enumerate(nets)}
    def route_colour(net):
        if 'route_color' not in net:
            driver=net['driver']
            if driver and driver['op']=='BUF':
                net['route_color']=route_colour(by_net[net['inputs'][0]])
            else:
                color=source_colours.get(net['id'],net['color'])
                if driver:
                    incoming={route_colour(by_net[source]) for source in net['inputs'] if source in by_net}
                    color_index=len(nets)+len(sources)+net_order[net['id']]
                    while color in incoming:
                        color=net_color(color_index)
                        color_index+=1
                net['route_color']=color
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
        asset=(SPRITES / f'arrow{type_id}.png').read_bytes()
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
    if mode == 'logical':
        return render_logical_poster(cells,manifest,path,whole)
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
            sprite=Image.open(SPRITES/f"arrow{cell['type']}.png").convert('RGBA')
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


def logical_view_data(cells,manifest):
    """Use exact signal metadata when present; otherwise trace labelled gates on the placed map."""
    if manifest.get('signals'):
        return view_data(cells,manifest)
    if map_hash(cells)!=manifest.get('map_hash'):
        raise MapError('Logical preview: map does not match metadata')
    from arrowshdl.arrow_layout import edges
    if not manifest.get('gate_labels'):
        raise MapError('Logical preview: signal metadata or logical gate labels are required')

    links=edges(cells)
    reverse={p:[] for p in cells}
    for p,targets in links.items():
        for q in targets:reverse[q].append(p)
    gate_labels={tuple(gate['at']):gate for gate in manifest['gate_labels']}
    logical_gates={p:gate for p,gate in gate_labels.items() if gate.get('op')!='BUF' and p in cells}
    input_sources=[];inputs_at=defaultdict(list)
    for name,entries in manifest.get('inputs',{}).items():
        for entry in entries:
            point=tuple(entry['contact']);source=f'input:{name}:{entry["index"]}'
            if point in cells:
                input_sources.append((source,point))
                inputs_at[point].append(source)
    constants={p:f'constant:{p[0]},{p[1]}' for p,cell in cells.items() if cell.type==2}
    gate_ids={p:f'gate:{gate.get("scope","core")}:{gate.get("id",p)}' for p,gate in logical_gates.items()}

    gate_inputs={}
    for at,gate_id in gate_ids.items():
        found=set();todo=list(reverse[at]);seen=set()
        while todo:
            point=todo.pop()
            if point in seen:continue
            seen.add(point)
            if point in gate_ids:
                found.add(gate_ids[point]);continue
            if point in inputs_at:
                found.update(inputs_at[point]);continue
            if point in constants:
                found.add(constants[point]);continue
            todo.extend(reverse[point])
        gate_inputs[gate_id]=found

    colors={}
    input_colors={source:net_color(i) for i,(source,_) in enumerate(input_sources)}
    colors.update(input_colors)
    constant_ids=sorted(constants.values())
    colors.update({source:net_color(len(colors)+i) for i,source in enumerate(constant_ids)})
    pending=set(gate_ids.values());gate_order=[]
    while pending:
        ready=sorted(gate for gate in pending if not (gate_inputs[gate]&pending))
        if not ready:ready=sorted(pending)  # Keep previews available for stateful or cyclic maps.
        for gate in ready:
            incoming={colors[source] for source in gate_inputs[gate] if source in colors}
            index=len(input_sources)+len(constant_ids)+len(gate_order)
            color=net_color(index)
            while color in incoming:
                index+=1;color=net_color(index)
            colors[gate]=color;gate_order.append(gate)
        pending.difference_update(ready)

    seeds=list(input_sources)
    seeds.extend((source,point) for point,source in sorted(constants.items()))
    by_gate_id={source:point for point,source in gate_ids.items()}
    seeds.extend((source,by_gate_id[source]) for source in gate_order)
    edges_by_source={source:set() for source,_ in seeds}
    owner={}
    for source,start in seeds:
        todo=[start];seen=set()
        while todo:
            point=todo.pop()
            if point in seen or point not in cells:continue
            if point in gate_ids and point!=start:continue
            if point in inputs_at and point!=start:continue
            if point in owner and owner[point]!=source:continue
            seen.add(point);owner[point]=source
            for target in links[point]:
                edges_by_source[source].add((point,target))
                if target in gate_ids or target in inputs_at:continue
                if target not in owner or owner[target]==source:todo.append(target)

    net_order={source:index for index,(source,_) in enumerate(seeds)}
    nets=[{'id':source,'route_color':colors[source],
           'edges':[[list(a),list(b)] for a,b in sorted(edges_by_source[source])]} for source,_ in seeds]
    display=add_fixture(cells,manifest)
    markers=[]
    for kind in ('inputs','outputs'):
        for name,entries in manifest.get(kind,{}).items():
            for entry in entries:
                at=tuple(entry['fixture']);contact=tuple(entry['contact'])
                source=(inputs_at.get(contact) or [owner.get(contact)]) [0]
                if source not in net_order:
                    if not nets:
                        source='untraced';net_order[source]=len(nets)
                        nets.append({'id':source,'route_color':'#64748b','edges':[]})
                    else:source=nets[0]['id']
                cell=display[at]
                markers.append({'at':list(at),'type':cell.type,'rotation':cell.rotation,'mirrored':cell.mirrored,
                                'net':net_order[source],'kind':kind,'source':f"{name}:{entry['index']}",
                                'label':f"{name}[{entry['index']}]",'contact':entry['contact'],'gate':None})
    drivers={tuple(gate['at']):gate for gate in manifest['gate_labels']}
    return {'top':manifest.get('top','Logic Arrows'),'hash':manifest['map_hash'],
            'core':manifest.get('logic_core'),'bounds':bounds_of(display),
            'production_bounds':manifest.get('bounds',bounds_of(cells)),
            'ports':{kind:manifest.get(kind,{}) for kind in ('inputs','outputs')},
            'module_blocks':manifest.get('module_blocks',[]),'buses':[],'sources':[],'nets':nets,
            'markers':markers,'modules':[],
            'cells':[{'at':list(at),'type':cell.type,'rotation':cell.rotation,'mirrored':cell.mirrored,
                      'net':net_order.get(owner.get(at),0),'gate':drivers.get(at),
                      'logic_gate':bool(at in logical_gates)} for at,cell in sorted(cells.items())]}


def render_logical_poster(cells, manifest, path, whole=False):
    """Show the logic graph as a thin, coloured overlay on the real cell map."""
    data=logical_view_data(cells,manifest)
    bounds=data['bounds'] if whole else (data['core'] or {}).get('bounds')
    if not bounds or bounds.get('min') is None:bounds=data['bounds']
    minx,miny=bounds['min'];maxx,maxy=bounds['max']
    minx-=2;miny-=2;maxx+=2;maxy+=2
    cells_w,cells_h=maxx-minx+1,maxy-miny+1
    size=34
    while size>2 and cells_w*cells_h*size*size>8_000_000:size-=2
    labels=logical_port_labels(data['markers'])
    label_font=font(14)
    label_width=max((label_font.getlength(item['label']) for item in labels),default=0)
    label_height=max((label_font.getbbox(item['label'])[3]-label_font.getbbox(item['label'])[1]
                      for item in labels),default=0)
    left_gutter=math.ceil(label_width+16) if any(item['side']=='left' for item in labels) else 0
    right_gutter=math.ceil(label_width+16) if any(item['side']=='right' for item in labels) else 0
    top_gutter=label_height+18 if any(item['side']=='top' for item in labels) else 0
    bottom_gutter=label_height+18 if any(item['side']=='bottom' for item in labels) else 0
    left=24+left_gutter
    top=56+top_gutter
    board_right=left+cells_w*size
    board_bottom=top+cells_h*size
    width=max(600,24+left_gutter+cells_w*size+right_gutter+24)
    height=board_bottom+24+bottom_gutter
    if width*height>40_000_000:
        raise MapError('Map is too large for logical preview PNG')
    im=Image.new('RGB',(width,height),'#f6f8fb')
    draw=ImageDraw.Draw(im)
    def pixel(point):return left+(point[0]-minx)*size,top+(point[1]-miny)*size
    draw.rectangle((left,top,board_right,board_bottom),fill='#ffffff')
    for x in range(minx,maxx+2):
        px,_=pixel((x,miny));draw.line((px,top,px,board_bottom),fill='#edf1f6')
    for y in range(miny,maxy+2):
        _,py=pixel((minx,y));draw.line((left,py,board_right,py),fill='#edf1f6')

    drawn=data['cells']+data['markers']
    visible={tuple(cell['at']) for cell in drawn
             if minx<=cell['at'][0]<=maxx and miny<=cell['at'][1]<=maxy}
    logic_cells={tuple(cell['at']) for cell in data['cells'] if cell.get('logic_gate')}
    for marker in data['markers']:
        a,b=(marker['at'],marker['contact']) if marker['kind']=='inputs' else (marker['contact'],marker['at'])
        data['nets'][marker['net']]['edges'].append([a,b])

    sprites={}
    sprite_size=max(1,size-10)
    for cell in drawn:
        point=tuple(cell['at'])
        if point not in visible:continue
        px,py=pixel(point)
        logic_gate=cell.get('logic_gate',False)
        kind=cell.get('kind')
        route_color=data['nets'][cell['net']]['route_color']
        if kind=='inputs':fill='#d9f4e7'
        elif kind=='outputs':fill='#fff0c2'
        elif logic_gate:fill='#eee7ff'
        else:fill=signal_tile_color(route_color)
        draw.rectangle((px+1,py+1,px+size-1,py+size-1),fill=fill)
        tint=None if logic_gate or kind else route_color
        token=cell['type'],cell['rotation'],cell['mirrored'],sprite_size,tint
        if token not in sprites:
            sprite=Image.open(SPRITES/f"arrow{cell['type']}.png").convert('RGBA')
            if cell['mirrored']:sprite=ImageOps.mirror(sprite)
            sprites[token]=sprite.rotate(-90*cell['rotation']).resize(
                (sprite_size,sprite_size),Image.Resampling.LANCZOS)
            if tint:
                sprite=sprites[token]
                alpha=sprite.getchannel('A')
                tinted=Image.new('RGBA',sprite.size,(*signal_sprite_color(tint),0))
                tinted.putalpha(alpha)
                sprites[token]=tinted
        sprite=sprites[token]
        im.paste(sprite,(px+(size-sprite_size)//2,py+(size-sprite_size)//2),sprite)

    def draw_edge(a,b,color,width):
        ax,ay=pixel(a);bx,by=pixel(b)
        start=(ax+size/2,ay+size/2);end=(bx+size/2,by+size/2)
        draw.line((*start,*end),fill=color,width=width)

    for net in data['nets']:
        for a,b in net['edges']:
            if (tuple(a) in visible and tuple(b) in visible and
                    not edge_crosses_cells(a,b,logic_cells)):
                draw_edge(a,b,'#46515f',max(2,size//14))
    for net in data['nets']:
        for a,b in net['edges']:
            if (tuple(a) in visible and tuple(b) in visible and
                    not edge_crosses_cells(a,b,logic_cells)):
                draw_edge(a,b,net['route_color'],max(1,size//32))

    for cell in drawn:
        point=tuple(cell['at'])
        if point not in visible:continue
        px,py=pixel(point)
        if cell.get('logic_gate'):
            draw.rectangle((px+1,py+1,px+size-1,py+size-1),outline='#6741b8',width=max(1,size//20))
        if kind:=cell.get('kind'):
            color='#16804c' if kind=='inputs' else '#a15b00'
            draw.rectangle((px+1,py+1,px+size-1,py+size-1),outline=color,width=max(1,size//16))
    for block in data['module_blocks']:
        x,y=pixel(block['at']);w,h=block['width']*size,block['height']*size
        draw.rectangle((x+1,y+1,x+w-1,y+h-1),outline='#7043bf',width=max(2,size//14))
    draw.rectangle((left,top,board_right,board_bottom),outline='#526174',width=1)
    draw.text((24,12),data['top'],font=font(27),fill='#142237')
    for item in labels:
        marker=item['marker'];px,py=pixel(marker['at'])
        text_color='#16804c' if item['kind']=='inputs' else '#a15b00'
        if item['side']=='left':
            draw.text((left-8,py+size/2),item['label'],font=label_font,fill=text_color,anchor='rm')
        elif item['side']=='right':
            draw.text((board_right+8,py+size/2),item['label'],font=label_font,fill=text_color,anchor='lm')
        elif item['side']=='top':
            draw.text((px+size/2,top-8),item['label'],font=label_font,fill=text_color,anchor='mb')
        else:
            draw.text((px+size/2,board_bottom+8),item['label'],font=label_font,fill=text_color,anchor='mt')
    im.save(path)


def logical_port_labels(markers):
    """Return one outward-facing label for every physical input/output fixture."""
    labels=[]
    for marker in markers:
        x,y=marker['at'];cx,cy=marker['contact']
        if abs(x-cx)>=abs(y-cy) and x!=cx:
            side='left' if x<cx else 'right'
        else:
            side='top' if y<cy else 'bottom'
        labels.append({'marker':marker,'label':marker['label'],'kind':marker['kind'],'side':side})
    return labels


def edge_crosses_cells(a,b,protected_cells):
    """True when a route segment touches a protected logical operator cell."""
    ax,ay=a;bx,by=b
    minx=math.ceil(min(ax,bx)-.5);maxx=math.floor(max(ax,bx)+.5)
    miny=math.ceil(min(ay,by)-.5);maxy=math.floor(max(ay,by)+.5)
    dx,dy=bx-ax,by-ay
    for x in range(minx,maxx+1):
        for y in range(miny,maxy+1):
            if (x,y) not in protected_cells:continue
            enter,leave=0.0,1.0
            for origin,delta,low,high in ((ax,dx,x-.5,x+.5),(ay,dy,y-.5,y+.5)):
                if delta==0:
                    if origin<low or origin>high:
                        enter,leave=1.0,0.0
                        break
                else:
                    first=(low-origin)/delta;last=(high-origin)/delta
                    if first>last:first,last=last,first
                    enter=max(enter,first);leave=min(leave,last)
                    if enter>leave:break
            if enter<=leave:return True
    return False


def export_views(cells, manifest, folder, stem):
    data=view_data(cells,manifest)
    template=(TEMPLATES/'circuit_view.html').read_text(encoding='utf-8')
    payload=json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    (folder/f'{stem}.viewer.html').write_text(template.replace('__MAP_DATA__',payload),encoding='utf-8')
    render_poster(cells,manifest,folder/f'{stem}.signals.preview.png')
    render_poster(cells,manifest,folder/f'{stem}.routing.preview.png','routing')
    render_poster(cells,manifest,folder/f'{stem}.routing.full.preview.png','routing',whole=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Render signal PNG and HTML from a game save and metadata')
    parser.add_argument('save',type=Path);parser.add_argument('manifest',type=Path)
    parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads(args.manifest.read_text(encoding='utf-8'))
    export_views(read_map(args.save),manifest,args.out,manifest['top'])
