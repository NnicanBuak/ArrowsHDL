"""Versioned RTLIL JSON module objects, compatible with separate compilation."""
from copy import deepcopy
import json
from pathlib import Path

from arrowshdl import __version__
from arrowshdl.arrowasm import MapError
from arrowshdl.mapdata import write_json
from arrowshdl.standards import OBJECT_VERSION, check_standard
from arrowshdl.verilog_frontend import elaborate, synthesize_raw
from arrowshdl.execution import bounded


@bounded
def compile_object(sources, top, output=None, timeout=90, **options):
    raw, _ = elaborate(sources, top, timeout, **options)
    document = {'format': 'arrowshdl-object', 'version': OBJECT_VERSION, 'compiler': __version__,
                'standard': options.get('standard', '1800-2023'), 'top': top, 'rtlil': raw}
    document['interface'] = raw['modules'][top].get('ports', {})
    document['parameters'] = options.get('parameters', {})
    document['instances'] = raw['modules'][top].get('cells', {})
    document['timing'] = []
    if output is not None:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        write_json(output, document)
    return document


def link_objects(paths, top, timeout=90):
    merged, standard = {}, None
    for path in paths:
        obj = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if obj.get('format') != 'arrowshdl-object' or type(obj.get('version')) is not int or obj['version'] != OBJECT_VERSION:
            raise MapError(f'{path}: несовместимая версия объектного файла')
        check_standard(obj.get('standard'))
        if standard and standard != obj['standard']:
            raise MapError('Объекты собраны для разных стандартов HDL')
        standard = obj['standard']
        for name, module in obj['rtlil']['modules'].items():
            module = deepcopy(module)
            module.get('attributes', {}).pop('top', None)
            previous = merged.get(name)
            if previous is not None and previous != module:
                old_blackbox = previous.get('attributes', {}).get('blackbox')
                new_blackbox = module.get('attributes', {}).get('blackbox')
                if old_blackbox and not new_blackbox:
                    _check_interface(name,previous,module)
                    merged[name] = module
                elif not old_blackbox and new_blackbox:
                    _check_interface(name,module,previous)
                    continue
                else:
                    raise MapError(f'Конфликт определения модуля {name}')
            else:
                merged[name] = module
    if top not in merged:
        raise MapError(f'В объектах отсутствует верхний модуль {top}')
    merged[top].setdefault('attributes', {})['top'] = '1'
    graph, log = synthesize_raw({'modules': merged, 'creator': f'ArrowsHDL {__version__}'}, top, timeout)
    return graph, log, standard


def _check_interface(name,a,b):
    def signature(module):
        return {n:(p['direction'],len(p['bits']),p.get('offset',0),p.get('upto',0))
                for n,p in module.get('ports',{}).items()}
    if signature(a)!=signature(b):raise MapError(f'Несовместимые интерфейсы модуля {name}')
