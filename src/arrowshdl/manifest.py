"""Strict, versioned TOML input; paths are relative to the manifest."""
from dataclasses import dataclass, replace
from pathlib import Path
import tomllib

from arrowshdl.arrowasm import MapError
from arrowshdl.standards import DEFAULT_STANDARD, check_project_version, check_standard


def table(value, allowed, context):
    if not isinstance(value, dict):
        raise MapError(f"{context}: expected a table")
    unknown = set(value) - set(allowed)
    if unknown:
        raise MapError(f"{context}: unknown fields {', '.join(sorted(unknown))}")


def strings(value, context):
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise MapError(f"{context}: expected a list of nonempty strings")
    return value


def pair(value, context, positive=False):
    if not isinstance(value, list) or len(value) != 2 or any(type(v) is not int for v in value):
        raise MapError(f"{context}: expected a pair of integers")
    if positive and any(v <= 0 for v in value):
        raise MapError(f"{context}: dimensions must be positive")
    return value


def component_file(base, reference):
    if not isinstance(reference,str) or not reference:
        raise MapError('components.file: expected a component filename or library:name')
    if reference.startswith('library:'):
        from arrowshdl.resources import PACKAGE
        name=reference.partition(':')[2]
        if name not in ('seven_segment','history64'):
            raise MapError(f'Unknown I/O library component: {name}')
        path=PACKAGE/'data/components'/f'{name}.toml'
    else:
        path=Path(base)/reference
    if not path.is_file():
        raise MapError(f'Component file not found: {path.resolve()}')
    return path.resolve()


@dataclass(frozen=True)
class Project:
    path: Path
    sources: tuple[Path, ...]
    top: str
    standard: str
    include_dirs: tuple[Path, ...]
    defines: tuple[str, ...]
    parameters: dict
    layout: dict
    timing: tuple[dict, ...]
    bindings: Path | None = None
    inputs: tuple[dict, ...] | None = None
    outputs: tuple[dict, ...] | None = None
    modules: tuple[dict, ...] = ()
    components: tuple[dict, ...] = ()
    connections: tuple[dict, ...] = ()
    labels: tuple[dict, ...] = ()
    version: int = 1
    design_path: Path | None = None
    design: dict | None = None
    output_sources: dict | None = None


def load_project(path: Path) -> Project:
    path = path.resolve()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError as exc:
        raise MapError(f"{path}: invalid TOML: {exc}") from exc
    check_project_version(data.get("version"))
    if data['version'] != 3:
        raise MapError(f"Project format {data['version']} is no longer supported; use version 3")
    return _load_v3(path, data)


def _load_v3(path, data):
    """Build configuration references HDL structure and a presentation sidecar."""
    table(data, {'version','sources','libraries','top','language','include_dirs','defines',
                 'parameters','timing','bindings','design'}, 'project v3')
    base_fields = {'version','sources','libraries','top','language','include_dirs','defines',
                   'parameters','timing','bindings'}
    base = _load_base(path, {key: value for key,value in data.items() if key in base_fields})
    design_path = None
    design = {'ports': (), 'views': (), 'components': (), 'labels': (), 'placement': {}}
    if 'design' in data:
        reference = data['design']
        if not isinstance(reference, str) or not reference:
            raise MapError('design: expected a design TOML filename')
        design_path = (path.parent / reference).resolve()
        if not design_path.is_file():
            raise MapError(f'Design file not found: {design_path}')
        try:
            document = tomllib.loads(design_path.read_text(encoding='utf-8-sig'))
        except tomllib.TOMLDecodeError as exc:
            raise MapError(f'{design_path}: invalid TOML: {exc}') from exc
        design = _load_design(design_path, document)
    labels=tuple(dict(row,io=row['path']) for row in design['labels'])
    return replace(base, version=3, modules=(), components=(), connections=(),
                   inputs=None, outputs=None, labels=labels,
                   layout=design['placement'], design_path=design_path, design=design)


