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
        path=PACKAGE/'data/components'/f'{name}.json'
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


def load_project(path: Path) -> Project:
    path = path.resolve()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError as exc:
        raise MapError(f"{path}: invalid TOML: {exc}") from exc
    check_project_version(data.get("version"))
    return _load_v2(path,data) if data['version']==2 else _load_v1(path, data)


def _load_v2(path,data):
    """A logical graph: geometry and optimization are compiler decisions."""
    table(data,{'version','sources','libraries','top','language','include_dirs','defines',
                'modules','components','connections','inputs','outputs'},'project v2')
    base = _load_v1(path,dict(data,version=1,modules=[],components=[],connections=[],inputs=[],outputs=[]),allow_empty_sources=True)
    if not (data.get('modules') or data.get('components')):
        raise MapError('project v2: modules or compiled components are required')
    definitions = {'modules':{'name','hdl','parameters','panel'},'components':{'name','file','kind','text','font','size'},
                   'connections':{'from','to'},'inputs':{'name','width','widget','size'},
                   'outputs':{'name','from','widget','length'}}
    rows = {}
    names = set()
    for category,allowed in definitions.items():
        value = data.get(category,[])
        if not isinstance(value,list): raise MapError(category+': expected a list')
        for row in value:
            table(row,allowed,category)
            if category!='connections':
                import re
                name = row.get('name')
                if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',name) or name in names:
                    raise MapError(category+': a unique HDL identifier is required')
                names.add(name)
            if category=='modules':
                if not isinstance(row.get('hdl'),str): raise MapError('modules.hdl: expected a Verilog module name')
                params = row.get('parameters',{})
                if not isinstance(params,dict) or any(type(v) not in (int,str) for v in params.values()):
                    raise MapError('modules.parameters: expected a table of HDL constants')
                if 'panel' in row:
                    panel=row['panel'];table(panel,{'button','size','left','right'},'modules.panel')
                    if not isinstance(panel.get('button'),str) or not panel['button']: raise MapError('panel.button: expected an HDL input')
                    pair(panel.get('size',[7,7]),'panel.size',positive=True)
                    for side in ('left','right'):
                        if side not in panel: continue
                        item=panel[side];table(item,{'file','port','bitmap'},'panel.'+side)
                        if not isinstance(item.get('port'),str) or not item['port']: raise MapError('panel.'+side+'.port: expected an HDL output')
                        if ('file' in item)==('bitmap' in item): raise MapError('panel.'+side+': specify file or bitmap')
                        if 'file' in item: component_file(path.parent,item['file'])
            if category=='components':
                if row.get('kind')=='text':
                    if 'file' in row: raise MapError('Text component cannot also specify file')
                    if not isinstance(row.get('text'),str) or not row['text']: raise MapError('Text component requires nonempty text')
                    if type(row.get('size',1)) is not int or row.get('size',1)<1: raise MapError('Text size must be a positive integer')
                    if not isinstance(row.get('font','library:arrow4'),str) or not row.get('font','library:arrow4'):
                        raise MapError('Text font must be a filename or library:arrow4')
                else:
                    if set(row)-{'name','file'}: raise MapError('Component requires file or kind="text"')
                    component_file(path.parent,row.get('file'))
            if category=='inputs':
                if type(row.get('width',1)) is not int or not 1<=row.get('width',1)<=65536:
                    raise MapError('inputs.width: expected a positive width up to 65536 bits')
                if 'size' in row: pair(row['size'],'inputs.size',positive=True)
            for key in ({'connections':('from','to'),'outputs':('from',)}.get(category,())):
                if not isinstance(row.get(key),str) or not row[key]: raise MapError(category+'.'+key+': a port is required')
        rows[category] = tuple(value)
    if rows['modules'] and not base.sources: raise MapError('HDL modules require source files')
    return replace(base,version=2,modules=rows['modules'],components=rows['components'],
                   connections=rows['connections'],inputs=rows['inputs'],outputs=rows['outputs'])


def _load_v1(path, data, *, allow_empty_sources=False):
    table(data, {"version", "sources", "libraries", "top", "language", "include_dirs", "defines", "parameters", "placement", "timing", "bindings", "inputs", "outputs", "modules", "components", "connections", "labels"}, "project v1")
    sources = strings(data.get("sources", []), "sources") + strings(data.get('libraries', []), 'libraries')
    if not isinstance(data.get("top"), str) or not data["top"]:
        raise MapError("A nonempty top module name is required")
    if not sources and (data.get('modules') or not data.get('components')) and not allow_empty_sources:
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
