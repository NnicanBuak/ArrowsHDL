"""Logical HDL modules + declarative physical presentation = a complete scheme."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import tomllib

from arrowshdl.arrowasm import Cell, MapError
from arrowshdl.arrow_layout import bounds_of, destinations
from arrowshdl.fixed_wiring import FixedWiring
from arrowshdl.mapdata import map_hash, read_map, write_map, write_json, save_sha256
from arrowshdl.manifest import load_project, table, pair, component_file
from arrowshdl.presentation import attach_io, port_bits
from arrowshdl.verilog_compile import compile_file
from arrowshdl.components import move as _move, load_component, keepout
from arrowshdl.execution import bounded
from arrowshdl.progress import report


def _combine(project, out, timeout, layout, max_cells):
    cells, blocks, reserved, originals = {}, {}, set(), {}
    with tempfile.TemporaryDirectory(prefix='arrowshdl-modules-') as directory:
        for i,mod in enumerate(project.modules):
            part,meta = compile_file(project.sources, mod['hdl'], Path(directory)/str(i), timeout,
                max_cells, layout, standard=project.standard, include_dirs=project.include_dirs,
                defines=project.defines, parameters=mod.get('parameters', {}))
            at = mod.get('at', [i*200,0])
            part,meta = _move(part,meta,at)
            if mod['name'] in blocks:raise MapError('Duplicate instance name')
            if cells.keys() & part.keys() or reserved & part.keys():
                raise MapError(f"Overlapping module: {mod['name']}")
            cells.update(part)
            blocks[mod['name']] = meta
    for i,component in enumerate(project.components):
        name = component['name']
        if name in blocks:
            raise MapError(f'Duplicate instance name: {name}')
        part,meta = load_component(component_file(project.path.parent,component['file']), component.get('at', [0,200+100*i]), component.get('rotation',0))
        footprint=keepout(part)
        if cells.keys() & footprint or reserved & footprint:
            raise MapError(f'Overlapping compiled block: {name}')
        cells.update(part)
        reserved.update(footprint)
        originals[name]=part
        blocks[name] = meta
    for meta in blocks.values():
        for side in ('inputs','outputs'):
            for entries in meta[side].values():reserved.update(tuple(e['fixture']) for e in entries)
    def endpoint(value, side):
        if '.' not in value:
            raise MapError(f'Expected instance.port: {value}')
        block,port = value.split('.',1)
        if block not in blocks:
            raise MapError(f'Unknown instance: {block}')
        return port_bits(blocks[block][side],port)
    router, driven, nets = FixedWiring(cells,reserved), set(), {}
    router.max_cells=max_cells
    for connection in project.connections:
        source,target = endpoint(connection['from'],'outputs'),endpoint(connection['to'],'inputs')
        if len(source) != len(target):
            raise MapError(f"Incompatible width: {connection['from']} → {connection['to']}")
        for a,b in zip(source,target):
            contact = tuple(b['contact'])
            if contact in driven:
                raise MapError(f'Multiple drivers for {connection["to"]}')
            driven.add(contact)
            root = tuple(a['fixture'])
            nets.setdefault(root,[]).append((tuple(b['fixture']),contact))
    net_names={}
    for i,(source,targets) in enumerate(nets.items()):
        net_names[source]=f'connection:{i}'
        router.connection(net_names[source],source,targets)
    if nets:
        cells = router.route_all()
    free_inputs,free_outputs = {},{}
    default_outputs=[]
    incoming={}
    for p,c in cells.items():
        for target in destinations(p,c):incoming.setdefault(target,[]).append(p)
    probe_reserved=set(reserved)|set(cells)
    for name in blocks:
        for port,entries in blocks[name]['inputs'].items():
            unbound = [e for e in entries if tuple(e['contact']) not in driven]
            if unbound:
                free_inputs[name+'.'+port] = unbound
        for port,entries in blocks[name]['outputs'].items():
            free_outputs[name+'.'+port] = deepcopy(entries)
            for entry in free_outputs[name+'.'+port]:
                if tuple(entry['fixture']) in cells:
                    root=tuple(entry['fixture'])
                    net=net_names.get(root)
                    points=[p for p,n in router.owners.items() if n==net] if net else []
                    found=False
                    for contact in sorted(points,key=lambda p:(abs(p[0]-root[0])+abs(p[1]-root[1]),p)):
                        for rotation,(dx,dy) in enumerate(((0,-1),(1,0),(0,1),(-1,0))):
                            sensor=(contact[0]+dx,contact[1]+dy)
                            fixture=(contact[0]+2*dx,contact[1]+2*dy)
                            if sensor in probe_reserved or fixture in probe_reserved or incoming.get(fixture):continue
                            if any(cells[p].type==3 for p in incoming.get(sensor,())):continue
                            entry.update(contact=list(contact),fixture=list(fixture),rotation=0,
                                         sensor=dict(at=list(sensor),rotation=rotation))
                            probe_reserved.update((sensor,fixture));found=True;break
                        if found:break
                    if not found:raise MapError('No space for an independent probe: increase module spacing')
            if all('sensor' not in e for e in free_outputs[name+'.'+port]):
                default_outputs.append(dict(name=name+'.'+port,**{'from':name+'.'+port},widget='indicator'))
    meta = dict(schema=1,top=project.top,inputs=free_inputs,outputs=free_outputs,cells=len(cells),
                bounds=bounds_of(cells),map_hash=map_hash(cells),layout='composed-scheme',
                settle_ticks=sum(m.get('settle_ticks',0) for m in blocks.values())+len(cells)+2,
                instances={name:dict(inputs=m['inputs'],outputs=m['outputs']) for name,m in blocks.items()},
                default_outputs=default_outputs)
    for name,part in originals.items():
        if any(cells.get(p)!=c for p,c in part.items()):raise MapError(f'Internal scheme was modified: {name}')
    meta['components']={n:dict(source_map_hash=blocks[n]['source_map_hash'],
                             placed_map_hash=blocks[n]['placed_map_hash'],cells=len(part),
                             interface=blocks[n]['interface']) for n,part in originals.items()}
    # Connected component outputs remain endpoints for explicit display widgets.
    return cells,meta


@bounded
def build_scheme(path, out, *, timeout=600, layout='auto', max_cells=1000000, testing=False,compact=False):
    report(1, f'Reading project: {path}')
    project = load_project(Path(path))
    out = Path(out)
    if project.version==2:
        from arrowshdl.compiled_graph import assemble
        cells,meta = assemble(project,out,timeout,layout,max_cells,compact)
    elif project.modules or project.components:
        cells,meta = _combine(project,out,timeout,layout,max_cells)
    else:
        if project.layout.get('template'):
            from arrowshdl.verilog_frontend import elaborate
            from arrowshdl.structural import expand_logic,elaborate_template
            from arrowshdl.verilog_compile import emit_build
            raw,log=elaborate_template(project,project.path.parent/project.layout['template'],timeout)
            graph=expand_logic(raw,project.top,project.path.parent/project.layout['template'])
            cells,meta=emit_build(graph,list(project.sources),project.top,out,log,max_cells=max_cells,
                constraints=project.layout,bindings=project.bindings,standard=project.standard)
        else:
            cells,meta = compile_file(project.sources,project.top,out,timeout,max_cells,layout,
                project.layout.get('input_buses'),project.layout.get('input_bus_gap','auto'),
                standard=project.standard,include_dirs=project.include_dirs,defines=project.defines,
                parameters=project.parameters,constraints=project.layout,bindings=project.bindings,compact=compact)
    if meta['layout'] != 'fixed-native-verilog':
        report(92, 'Attaching input and output devices')
        inputs = [dict(row,to=row['name']) for row in project.inputs] if project.version==2 else project.inputs
        outputs = [dict(row,**{'from':row['name']}) for row in project.outputs] if project.version==2 else project.outputs
        cells,meta = attach_io(cells,meta,inputs,outputs,testing=testing)
    elif project.inputs or project.outputs:
        raise MapError('Fixed structural scheme widgets require its prepared template')
    elif testing:
        from arrowshdl.test_harness import add_fixture
        cells = add_fixture(cells,meta)
        meta['production_map_hash'] = meta['map_hash']
        meta.update(map_hash=map_hash(cells),cells=len(cells),bounds=bounds_of(cells),testing=True)
    if project.labels:
        from arrowshdl.lettering import attach_labels
        cells,meta=attach_labels(cells,meta,project.labels,project.path.parent)
    if len(cells) > max_cells:
        raise MapError('Scheme exceeds --max-cells')
    meta['project_version'] = project.version
    from arrowshdl.timing import verify_contracts
    report(96, 'Checking timing contracts and writing scheme')
    meta['timing_contracts'] = verify_contracts(cells,meta,project.timing)
    write_map(out,project.top,cells)
    meta['save_sha256'] = save_sha256(out / f'{project.top}.save.txt')
    write_json(out/f'{project.top}.build.json',meta)
    return cells,meta