def _load_design(path, data):
    table(data, {'version','ports','views','components','labels','placement'}, 'design')
    if data.get('version') != 1:
        raise MapError('design.version: expected 1')
    result = {}
    definitions = {
        'ports': {'path','widget','size','hidden'},
        'views': {'select','button','size','left','right'},
        'components': {'name','file','kind','text','font','size','bind','at','rotation'},
        'labels': {'name','path','text','font','size','offset','at'},
    }
    for category, allowed in definitions.items():
        rows = data.get(category, [])
        if not isinstance(rows, list):
            raise MapError(f'design.{category}: expected a list of tables')
        seen = set()
        for row in rows:
            table(row, allowed, f'design.{category}')
            key = 'path' if category in ('ports','labels') else 'select' if category == 'views' else 'name'
            if not isinstance(row.get(key), str) or not row[key]:
                raise MapError(f'design.{category}.{key}: a nonempty string is required')
            if category != 'views':
                if row[key] in seen:
                    raise MapError(f'design.{category}: duplicate {key} {row[key]!r}')
                seen.add(row[key])
            if category == 'ports':
                if row.get('hidden', False) not in (True, False):
                    raise MapError('design.ports.hidden: expected a boolean')
                if 'widget' in row and row['widget'] not in ('button','indicator','binary'):
                    raise MapError('design.ports.widget: expected button, indicator or binary')
                if 'size' in row: pair(row['size'], 'design.ports.size', positive=True)
            elif category == 'views':
                if not isinstance(row.get('button'), str) or not row['button']:
                    raise MapError('design.views.button: an HDL input path is required')
                if 'size' in row: pair(row['size'], 'design.views.size', positive=True)
                for side in ('left','right'):
                    item = row.get(side)
                    if item is None: continue
                    table(item, {'port','component','bitmap'}, f'design.views.{side}')
                    if not isinstance(item.get('port'), str) or not item['port']:
                        raise MapError(f'design.views.{side}.port: an HDL output is required')
                    if ('component' in item) == ('bitmap' in item):
                        raise MapError(f'design.views.{side}: specify component or bitmap')
                    if 'component' in item:
                        component_file(path.parent, item['component'])
                        if not item['component'].startswith('library:'):
                            item['component']=str((path.parent/item['component']).resolve())
                    if 'bitmap' in item and (not isinstance(item['bitmap'], list) or not item['bitmap'] or
                                              any(not isinstance(line, str) or not line for line in item['bitmap']) or
                                              len({len(line) for line in item['bitmap']}) != 1 or
                                              any(set(line)-{'.','#'} for line in item['bitmap'])):
                        raise MapError(f'design.views.{side}.bitmap: expected a rectangular . and # raster')
            elif category == 'components':
                if 'at' in row: pair(row['at'], 'design.components.at')
                if row.get('rotation',0) not in (0,1,2,3) or type(row.get('rotation',0)) is not int:
                    raise MapError('design.components.rotation: expected 0, 1, 2 or 3')
                if row.get('kind') == 'text':
                    if 'file' in row or not isinstance(row.get('text'), str) or not row['text']:
                        raise MapError('Text component requires text and cannot specify file')
                    if type(row.get('size',1)) is not int or row.get('size',1) < 1:
                        raise MapError('design.components.size: expected a positive integer')
                    if not isinstance(row.get('font','library:arrow4'), str):
                        raise MapError('design.components.font: expected a font filename')
                else:
                    component_file(path.parent, row.get('file'))
                if 'bind' in row and not (isinstance(row['bind'], str) or
                        isinstance(row['bind'],dict) and row['bind'] and
                        all(isinstance(k,str) and k and isinstance(v,str) and v for k,v in row['bind'].items())):
                    raise MapError('design.components.bind: expected an HDL signal path or port-to-signal table')
                if 'file' in row and not row['file'].startswith('library:'):
                    component_file(path.parent,row['file'])
                    row['file']=str((path.parent/row['file']).resolve())
                if row.get('kind')=='text' and row.get('font','library:arrow4')!='library:arrow4':
                    font=(path.parent/row['font']).resolve()
                    if not font.is_file(): raise MapError(f'Font file not found: {font}')
                    row['font']=str(font)
            else:
                if not isinstance(row.get('text'),str) or not row['text'] or not isinstance(row.get('font'),str) or not row['font']:
                    raise MapError('design.labels: text and font are required')
                if type(row.get('size',1)) is not int or row.get('size',1) < 1:
                    raise MapError('design.labels.size: expected a positive integer')
                if 'at' in row: pair(row['at'],'design.labels.at')
                if 'offset' in row: pair(row['offset'],'design.labels.offset')
                if 'at' in row and 'offset' in row: raise MapError('design.labels: specify at or offset')
                if row['font']=='library:arrow4':
                    from arrowshdl.resources import PACKAGE
                    row['font']=str(PACKAGE/'data/fonts/arrow4.json')
                else:
                    font=(path.parent/row['font']).resolve()
                    if not font.is_file(): raise MapError(f'Font file not found: {font}')
                    row['font']=str(font)
        result[category] = tuple(rows)
    placement = data.get('placement', {})
    table(placement, {'input_buses','input_bus_gap','grids','placements','template'}, 'design.placement')
    strings(placement.get('input_buses', []), 'design.placement.input_buses')
    for category, allowed in (('grids', {'instances','step','origin','max_cell_size'}),
                              ('placements', {'instance','at'})):
        rows = placement.get(category, [])
        if not isinstance(rows, list): raise MapError(f'design.placement.{category}: expected a list')
        for row in rows:
            table(row, allowed, f'design.placement.{category}')
            selector = row.get('instances' if category == 'grids' else 'instance')
            if not isinstance(selector, str) or not selector: raise MapError(f'design.placement.{category}: selector required')
            for field in ('step','origin','max_cell_size','at'):
                if field in row: pair(row[field], f'design.placement.{category}.{field}', positive=field in ('step','max_cell_size'))
            if category == 'grids' and 'step' not in row or category == 'placements' and 'at' not in row:
                raise MapError(f'design.placement.{category}: step or at is missing')
    if 'input_bus_gap' in placement and placement['input_bus_gap'] != 'auto' and (type(placement['input_bus_gap']) is not int or placement['input_bus_gap'] < 0):
        raise MapError('design.placement.input_bus_gap: expected auto or a nonnegative integer')
    if 'template' in placement and (not isinstance(placement['template'],str) or not (path.parent/placement['template']).is_file()):
        raise MapError('design.placement.template: physical template file not found')
    result['placement'] = placement
    return result


