"""Render observed physical cells: no gate captions, only title and color legend."""
import json
from PIL import Image,ImageDraw,ImageOps,ImageEnhance
from build import HERE,PROJECT
from mapdata import read_map,map_hash
from map_preview import font


def render(value):
    folder=HERE/'build/presets'
    cells=read_map(folder/f'digit{value}.save.txt')
    record=json.loads((folder/f'digit{value}.states.json').read_text())
    assert map_hash(cells)==record['map_hash']
    active={tuple(p['at']) for p in record['states'] if p['values'][0]}
    size=26;left=24;top=50
    minx,miny=min(x for x,y in cells)-1,min(y for x,y in cells)-1
    maxx,maxy=max(x for x,y in cells)+1,max(y for x,y in cells)+1
    width=max(460,(maxx-minx+1)*size+48);bottom=top+(maxy-miny+1)*size
    im=Image.new('RGB',(width,bottom+58),'#101925');draw=ImageDraw.Draw(im)
    draw.text((24,8),f'Digit {value}',font=font(26),fill='white')
    def pixel(p):return left+(p[0]-minx)*size,top+(p[1]-miny)*size
    for x in range(minx,maxx+2):
        px,_=pixel((x,miny));draw.line((px,top,px,bottom),fill='#243447')
    for y in range(miny,maxy+2):
        _,py=pixel((minx,y));draw.line((left,py,width-24,py),fill='#243447')
    sprites={}
    for p,c in cells.items():
        px,py=pixel(p);on=p in active
        logic=c.type in (3,5,15,16,17,19)
        fill='#9c161c' if on else '#312944' if logic else '#18303b'
        draw.rectangle((px+1,py+1,px+size-1,py+size-1),fill=fill)
        token=c.type,c.rotation,c.mirrored,on
        if token not in sprites:
            sprite=Image.open(PROJECT/f'assets/sprites/arrow{c.type}.png').convert('RGBA')
            if c.mirrored:sprite=ImageOps.mirror(sprite)
            if not on:sprite=ImageEnhance.Brightness(sprite).enhance(.7)
            sprites[token]=sprite.rotate(-90*c.rotation).resize((size-6,size-6),Image.Resampling.LANCZOS)
        im.paste(sprites[token],(px+3,py+3),sprites[token])
        if logic:draw.rectangle((px+1,py+1,px+size-1,py+size-1),outline='white',width=1)
    for x,label,color in ((24,'On','#cf2831'),(135,'Wire','#426f83'),(260,'Logic','#ac8bea')):
        draw.rectangle((x,bottom+19,x+15,bottom+34),fill=color)
        draw.text((x+23,bottom+13),label,font=font(16),fill='white')
    im.save(folder/f'digit{value}.preview.png')
    # The digit crop keeps the complete display block; it contains actual sampled arrows.
    region=im.crop((left,top,left+(maxx-minx+1)*size,top+(18-miny)*size))
    return region


def main():
    previews=[render(v) for v in range(8)]
    w=max(p.width for p in previews);h=max(p.height for p in previews)
    image=Image.new('RGB',(4*w+48,2*h+112),'#101925');draw=ImageDraw.Draw(image)
    draw.text((24,10),'Digit3',font=font(27),fill='white')
    for v,im in enumerate(previews):image.paste(im,(24+(v%4)*w,54+(v//4)*h))
    y=2*h+74
    for x,label,color in ((24,'On','#cf2831'),(135,'Wire','#426f83'),(260,'Logic','#ac8bea')):
        draw.rectangle((x,y+5,x+15,y+20),fill=color)
        draw.text((x+23,y),label,font=font(16),fill='white')
    image.save(HERE/'build/digit3.preview.png')


if __name__=='__main__':main()
