"""Persistent compiled modules: synthesis and placement once per specialization."""
import hashlib
import json
import os
import tempfile
from pathlib import Path

from arrowshdl import __version__
from arrowshdl.arrowasm import MapError
from arrowshdl.mapdata import read_map,map_hash,write_json
from arrowshdl.verilog_compile import compile_file


def component_document(top,meta):
    result=dict(version=1,map=f'{top}.map.json',ports={side:{name:[{key:e[key] for key in ('index','contact','fixture','rotation','panel') if key in e} for e in entries]
        for name,entries in meta[side].items()} for side in ('inputs','outputs')},
        settle_ticks=meta['settle_ticks'],state_boundaries=meta.get('timing',{}).get('state_boundaries',[]),
        interface=dict(kind='compiled HDL module',protocol='native game ticks',bit_order='port indices'))
    if meta.get('panel'):result['panel']=meta['panel']
    return result


def compiled_module(project,module,out,timeout,layout,max_cells,compact):
    headers = {}
    for directory in (*project.include_dirs,*{p.parent for p in project.sources}):
        for path in sorted(directory.rglob('*')):
            if path.is_file() and path.suffix in ('.vh','.svh','.h','.inc'):
                headers[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    compiler = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob('*.py')):
        if path.name in ('compiled_graph.py','project_graph.py','graph_components.py'): continue
        compiler.update(path.read_bytes())
    compiler.update((Path(__file__).parent/'library/arrows.v').read_bytes())
    identity = dict(version=__version__,compiler=compiler.hexdigest(),hdl=module['hdl'],
        sources=[dict(name=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in project.sources],
        headers=headers,parameters=module.get('parameters',{}),standard=project.standard,
        defines=list(project.defines),layout=layout,compact=compact,panel=module.get('panel'))
    key = hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    from arrowshdl.artifacts import document, unpack
    from arrowshdl.progress import report
    default = Path(os.environ.get('LOCALAPPDATA', Path.home()/'.cache'))/'ArrowsHDL'/'cache'
    folder = Path(os.environ.get('ARROWSHDL_CACHE_DIR', default)).expanduser()
    cached = folder/f'{key}.json'
    if cached.is_file():
        try:
            info = json.loads(cached.read_text(encoding='utf-8'))
            cells,meta = unpack(info['scheme'])
            if info.get('identity')==identity and map_hash(cells)==meta['map_hash'] and len(cells)<=max_cells:
                report(100, f"Reused compiled module {module['hdl']}")
                return cells,meta,dict(key=key,reused=True,path=str(cached))
        except (ValueError, KeyError, MapError):
            pass
    with tempfile.TemporaryDirectory(prefix='arrowshdl-module-') as directory:
        cells,meta = compile_file(project.sources,module['hdl'],directory,timeout,max_cells,layout,
            standard=project.standard,include_dirs=project.include_dirs,defines=project.defines,
            parameters=module.get('parameters',{}),compact=compact,
            constraints={'panel':module['panel'],'base':str(project.path.parent)} if module.get('panel') else None)
    folder.mkdir(parents=True,exist_ok=True)
    temporary = folder/f'{key}.{os.getpid()}.tmp'
    write_json(temporary,dict(identity=identity,key=key,scheme=document(cells,meta)))
    temporary.replace(cached)
    return cells,meta,dict(key=key,reused=False,path=str(cached))