def _load_base(path, data):
    table(data, {"version", "sources", "libraries", "top", "language", "include_dirs", "defines", "parameters", "placement", "timing", "bindings", "inputs", "outputs", "modules", "components", "connections", "labels"}, "project")
    sources = strings(data.get("sources", []), "sources") + strings(data.get('libraries', []), 'libraries')
    if not isinstance(data.get("top"), str) or not data["top"]:
        raise MapError("A nonempty top module name is required")
    if not sources:
        raise MapError("Sources or compiled components are required")
    language = data.get("language", {})
    table(language, {"standard"}, "language")
    standard = check_standard(language.get("standard", DEFAULT_STANDARD))
    base = path.parent
    files = tuple((base / value).resolve() for value in sources)
    for file in files:
        if not file.is_file():
            raise MapError(f"Source file not found: {file}")
    includes = tuple((base / v).resolve() for v in strings(data.get("include_dirs", []), "include_dirs"))
    if any(not p.is_dir() for p in includes):
        raise MapError("include_dirs contains a missing directory")
    defines = tuple(strings(data.get("defines", []), "defines"))
    contracts = data.get('timing', [])
    if not isinstance(contracts, list):
        raise MapError('timing: expected a list of contracts')
    for row in contracts:
        table(row, {'name','from','to','max_ticks','states'}, 'timing')
        if not isinstance(row.get('name'),str) or not row['name']:
            raise MapError('timing.name: expected a nonempty contract name')
        if type(row.get('max_ticks')) is not int or row['max_ticks'] < 1:
            raise MapError('timing.max_ticks: expected a positive integer')
        for endpoint in ('from','to'):
            if not isinstance(row.get(endpoint), str):
                pair(row.get(endpoint), 'timing.'+endpoint)
        if not isinstance(row.get('states',[]),list):
            raise MapError('timing.states: expected a list of state coordinates')
        for state in row.get('states',[]):
            pair(state,'timing.states')
    parameters = data.get("parameters", {})
    if not isinstance(parameters, dict) or any(type(v) not in (int, str) for v in parameters.values()):
        raise MapError("parameters: expected a table of integers or HDL constants")
    layout = data.get("placement", {})
    table(layout, {"input_buses", "input_bus_gap", "grids", "placements", "template"}, "placement")
    strings(layout.get("input_buses", []), "placement.input_buses")
    gap = layout.get("input_bus_gap", "auto")
    if gap != "auto" and (type(gap) is not int or gap < 0):
        raise MapError("placement.input_bus_gap: expected auto or a nonnegative integer")
    for name, allowed in (("grids", {"instances", "step", "origin", "max_cell_size"}), ("placements", {"instance", "at"})):
        rows = layout.get(name, [])
        if not isinstance(rows, list):
            raise MapError(f"layout.{name}: expected a list of tables")
        for row in rows:
            table(row, allowed, f"layout.{name}")
            selector = row.get("instances" if name == "grids" else "instance")
            if not isinstance(selector, str) or not selector:
                raise MapError(f"layout.{name}: an instance name is required")
            for field in ("step", "origin", "max_cell_size", "at"):
                if field in row:
                    pair(row[field], f"layout.{name}.{field}", positive=field in ("step", "max_cell_size"))
            if (name == "grids" and "step" not in row) or (name == "placements" and "at" not in row):
                raise MapError(f"layout.{name}: step or at is missing")
    rows = {}
    definitions = {
        'inputs': {'name', 'to', 'widget', 'size'},
        'outputs': {'name', 'from', 'widget'},
        'modules': {'name', 'hdl', 'parameters', 'at'},
        'components': {'name', 'file', 'at', 'rotation'},
        'connections': {'from', 'to'},
        'labels': {'name', 'io', 'text', 'font', 'size', 'offset', 'at'},
    }
    for key, allowed in definitions.items():
        value = data.get(key, [])
        if not isinstance(value, list):
            raise MapError(f'{key}: expected a list of tables; [] disables automatic widgets')
        seen = set()
        for row in value:
            table(row, allowed, key)
            if key != 'connections':
                if not isinstance(row.get('name'), str) or not row['name'] or row['name'] in seen:
                    raise MapError(f'{key}: a unique nonempty name is required')
                seen.add(row['name'])
            if key == 'modules' and not isinstance(row.get('hdl'), str):
                raise MapError('modules.hdl: expected a Verilog module name')
            if key == 'modules':
                params=row.get('parameters', {})
                if not isinstance(params,dict) or any(type(v) not in (int,str) for v in params.values()):
                    raise MapError('modules.parameters: expected a table of HDL constants')
            if key == 'components':
                component_file(base,row.get('file'))
                if row.get('rotation', 0) not in (0, 1, 2, 3) or type(row.get('rotation', 0)) is not int:
                    raise MapError('components.rotation: expected 0, 1, 2 or 3')
            if 'at' in row:
                pair(row['at'], key+'.at')
            if key == 'inputs' and 'size' in row:
                pair(row['size'], 'inputs.size', positive=True)
            if key == 'labels':
                if not all(isinstance(row.get(k),str) and row[k] for k in ('io','text','font')):
                    raise MapError('labels: io, text and font file are required')
                if type(row.get('size',1)) is not int or row.get('size',1)<1:
                    raise MapError('labels.size: expected a positive integer font scale')
                if 'offset' in row:pair(row['offset'],'labels.offset')
                if 'at' in row and 'offset' in row:
                    raise MapError('labels: specify at or offset')
            if key in ('inputs', 'connections') and not isinstance(row.get('to'), str):
                raise MapError(key+'.to: a logical input is required')
            if key in ('outputs', 'connections') and not isinstance(row.get('from'), str):
                raise MapError(key+'.from: a logical output is required')
        rows[key] = tuple(value) if key in data or key not in ('inputs', 'outputs') else None
    bindings = (base / data["bindings"]).resolve() if isinstance(data.get("bindings"), str) else None
    if "bindings" in data and (bindings is None or not bindings.is_file()):
        raise MapError("bindings: an existing observation JSON file is required")
    return Project(path, files, data["top"], standard, includes, defines, parameters, layout, tuple(contracts), bindings,
                   rows['inputs'], rows['outputs'], rows['modules'], rows['components'], rows['connections'],rows['labels'])
