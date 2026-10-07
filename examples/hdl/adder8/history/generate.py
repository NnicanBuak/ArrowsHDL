"""Render complete compiler iterations from their real, frozen cell maps."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from PIL import Image,ImageDraw

HERE=Path(__file__).resolve().parent
PROJECT=HERE.parents[3]
sys.path.insert(0,str(PROJECT/'src'))
from arrow_layout import bounds_of,depth_of,edges
from mapdata import map_hash,read_map,write_json,write_map
from map_preview import font
from test_harness import run_vectors

VERSIONS=[
    {'stem':'v1_sparse','title':'1. Длинные шины','expected':(30393,793,269,3778),
     'method':'Каждому сигналу — отдельная шина; элементы стоят далеко друг от друга.'},
    {'stem':'v2_free','title':'2. Свободное размещение','expected':(473,43,38,128),'snapshot':'free_v2.py',
     'method':'Перестановки сближают связанные узлы; A* ищет короткие провода. Порты разбросаны.'},
    {'stem':'v3_buses','title':'3. Упорядоченные шины','expected':(623,36,34,93),'snapshot':'buses_v3.py',
     'method':'Биты портов собраны в шины; A* перестраивает трассы и учитывает критические цепочки.'},
    {'stem':'v4_native','title':'4. Компактные разряды','expected':(58,18,4,20),
     'method':'Пять булевых элементов разряда заменены двумя игровыми; перенос идёт к соседу.'},
]
EXAMPLES=[(0,0,0),(1,1,0),(127,1,0),(255,0,1),(255,255,0),(255,255,1),(85,170,0),(85,170,1)]


def load_versions(rebuild=False):
    logic=HERE/'adder8.logic.json'
    digest=hashlib.sha256(logic.read_bytes()).hexdigest()
    graph=json.loads(logic.read_text(encoding='utf-8'))
    vectors=[{'inputs':{'a':a,'b':b,'cin':c},'expect':{'sum':(a+b+c)&255,'cout':(a+b+c)>>8}} for a,b,c in EXAMPLES]
    results=[]
    for version in VERSIONS:
        stem=version['stem']
        if rebuild and 'snapshot' in version:
            spec=importlib.util.spec_from_file_location(stem,HERE/version['snapshot'])
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            cells,meta=module.place_compact(graph)
            meta['logic_sha256']=digest
            write_map(HERE,stem,cells);write_json(HERE/f'{stem}.build.json',meta)
        cells=read_map(HERE/f'{stem}.map.json')
        meta=json.loads((HERE/f'{stem}.build.json').read_text(encoding='utf-8'))
        assert cells==read_map(HERE/f'{stem}.save.txt')
        assert meta['map_hash']==map_hash(cells) and meta['logic_sha256']==digest
        bounds=bounds_of(cells)
        actual=(len(cells),bounds['width'],bounds['height'],depth_of(cells)+2)
        if actual!=version['expected']:raise ValueError(f'{stem}: expected {version["expected"]}, got {actual}')
        assert not any(c.type in (22,23) for c in cells.values())
        _,report=run_vectors(cells,meta,vectors,HERE,stem,compressed=True)
        if not report['passed']:raise ValueError(f'{stem}: physical test failed')
        results.append((version,cells,meta,report))
    return results


def board(cells,meta):
    b=bounds_of(cells)
    size=12 if b['width']>200 else 30
    image=Image.new('RGB',((b['width']+2)*size,(b['height']+2)*size),'white')
    draw=ImageDraw.Draw(image)
    for x in range(0,image.width,size):draw.line((x,0,x,image.height),fill='#edf1f6')
    for y in range(0,image.height,size):draw.line((0,y,image.width,y),fill='#edf1f6')
    gates={tuple(g['at']) for g in meta['gate_labels']}
    inputs={tuple(e['contact']) for es in meta['inputs'].values() for e in es}
    outputs={tuple(e['contact']) for es in meta['outputs'].values() for e in es}
    sprites={}
    for (x,y),cell in cells.items():
        px,py=(x-b['min'][0]+1)*size,(y-b['min'][1]+1)*size
        key=(x,y)
        color='#d9f7e5' if key in inputs else '#fff0b7' if key in outputs else '#eee7ff' if key in gates else '#e3f1ff' if cell.type in (10,11,12,13,14) else '#fafbfc'
        draw.rectangle((px+1,py+1,px+size-1,py+size-1),fill=color)
        token=cell.type,cell.rotation,cell.mirrored
        if token not in sprites:
            sprite=Image.open(PROJECT/f'assets/sprites/arrow{cell.type}.png').convert('RGBA')
            if cell.mirrored:sprite=sprite.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            sprites[token]=sprite.rotate(-90*cell.rotation).resize((size-2,size-2),Image.Resampling.LANCZOS)
        image.paste(sprites[token],(px+1,py+1),sprites[token])
    return image


def metrics(meta):
    b=meta['bounds']
    count=f"{meta['cells']:,}".replace(',',' ')
    return f"{count} стрелок · поле {b['width']}×{b['height']} · проверка через {meta['settle_ticks']} тактов"


def overview(cells,meta,width,height):
    """Readable complete physical connections when individual cells are subpixel."""
    b=bounds_of(cells)
    image=Image.new('RGB',(width,height),'white');draw=ImageDraw.Draw(image)
    sx,sy=width/(b['width']+2),height/(b['height']+2)
    def pixel(p):return ((p[0]-b['min'][0]+1.5)*sx,(p[1]-b['min'][1]+1.5)*sy)
    for p,targets in edges(cells).items():
        for q in targets:
            draw.line((*pixel(p),*pixel(q)),fill='#4158b0' if cells[p].type in (10,11,12,13,14) else '#74312e',width=1)
    markers=[(tuple(g['at']),'#7952b3') for g in meta['gate_labels']]
    markers += [(tuple(e['contact']),color) for side,color in (('inputs','#16804c'),('outputs','#af7b00')) for es in meta[side].values() for e in es]
    for p,color in markers:
        x,y=pixel(p);draw.rectangle((x-1,y-1,x+1,y+1),fill=color)
    return image


def wrap(draw,text,width,size):
    lines=[];line=''
    for word in text.split():
        trial=f'{line} {word}'.strip()
        if line and draw.textlength(trial,font=font(size))>width:lines.append(line);line=word
        else:line=trial
    return lines+[line]


def render_all(results):
    card_w,card_h,gap,margin=1160,980,28,36
    image=Image.new('RGB',(2*card_w+gap+2*margin,2*card_h+gap+2*margin+200),'#f0f4fa')
    draw=ImageDraw.Draw(image)
    draw.text((margin,22),'Как менялся 8-битный сумматор ArrowsHDL',font=font(38),fill='#142237')
    draw.text((margin,76),'Один Verilog и один исходный граф Yosys. Показаны полные обычные карты без Source/Target.',font=font(22),fill='#526278')
    stats=[]
    for i,(version,cells,meta,report) in enumerate(results):
        x=margin+(i%2)*(card_w+gap);y=128+(i//2)*(card_h+gap)
        draw.rounded_rectangle((x,y,x+card_w,y+card_h),radius=18,fill='white',outline='#ccd6e4',width=2)
        draw.text((x+24,y+18),version['title'],font=font(30),fill='#142237')
        draw.text((x+24,y+62),metrics(meta),font=font(23),fill='#526278')
        field=board(cells,meta)
        field.save(HERE/f"{version['stem']}.board.png")
        scale=min((card_w-48)/field.width,760/field.height,1.8)
        fitted=field.resize((round(field.width*scale),round(field.height*scale)),Image.Resampling.LANCZOS)
        if meta['bounds']['width']>200:
            fitted=overview(cells,meta,fitted.width,fitted.height)
        px=x+(card_w-fitted.width)//2;py=y+104+(760-fitted.height)//2
        image.paste(fitted,(px,py))
        draw.rectangle((px,py,px+fitted.width,py+fitted.height),outline='#ccd6e4')
        for n,line in enumerate(wrap(draw,version['method'],card_w-48,22)):
            draw.text((x+24,y+884+n*29),line,font=font(22),fill='#253b57')
        single=Image.new('RGB',(max(950,field.width+48),field.height+172),'#f6f8fb')
        single_draw=ImageDraw.Draw(single)
        single_draw.text((24,16),version['title'],font=font(30),fill='#142237')
        single_draw.text((24,58),metrics(meta),font=font(21),fill='#526278')
        single.paste(field,((single.width-field.width)//2,102))
        single_draw.text((24,single.height-46),'Зелёный — входы; жёлтый — выходы; фиолетовый — логические элементы.',font=font(19),fill='#526278')
        single.save(HERE/f"{version['stem']}.preview.png")
        stats.append({'version':i+1,'title':version['title'],'cells':meta['cells'],'bounds':meta['bounds'],
                      'settle_ticks':meta['settle_ticks'],'map_hash':meta['map_hash'],'logic_sha256':meta['logic_sha256'],
                      'map':f"{version['stem']}.map.json",'image':f"{version['stem']}.preview.png",
                      'test_passed':report['passed'],'checked_samples':report['checked_samples'],
                      'recovered_from_history':'snapshot' in version})
    footer=128+2*card_h+gap+18
    draw.text((margin,footer),'Масштаб панелей различается. Для большой первой карты показаны физические соединения; стрелки доступны в полном PNG.',font=font(21),fill='#526278')
    draw.text((margin,footer+34),'Последняя настройка: ядро без ввода/вывода — 23 стрелки, 15×2, 15 тактов; эта схема осталась прежней.',font=font(21),fill='#253b57')
    image.save(HERE/'iterations.png')
    write_json(HERE/'iterations.json',{'schema':1,'versions':stats,'same_original_logic_graph':True,
                                   'comparison_scope':'production maps, excluding Source/Target','different_panel_scales':True})


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--rebuild',action='store_true',help='rebuild versions 2 and 3 using recovered compiler snapshots')
    args=parser.parse_args()
    render_all(load_versions(args.rebuild))
    print(HERE/'iterations.png')
