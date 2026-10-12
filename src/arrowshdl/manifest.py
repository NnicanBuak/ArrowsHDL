"""Strict, versioned TOML input; paths are relative to the manifest."""
from dataclasses import dataclass
from pathlib import Path
import tomllib

from arrowshdl.arrowasm import MapError
from arrowshdl.standards import DEFAULT_STANDARD, check_project_version, check_standard


def table(value, allowed, context):
    if not isinstance(value, dict):
        raise MapError(f"{context}: ожидается таблица")
    unknown = set(value) - set(allowed)
    if unknown:
        raise MapError(f"{context}: неизвестные поля {', '.join(sorted(unknown))}")


def strings(value, context):
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise MapError(f"{context}: ожидается список непустых строк")
    return value


def pair(value, context, positive=False):
    if not isinstance(value, list) or len(value) != 2 or any(type(v) is not int for v in value):
        raise MapError(f"{context}: ожидается пара целых чисел")
    if positive and any(v <= 0 for v in value):
        raise MapError(f"{context}: размеры должны быть положительными")
    return value


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


def load_project(path: Path) -> Project:
    path = path.resolve()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError as exc:
        raise MapError(f"{path}: некорректный TOML: {exc}") from exc
    check_project_version(data.get("version"))
    return _load_v1(path, data)


def _load_v1(path, data):
    table(data, {"version", "sources", "libraries", "top", "language", "include_dirs", "defines", "parameters", "placement", "timing", "bindings", "inputs", "outputs", "modules", "components", "connections", "labels"}, "схема v1")
    sources = strings(data.get("sources", []), "sources") + strings(data.get('libraries', []), 'libraries')
    if not isinstance(data.get("top"), str) or not data["top"]:
        raise MapError("Требуется непустое имя top")
    if not sources and (data.get('modules') or not data.get('components')):
        raise MapError("Требуются sources или готовые components")
    language = data.get("language", {})
    table(language, {"standard"}, "language")
    standard = check_standard(language.get("standard", DEFAULT_STANDARD))
    base = path.parent
    files = tuple((base / value).resolve() for value in sources)
    for file in files:
        if not file.is_file():
            raise MapError(f"Исходник не найден: {file}")
    includes = tuple((base / v).resolve() for v in strings(data.get("include_dirs", []), "include_dirs"))
    if any(not p.is_dir() for p in includes):
        raise MapError("include_dirs содержит отсутствующую папку")
    defines = tuple(strings(data.get("defines", []), "defines"))
    contracts = data.get('timing', [])
    if not isinstance(contracts, list):
        raise MapError('timing: ожидается список контрактов')
    for row in contracts:
        table(row, {'name','from','to','max_ticks','states'}, 'timing')
        if not isinstance(row.get('name'),str) or not row['name']:
            raise MapError('timing.name: непустое имя контракта')
        if type(row.get('max_ticks')) is not int or row['max_ticks'] < 1:
            raise MapError('timing.max_ticks: положительное целое число')
        for endpoint in ('from','to'):
            if not isinstance(row.get(endpoint), str):
                pair(row.get(endpoint), 'timing.'+endpoint)
        if not isinstance(row.get('states',[]),list):
            raise MapError('timing.states: список координат памяти')
        for state in row.get('states',[]):
            pair(state,'timing.states')
    parameters = data.get("parameters", {})
    if not isinstance(parameters, dict) or any(type(v) not in (int, str) for v in parameters.values()):
        raise MapError("parameters: таблица целых чисел или констант HDL")
    layout = data.get("placement", {})
    table(layout, {"input_buses", "input_bus_gap", "grids", "placements", "template"}, "placement")
    strings(layout.get("input_buses", []), "placement.input_buses")
    gap = layout.get("input_bus_gap", "auto")
    if gap != "auto" and (type(gap) is not int or gap < 0):
        raise MapError("placement.input_bus_gap: auto или неотрицательное целое число")
    for name, allowed in (("grids", {"instances", "step", "origin", "max_cell_size"}), ("placements", {"instance", "at"})):
        rows = layout.get(name, [])
        if not isinstance(rows, list):
            raise MapError(f"layout.{name}: ожидается список таблиц")
        for row in rows:
            table(row, allowed, f"layout.{name}")
            selector = row.get("instances" if name == "grids" else "instance")
            if not isinstance(selector, str) or not selector:
                raise MapError(f"layout.{name}: требуется имя экземпляра")
            for field in ("step", "origin", "max_cell_size", "at"):
                if field in row:
                    pair(row[field], f"layout.{name}.{field}", positive=field in ("step", "max_cell_size"))
            if (name == "grids" and "step" not in row) or (name == "placements" and "at" not in row):
                raise MapError(f"layout.{name}: отсутствует step или at")
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
            raise MapError(f'{key}: ожидается список таблиц; [] отключает автоматические виджеты')
        seen = set()
        for row in value:
            table(row, allowed, key)
            if key != 'connections':
                if not isinstance(row.get('name'), str) or not row['name'] or row['name'] in seen:
                    raise MapError(f'{key}: требуется уникальное непустое имя')
                seen.add(row['name'])
            if key == 'modules' and not isinstance(row.get('hdl'), str):
                raise MapError('modules.hdl: требуется имя модуля Verilog')
            if key == 'modules':
                params=row.get('parameters', {})
                if not isinstance(params,dict) or any(type(v) not in (int,str) for v in params.values()):
                    raise MapError('modules.parameters: таблица констант HDL')
            if key == 'components':
                if not isinstance(row.get('file'), str) or not (base / row['file']).is_file():
                    raise MapError('components.file: требуется существующий TOML готового блока')
                if row.get('rotation', 0) not in (0, 1, 2, 3) or type(row.get('rotation', 0)) is not int:
                    raise MapError('components.rotation: 0, 1, 2 или 3')
            if 'at' in row:
                pair(row['at'], key+'.at')
            if key == 'inputs' and 'size' in row:
                pair(row['size'], 'inputs.size', positive=True)
            if key == 'labels':
                if not all(isinstance(row.get(k),str) and row[k] for k in ('io','text','font')):
                    raise MapError('labels: требуются io, text и файл font')
                if type(row.get('size',1)) is not int or row.get('size',1)<1:
                    raise MapError('labels.size: положительный целочисленный множитель кегля')
                if 'offset' in row:pair(row['offset'],'labels.offset')
                if 'at' in row and 'offset' in row:
                    raise MapError('labels: укажите at или offset')
            if key in ('inputs', 'connections') and not isinstance(row.get('to'), str):
                raise MapError(key+'.to: требуется логический вход')
            if key in ('outputs', 'connections') and not isinstance(row.get('from'), str):
                raise MapError(key+'.from: требуется логический выход')
        rows[key] = tuple(value) if key in data or key not in ('inputs', 'outputs') else None
    bindings = (base / data["bindings"]).resolve() if isinstance(data.get("bindings"), str) else None
    if "bindings" in data and (bindings is None or not bindings.is_file()):
        raise MapError("bindings: требуется существующий файл наблюдений JSON")
    return Project(path, files, data["top"], standard, includes, defines, parameters, layout, tuple(contracts), bindings,
                   rows['inputs'], rows['outputs'], rows['modules'], rows['components'], rows['connections'],rows['labels'])
