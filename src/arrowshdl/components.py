"""Opaque placed modules: load game saves, transform coordinates, expose declared pins.

No synthesis, simplification or reconstruction of a component's computation.
"""
from copy import deepcopy
from pathlib import Path
import tomllib
import json

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
    for key in ('state_boundaries',):
        if key in meta: meta[key]=[[p[0]+dx,p[1]+dy] for p in meta[key]]
    if meta.get('timing'):
        meta['timing']['state_boundaries']=[[p[0]+dx,p[1]+dy] for p in meta['timing'].get('state_boundaries',())]
    for gate in meta.get('gate_labels',[]): gate['at']=[gate['at'][0]+dx,gate['at'][1]+dy]
    if meta.get('display'):
        meta['display']['pixels']=[[p[0]+dx,p[1]+dy] for p in meta['display']['pixels']]
    if meta.get('display_pixels'):
        meta['display_pixels']=[[p[0]+dx,p[1]+dy] for p in meta['display_pixels']]
    if meta.get('segment_pixels'):
        meta['segment_pixels']=[[[p[0]+dx,p[1]+dy] for p in row] for row in meta['segment_pixels']]
    if meta.get('panel'):
        panel=meta['panel']
        for key in ('min','max'): panel['region'][key]=[panel['region'][key][0]+dx,panel['region'][key][1]+dy]
        for side,item in panel.get('displays',{}).items():
            for entries in item['inputs'].values():
                for entry in entries:
                    for key in ('contact','fixture'): entry[key]=[entry[key][0]+dx,entry[key][1]+dy]
            item['pixels']=[[p[0]+dx,p[1]+dy] for p in item.get('pixels',[])]
            if item.get('segment_pixels'):
                item['segment_pixels']=[[[p[0]+dx,p[1]+dy] for p in row] for row in item['segment_pixels']]
        panel['button']=[[p[0]+dx,p[1]+dy] for p in panel['button']]
    return {(x+dx,y+dy):c for (x,y),c in cells.items()},meta


def load_component(path,at=(0,0),rotation=0):
    path=Path(path).resolve()
    data=(json.loads if path.suffix=='.json' else tomllib.loads)(path.read_text(encoding='utf-8-sig'))
    embedded = None
    if data.get('format') == 'arrowshdl-compiled-scheme':
        from arrowshdl.artifacts import unpack
        from arrowshdl.module_cache import component_document
        embedded, metadata = unpack(data)
        data = component_document(metadata['top'], metadata)
    table(data,{'version','map','ports','interface','settle_ticks','state_boundaries','panel',
                'display_pixels','segment_pixels'},str(path))
    if type(data.get('version')) is not int or data['version']!=1:
        raise MapError(f'{path}: unsupported compiled module descriptor version')
    if not isinstance(data.get('map'),str) or not data['map']:
        raise MapError('Compiled module must reference map JSON or a game save')
    cells=embedded if embedded is not None else read_map(path.parent/data['map'])
    if not cells:raise MapError('Compiled module is empty')
    ports=data.get('ports',{})
    table(ports,{'inputs','outputs'},'ports')
    meta=dict(inputs=deepcopy(ports.get('inputs',{})),outputs=deepcopy(ports.get('outputs',{})),state_boundaries=data.get('state_boundaries',[]))
    if data.get('panel'):meta['panel']=deepcopy(data['panel'])
    if data.get('segment_pixels'):meta['segment_pixels']=deepcopy(data['segment_pixels'])
    if data.get('display_pixels'):meta['display_pixels']=deepcopy(data['display_pixels'])
    if embedded is not None and metadata.get('segment_pixels'):meta['segment_pixels']=deepcopy(metadata['segment_pixels'])
    if embedded is not None and metadata.get('display'):meta['display']=deepcopy(metadata['display'])
    for point in meta['state_boundaries']: pair(point,'state_boundaries')
    contacts=set()
    for side in ('inputs','outputs'):
        if not isinstance(meta[side],dict):raise MapError('ports: expected named contacts')
        for name,entries in meta[side].items():
            if not name or not isinstance(entries,list) or not entries:
                raise MapError(f'{name}: missing port contacts')
            for e in entries:
                table(e,{'index','contact','fixture','rotation','panel'},name)
                pair(e.get('contact'),name+'.contact');pair(e.get('fixture'),name+'.fixture')
                if type(e.get('index')) is not int or e['index']<0 or type(e.get('rotation')) is not int or e['rotation'] not in (0,1,2,3):
                    raise MapError(f'{name}: invalid index or rotation')
                contact,fixture=tuple(e['contact']),tuple(e['fixture'])
                if contact not in cells or fixture in cells:
                    raise MapError(f'{name}: contact is missing or fixture is occupied')
                if (side,fixture) in contacts:raise MapError('One fixture is declared by multiple ports')
                contacts.add((side,fixture))
                if side=='inputs' and list(destinations(fixture,Cell(1,e['rotation'])))!=[contact]:
                    raise MapError(f'{name}: input contact direction does not match fixture')
                if side=='outputs' and fixture not in destinations(contact,cells[contact]):
                    raise MapError(f'{name}: output does not point toward fixture')
            entries.sort(key=lambda e:e['index'])
            if [e['index'] for e in entries]!=list(range(len(entries))):
                raise MapError(f'{name}: bit indices must start at 0 without duplicates or gaps')
    interface=data.get('interface',{})
    table(interface,{'kind','encoding','protocol','bit_order'},'interface')
    if any(not isinstance(v,str) or not v for v in interface.values()):
        raise MapError('interface: expected nonempty descriptive strings')
    ticks=data.get('settle_ticks',len(cells)+2)
    if type(ticks) is not int or ticks<1:raise MapError('settle_ticks: expected a positive integer')
    source_hash=map_hash(cells)
    def turn(p):
        x,y=p
        for _ in range(rotation):x,y=-y,x
        return [x,y]
    if rotation:
        if meta.get('panel'):raise MapError('Rotating a compiled interaction panel is unsupported')
        cells={tuple(turn(p)):Cell(c.type,(c.rotation+rotation)%4,c.mirrored) for p,c in cells.items()}
        if meta.get('segment_pixels'):meta['segment_pixels']=[[turn(p) for p in row] for row in meta['segment_pixels']]
        if meta.get('display'):meta['display']['pixels']=[turn(p) for p in meta['display']['pixels']]
        if meta.get('display_pixels'):meta['display_pixels']=[turn(p) for p in meta['display_pixels']]
        for side in ('inputs','outputs'):
            for entries in meta[side].values():
                for e in entries:
                    e['contact'],e['fixture']=turn(e['contact']),turn(e['fixture'])
                    e['rotation']=(e['rotation']+rotation)%4
        meta['state_boundaries']=[turn(p) for p in meta['state_boundaries']]
    cells,meta=move(cells,meta,at)
    placed_hash=map_hash(cells)
    meta.update(component_version=1,source_map_hash=source_hash,placed_map_hash=placed_hash,map_hash=placed_hash,
                interface=interface,settle_ticks=ticks,bounds=bounds_of(cells),file=str(path))
    return cells,meta


def keepout(cells):
    """Keep empty cells inside the module's footprint empty too."""
    bounds=bounds_of(cells)
    (x0,y0),(x1,y1)=bounds['min'],bounds['max']
    return {(x,y) for y in range(y0,y1+1) for x in range(x0,x1+1)}
