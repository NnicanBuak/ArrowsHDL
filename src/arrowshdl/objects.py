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
        try:
            obj = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise MapError(f'{path}: invalid object JSON: {error}') from error
        if not isinstance(obj, dict) or obj.get('format') != 'arrowshdl-object' or type(obj.get('version')) is not int or obj['version'] != OBJECT_VERSION:
            raise MapError(f'{path}: incompatible object file version')
        _validate_object(path, obj)
        check_standard(obj['standard'])
        if standard and standard != obj['standard']:
            raise MapError('Objects use incompatible HDL standards')
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
                    raise MapError(f'Conflicting module definition: {name}')
            else:
                merged[name] = module
    if top not in merged:
        raise MapError(f'Objects do not contain top module {top}')
    merged[top].setdefault('attributes', {})['top'] = '1'
    graph, log = synthesize_raw({'modules': merged, 'creator': f'ArrowsHDL {__version__}'}, top, timeout)
    return graph, log, standard


def _validate_object(path, obj):
    """Reject malformed object documents before linking can index into them."""
    def require(condition, field, expected):
        if not condition:
            raise MapError(f'{path}: malformed ArrowsHDL object: {field} {expected}')

    require(isinstance(obj, dict), 'root', 'must be an object')
    require(isinstance(obj.get('standard'), str), 'standard', 'must be a string')

    rtlil = obj.get('rtlil')
    require(isinstance(rtlil, dict), 'rtlil', 'must be an object')
    modules = rtlil.get('modules')
    require(isinstance(modules, dict) and bool(modules), 'rtlil.modules', 'must be a nonempty object')
    top = obj.get('top')
    require(isinstance(top, str) and top in modules, 'top', 'must name a module in rtlil.modules')
    for module_name, module in modules.items():
        require(isinstance(module_name, str) and isinstance(module, dict),
                f'rtlil.modules[{module_name!r}]', 'must be an object')
        for field in ('attributes', 'ports', 'cells'):
            require(field not in module or isinstance(module[field], dict),
                    f'rtlil.modules[{module_name!r}].{field}', 'must be an object')
        for port_name, port in module.get('ports', {}).items():
            location = f'rtlil.modules[{module_name!r}].ports[{port_name!r}]'
            require(isinstance(port, dict), location, 'must be an object')
            require(port.get('direction') in ('input', 'output', 'inout'),
                    f'{location}.direction', 'must be input, output or inout')
            require(isinstance(port.get('bits'), list), f'{location}.bits', 'must be an array')
        for cell_name, cell in module.get('cells', {}).items():
            location = f'rtlil.modules[{module_name!r}].cells[{cell_name!r}]'
            require(isinstance(cell, dict), location, 'must be an object')
            require(isinstance(cell.get('type'), str), f'{location}.type', 'must be a string')
            require(isinstance(cell.get('connections'), dict),
                    f'{location}.connections', 'must be an object')
            require(all(isinstance(bits, list) for bits in cell['connections'].values()),
                    f'{location}.connections', 'values must be arrays')
            for field in ('attributes', 'parameters', 'port_directions'):
                require(field not in cell or isinstance(cell[field], dict),
                        f'{location}.{field}', 'must be an object')


def _check_interface(name,a,b):
    def signature(module):
        return {n:(p['direction'],len(p['bits']),p.get('offset',0),p.get('upto',0))
                for n,p in module.get('ports',{}).items()}
    if signature(a)!=signature(b):raise MapError(f'Incompatible module interfaces: {name}')
