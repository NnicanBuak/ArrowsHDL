"""Attach controls and displays to logical HDL ports without changing the core."""
from copy import deepcopy

from arrowshdl.arrowasm import Cell, MapError
from arrowshdl.arrow_layout import bounds_of, destinations
from arrowshdl.mapdata import map_hash


def button_cells(at,rotation,size):
    """A rectangle of directional buttons collecting toward one boundary pin."""
    w,h=size
    if w*h>1000000:raise MapError('Кнопка превышает миллион клеток')
    x,y=at
    if rotation==0:x0,y0=x-w//2,y
    elif rotation==1:x0,y0=x-w+1,y-h//2
    elif rotation==2:x0,y0=x-w//2,y-h+1
    else:x0,y0=x,y-h//2
    result={}
    for py in range(y0,y0+h):
        for px in range(x0,x0+w):
            if (px,py)==at:r=rotation
            elif py!=y:r=2 if py<y else 0
            else:r=1 if px<x else 3
            result[px,py]=Cell(24,r)
    return result


def port_bits(ports, reference):
    """Resolve a whole named port or one bit: result[3]."""
    if reference in ports:
        return ports[reference]
    if reference.endswith(']') and '[' in reference:
        name, number = reference[:-1].rsplit('[', 1)
        try:
            index = int(number)
        except ValueError as exc:
            raise MapError(f'Неверный индекс порта {reference}') from exc
        entries = [entry for entry in ports.get(name, ()) if entry['index'] == index]
        if entries:
            return entries
    raise MapError(f'Логический порт не найден: {reference}')


def attach_io(cells, manifest, inputs=None, outputs=None, *, testing=False):
    """None selects default widgets; [] explicitly leaves the ports unbound.

    Bit indicators are native arrows. Test mode substitutes Source/Target at
    the same declared contacts; normal displays stay part of the view.
    """
    cells, meta = dict(cells), deepcopy(manifest)
    devices = []
    if inputs is None:
        inputs = [dict(name=name, to=name, widget='button') for name in meta['inputs']]
    if outputs is None:
        outputs = meta.get('default_outputs',[dict(name=name, **{'from': name}, widget='indicator') for name in meta['outputs']])
    occupied_ports = set()
    for rows, direction, endpoint in ((inputs, 'inputs', 'to'), (outputs, 'outputs', 'from')):
        for row in rows:
            reference = row.get(endpoint, row.get('name'))
            entries = port_bits(meta[direction], reference)
            widget = row.get('widget', 'button' if direction == 'inputs' else 'indicator')
            if widget not in (('button',) if direction == 'inputs' else ('indicator', 'binary')):
                raise MapError(f'Встроенный виджет {widget!r} не поддерживается; готовые дисплеи подключаются как components')
            for entry in entries:
                key = (direction, tuple(entry['contact']))
                if key in occupied_ports:
                    raise MapError(f'Повторное подключение виджета к {reference}')
                occupied_ports.add(key)
                at = tuple(entry['fixture'])
                if at in cells:
                    raise MapError(f'Место виджета занято: {at}')
                kind = (22 if testing else 24) if direction == 'inputs' else 1
                if direction=='inputs' and not testing:
                    part=button_cells(at,entry['rotation'],row.get('size',[1,1]))
                    if cells.keys() & part.keys():raise MapError('Кнопка заданного размера пересекается со схемой')
                    if any(q in part for p,c in cells.items() for q in destinations(p,c)):
                        raise MapError('Схема подаёт посторонний сигнал в кнопку')
                    cells.update(part)
                elif direction=='outputs' and entry.get('sensor'):
                    sensor=entry['sensor'];p=tuple(sensor['at'])
                    if p in cells:raise MapError('Место пробника занято')
                    cells[p]=Cell(5,sensor['rotation']);cells[at]=Cell(kind,entry['rotation'])
                else:
                    cells[at] = Cell(kind, entry['rotation'])
                if direction == 'inputs' and list(destinations(at, cells[at])) != [tuple(entry['contact'])]:
                    raise MapError('Кнопка не направлена на логический вход')
                devices.append(dict(name=row.get('name', reference), port=reference, index=entry['index'],
                                    kind=widget, direction=direction, at=list(at), type=kind))
    meta['io_devices'] = devices
    meta['core_map_hash'] = manifest['map_hash']
    meta['map_hash'] = map_hash(cells)
    meta['cells'] = len(cells)
    meta['bounds'] = bounds_of(cells)
    meta['build_target'] = 'test' if testing else 'scheme'
    if testing:
        from arrowshdl.test_harness import add_fixture
        cells=add_fixture(cells,meta)
        meta['map_hash']=map_hash(cells)
        meta['cells']=len(cells)
        meta['bounds']=bounds_of(cells)
    return cells, meta
