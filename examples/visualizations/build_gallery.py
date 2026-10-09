"""Preview current saved HDL circuits without changing or recompiling maps."""
import json
import shutil
from pathlib import Path
import sys
from PIL import Image, ImageDraw, ImageEnhance, ImageOps

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(PROJECT/'src'))
from mapdata import read_map, map_hash, write_json
from map_preview import font
from signal_view import export_views

EXAMPLES = [
    ('digit3', '../digit3/build', 'digit3'),
    ('bcd4', 'binary_to_bcd/build/bcd4', 'bcd4'),
    ('mul4_tree', 'candidates/mul4/build', 'mul4'),
    ('composed_logic', 'composed_logic/build', 'composed_logic'),
    ('mux2', 'multiplexer/mux2/build', 'mux2'),
    ('mux4', 'multiplexer/mux4/build', 'mux4'),
    ('mux8', 'multiplexer/mux8/build', 'mux8'),
    ('adder8', 'adder8/build', 'adder8'),
    ('half_adder', 'half_adder/build', 'half_adder'),
    ('full_adder', 'full_adder/build', 'full_adder'),
    ('mul2_flat', 'multiplier/mul2/build', 'mul2'),
    ('mul3_flat', 'multiplier/mul3/build', 'mul3'),
    ('mul4_flat', 'multiplier/mul4/build', 'mul4'),
]


def legacy_preview(cells, meta, path):
    """Older maps lack net provenance; show actual arrows with a type legend."""
    gates = {tuple(g['at']) for g in meta['gate_labels'] if g['op'] != 'BUF'}
    markers = {tuple(e['fixture']): (22 if kind == 'inputs' else 23, e.get('rotation', 0))
               for kind in ('inputs', 'outputs') for entries in meta[kind].values() for e in entries}
    points = set(cells) | markers.keys()
    minx, miny = min(p[0] for p in points)-2, min(p[1] for p in points)-2
    maxx, maxy = max(p[0] for p in points)+2, max(p[1] for p in points)+2
    size = 30
    while (maxx-minx+1)*(maxy-miny+1)*size*size > 12_000_000:
        size -= 1
    width = max(700, (maxx-minx+1)*size+48)
    bottom = 56+(maxy-miny+1)*size
    im = Image.new('RGB', (width, bottom+66), '#101925')
    draw = ImageDraw.Draw(im)
    draw.text((24,12),meta['top'],font=font(27),fill='white')
    def pixel(p):return 24+(p[0]-minx)*size,56+(p[1]-miny)*size
    for x in range(minx,maxx+2):
        px,_=pixel((x,miny));draw.line((px,56,px,bottom),fill='#243447')
    for y in range(miny,maxy+2):
        _,py=pixel((minx,y));draw.line((24,py,width-24,py),fill='#243447')
    colors={'Wire':'#7566ae','Gate':'#c298ef','Jump':'#60bed3','Source':'#62ce9f','Target':'#efcf68','Constant':'#eaa269'}
    sprites={}
    actual=[(p,c.type,c.rotation,c.mirrored) for p,c in cells.items()]
    actual += [(p,t,r,False) for p,(t,r) in markers.items() if p not in cells]
    for p,t,r,mirrored in actual:
        category='Gate' if p in gates else 'Source' if t==22 else 'Target' if t==23 else 'Constant' if t==2 else 'Jump' if t in (10,11,12,13,14) else 'Wire'
        px,py=pixel(p);color=colors[category]
        dim=p not in gates and category in ('Wire','Jump')
        factor=.35 if dim else .75
        fill=tuple(round(int(color[k:k+2],16)*factor) for k in (1,3,5))
        draw.rectangle((px+2,py+2,px+size-2,py+size-2),fill=fill)
        token=t,r,mirrored,dim
        if token not in sprites:
            sprite=Image.open(PROJECT/f'assets/sprites/arrow{t}.png').convert('RGBA')
            if mirrored:sprite=ImageOps.mirror(sprite)
            if dim:sprite=ImageEnhance.Brightness(sprite).enhance(.8)
            sprites[token]=sprite.rotate(-90*r).resize((size-8,size-8),Image.Resampling.LANCZOS)
        im.paste(sprites[token],(px+4,py+4),sprites[token])
        if p in gates:draw.rectangle((px+2,py+2,px+size-2,py+size-2),outline='white',width=1)
    x=24
    for label,color in colors.items():
        draw.rectangle((x,bottom+22,x+16,bottom+38),fill=color)
        draw.text((x+23,bottom+16),label,font=font(16),fill='white')
        x+=100
    im.save(path)


def main():
    output=HERE/'build';output.mkdir(exist_ok=True)
    records=[];sections=[]
    for name,relative,stem in EXAMPLES:
        source=PROJECT/'examples/hdl'/relative
        cells=read_map(source/f'{stem}.save.txt')
        meta=json.loads((source/f'{stem}.build.json').read_text(encoding='utf-8'))
        assert map_hash(cells)==meta['map_hash'],name
        meta=dict(meta,top=name)
        if meta['layout']=='reused-seven-segment-module':
            image=f'{name}.preview.png';target=f'{name}.full.preview.png'
            shutil.copyfile(source/'digit3.preview.png',output/image)
            shutil.copyfile(source/'presets/digit0.preview.png',output/target)
        elif meta.get('signals'):
            export_views(cells,meta,output,name)
            image=f'{name}.routing.full.preview.png';target=f'{name}.viewer.html'
        else:
            image=f'{name}.preview.png';target=image
            legacy_preview(cells,meta,output/image)
        sections.append(f'<a href="{target}" aria-label="{name}"><img src="{image}" alt="{name}"></a>')
        records.append(dict(name=name,save=str(source/f'{stem}.save.txt'),map_hash=map_hash(cells),cells=len(cells),image=image,interactive=bool(meta.get('signals'))))
    html='''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Circuits</title><style>
body{margin:0;background:#101925}main{max-width:1800px;margin:auto;padding:12px;display:grid;gap:24px}
a{display:block}img{display:block;width:100%;height:auto}a:focus-visible{outline:2px solid white}
</style><main>'''+ '\n'.join(sections)+'</main></html>\n'
    (output/'index.html').write_text(html,encoding='utf-8')
    write_json(output/'gallery.json',records)
    print(f'{len(records)} saved circuits verified and rendered')


if __name__=='__main__':main()
