"""Generate passive labels from an external, versioned bitmap font."""
from copy import deepcopy
import json
from pathlib import Path

from arrowshdl.arrowasm import Cell,MapError
from arrowshdl.arrow_layout import bounds_of
from arrowshdl.manifest import table
from arrowshdl.mapdata import map_hash
from arrowshdl.presentation import port_bits


def text_pixels(font_path,text,size=1):
    if type(size) is not int or size<1:raise MapError('Кегль: целый множитель от 1')
    data=json.loads(Path(font_path).read_text(encoding='utf-8-sig'))
    table(data,{'version','name','height','spacing','space','glyphs','source'},'font')
    if type(data.get('version')) is not int or data['version']!=1:
        raise MapError('Неизвестная версия шрифта')
    height,spacing,space=data.get('height'),data.get('spacing',1),data.get('space',3)
    if any(type(n) is not int or n<1 for n in (height,space)) or type(spacing) is not int or spacing<0:
        raise MapError('Неверные размеры шрифта')
    glyphs=data.get('glyphs')
    if not isinstance(glyphs,dict):raise MapError('font.glyphs: таблица символов')
    for char,rows in glyphs.items():
        if len(char)!=1 or not isinstance(rows,list) or len(rows)!=height or not rows or not isinstance(rows[0],str) or not rows[0]:
            raise MapError('Символ шрифта: одна буква и height строк')
        if any(not isinstance(r,str) or len(r)!=len(rows[0]) or set(r)-set('.#') for r in rows):
            raise MapError('Растр символа: строки одинаковой ширины из . и #')
    lines=text.split('\n')
    width=max((sum(space if c==' ' else len(glyphs[c][0]) if c in glyphs else 0 for c in line)+max(0,len(line)-1)*spacing for line in lines),default=0)
    missing=sorted({c for c in text if c not in glyphs and c not in ' \n'})
    if missing:raise MapError('В шрифте отсутствуют символы: '+''.join(missing))
    total_height=len(lines)*height+max(0,len(lines)-1)*spacing
    if width*total_height*size*size>1000000:raise MapError('Надпись превышает миллион клеток')
    pixels=set()
    for line_index,line in enumerate(lines):
        left=0
        for char in line:
            if char==' ':left+=space+spacing;continue
            rows=glyphs[char]
            for y,row in enumerate(rows):
                for x,value in enumerate(row):
                    if value=='#':
                        for dy in range(size):
                            for dx in range(size):pixels.add(((left+x)*size+dx,(line_index*(height+spacing)+y)*size+dy))
            left+=len(rows[0])+spacing
    return pixels,(width*size,total_height*size)


def attach_labels(cells,manifest,labels,base):
    result,meta=dict(cells),deepcopy(manifest)
    occupied={tuple(e['fixture']) for side in ('inputs','outputs') for es in meta[side].values() for e in es}
    records=[]
    for row in labels:
        reference=row['io'];matches=[]
        for side in ('inputs','outputs'):
            try:matches.append((side,port_bits(meta[side],reference)))
            except MapError:pass
        if len(matches)!=1:raise MapError(f'Подпись {row["name"]}: I/O отсутствует или неоднозначен')
        side,entries=matches[0]
        pixels,(width,height)=text_pixels(base/row['font'],row['text'],row.get('size',1))
        anchor=entries[0]['fixture']
        offset=row.get('offset',[-width-3,-height//2] if side=='inputs' else [3,-height//2])
        at=row.get('at',[anchor[0]+offset[0],anchor[1]+offset[1]])
        part={(x+at[0],y+at[1]):Cell(25,0) for x,y in pixels}
        if part.keys() & result.keys() or part.keys() & occupied:raise MapError(f'Надпись {row["name"]} пересекается со схемой или I/O')
        result.update(part)
        records.append(dict(name=row['name'],io=reference,text=row['text'],font=row['font'],
                            size=row.get('size',1),at=at,width=width,height=height,cells=len(part)))
    meta.update(labels=records,map_hash=map_hash(result),cells=len(result),bounds=bounds_of(result))
    return result,meta
