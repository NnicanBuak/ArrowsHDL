"""Opaque placed modules: decode storage, transform coordinates, expose declared pins.

No synthesis, simplification or reconstruction of a component's computation.
"""
from copy import deepcopy
from pathlib import Path
import tomllib

from arrowshdl.arrowasm import Cell, MapError
from arrowshdl.arrow_layout import bounds_of, destinations
from arrowshdl.manifest import pair, table
from arrowshdl.mapdata import map_hash, read_map


def move(cells, manifest, at):
    dx,dy=at
    meta=deepcopy(manifest)
    for side in ('inputs','outputs'):
        for entries in meta[side].values():
            for e in entries:
                for key in ('contact','fixture'):
                    e[key]=[e[key][0]+dx,e[key][1]+dy]
    return {(x+dx,y+dy):c for (x,y),c in cells.items()},meta


def load_component(path,at=(0,0),rotation=0):
    path=Path(path).resolve()
    data=tomllib.loads(path.read_text(encoding='utf-8-sig'))
    table(data,{'version','map','ports','interface','settle_ticks'},str(path))
    if type(data.get('version')) is not int or data['version']!=1:
        raise MapError(f'{path}: неизвестная версия описания готового модуля')
    if not isinstance(data.get('map'),str) or not data['map']:
        raise MapError('Готовый модуль должен ссылаться на map JSON или код сохранения')
    cells=read_map(path.parent/data['map'])
    if not cells:raise MapError('Готовый модуль пуст')
    ports=data.get('ports',{})
    table(ports,{'inputs','outputs'},'ports')
    meta=dict(inputs=deepcopy(ports.get('inputs',{})),outputs=deepcopy(ports.get('outputs',{})))
    contacts=set()
    for side in ('inputs','outputs'):
        if not isinstance(meta[side],dict):raise MapError('ports: ожидаются именованные контакты')
        for name,entries in meta[side].items():
            if not name or not isinstance(entries,list) or not entries:
                raise MapError(f'{name}: отсутствуют контакты порта')
            for e in entries:
                table(e,{'index','contact','fixture','rotation'},name)
                pair(e.get('contact'),name+'.contact');pair(e.get('fixture'),name+'.fixture')
                if type(e.get('index')) is not int or e['index']<0 or type(e.get('rotation')) is not int or e['rotation'] not in (0,1,2,3):
                    raise MapError(f'{name}: неправильный индекс или поворот')
                contact,fixture=tuple(e['contact']),tuple(e['fixture'])
                if contact not in cells or fixture in cells:
                    raise MapError(f'{name}: контакт отсутствует или место соединения занято')
                if (side,fixture) in contacts:raise MapError('Одна площадка объявлена несколькими портами')
                contacts.add((side,fixture))
                if side=='inputs' and list(destinations(fixture,Cell(1,e['rotation'])))!=[contact]:
                    raise MapError(f'{name}: направление входного контакта не совпадает с fixture')
                if side=='outputs' and fixture not in destinations(contact,cells[contact]):
                    raise MapError(f'{name}: выход не направлен на fixture')
            entries.sort(key=lambda e:e['index'])
            if [e['index'] for e in entries]!=list(range(len(entries))):
                raise MapError(f'{name}: индексы битов должны идти от 0 без повторов и пропусков')
    interface=data.get('interface',{})
    table(interface,{'kind','encoding','protocol','bit_order'},'interface')
    if any(not isinstance(v,str) or not v for v in interface.values()):
        raise MapError('interface: описательные непустые строки')
    ticks=data.get('settle_ticks',len(cells)+2)
    if type(ticks) is not int or ticks<1:raise MapError('settle_ticks: положительное целое число')
    source_hash=map_hash(cells)
    def turn(p):
        x,y=p
        for _ in range(rotation):x,y=-y,x
        return [x,y]
    if rotation:
        cells={tuple(turn(p)):Cell(c.type,(c.rotation+rotation)%4,c.mirrored) for p,c in cells.items()}
        for side in ('inputs','outputs'):
            for entries in meta[side].values():
                for e in entries:
                    e['contact'],e['fixture']=turn(e['contact']),turn(e['fixture'])
                    e['rotation']=(e['rotation']+rotation)%4
    cells,meta=move(cells,meta,at)
    meta.update(component_version=1,source_map_hash=source_hash,placed_map_hash=map_hash(cells),
                interface=interface,settle_ticks=ticks,bounds=bounds_of(cells),file=str(path))
    return cells,meta


def keepout(cells):
    """Keep empty cells inside the module's footprint empty too."""
    bounds=bounds_of(cells)
    (x0,y0),(x1,y1)=bounds['min'],bounds['max']
    return {(x,y) for y in range(y0,y1+1) for x in range(x0,x1+1)}
