"""Map pure native computations using a separately versioned physical template.

The HDL determines every operator and connection. Templates contain position,
wire shape and presentation cells. They cannot redefine a computation.
"""
from pathlib import Path
import json
import tomllib

from arrowshdl.arrowasm import MapError
from arrowshdl.physical import parameter,place_physical
from arrowshdl.manifest import table


def logic_operation(type_id):
    if type_id in (1,6,7,8,10,11,12,13,14,23):
        return 1
    return type_id


def expand_logic(raw,top,template_path):
    """Expand compiled modules; geometry and external I/O are in the template."""
    template_path=Path(template_path).resolve()
    data=tomllib.loads(template_path.read_text(encoding='utf-8-sig'))
    if type(data.get('version')) is not int or data['version'] != 1:
        raise MapError('Неизвестная версия шаблона размещения')
    table(data,{'version','modules','instances','interfaces'},'physical template')
    definitions={}
    for item in data.get('modules',[]):
        table(item,{'hdl','geometry','source'},'template.modules')
        geometry=json.loads((template_path.parent/item['geometry']).read_text(encoding='utf-8-sig'))
        if geometry.get('version') != 1:
            raise MapError('Неизвестная версия геометрии')
        definitions[item['hdl']]=geometry
    origins={item['path']:item['at'] for item in data.get('instances',[])}
    modules=raw['modules'];records=[];counter=0;wire_union={}

    def canonical(net):
        while net in wire_union:
            net=wire_union[net]
        return net

    def walk(kind,prefix,ports,origin,stack):
        nonlocal counter
        if kind in stack:raise MapError('Рекурсивный модуль')
        module=modules[kind]
        original=module.get('attributes',{}).get('hdlname',kind).split(' ')[0]
        if original not in definitions:
            original=kind.split('$')[0]
        geometry=definitions.get(original)
        if geometry is None:raise MapError(f'Для {kind} отсутствует геометрия')
        coords=geometry.get('cells',{})
        views=geometry.get('presentation',[])
        wires=dict(ports)
        aliases={}
        for cell in module.get('cells',{}).values():
            if cell['type']=='$buf':aliases.update(zip(cell['connections']['Y'],cell['connections']['A']))
        def local(bit):
            seen=set()
            while bit in aliases:
                if bit in seen:raise MapError('Цикл псевдонимов')
                seen.add(bit);bit=aliases[bit]
            return bit
        for key,value in ports.items():
            base=local(key)
            if type(base) is int:
                if base in wires and wires[base] != value:
                    wire_union[value]=wires[base]
                wires[base]=value
        def wire(bit):
            nonlocal counter
            bit=local(bit)
            if type(bit) is str:
                if bit not in ('0','1'):raise MapError('Неопределённый бит HDL')
                return bit
            if bit not in wires:counter+=1;wires[bit]=counter
            return wires[bit]
        used=set()
        for name,cell in sorted(module.get('cells',{}).items()):
            full=prefix+name;kind2=cell['type']
            if kind2 in ('$buf','$scopeinfo'):continue
            connections={p:[wire(v) for v in bits] for p,bits in cell['connections'].items()}
            if kind2=='arrows_logic':
                layout=coords.get(name)
                if layout is None:raise MapError(f'{full}: отсутствует размещение')
                used.add(name)
                op=parameter(cell.get('parameters',{}).get('OP'),1)
                if op != logic_operation(layout['type']):
                    raise MapError(f'{full}: физический тип не реализует операцию HDL {op}')
                records.append(dict(id=full,at=[layout['at'][0]+origin[0],layout['at'][1]+origin[1]],type=layout['type'],
                    rotation=layout['rotation'],mirrored=layout.get('mirrored',False),connections=connections))
            elif kind2 in modules and not modules[kind2].get('attributes',{}).get('blackbox'):
                child=modules[kind2];mapping={}
                for port,desc in child.get('ports',{}).items():
                    if port not in connections or len(desc['bits'])!=len(connections[port]):raise MapError(f'{full}: несовместимый интерфейс')
                    mapping.update((a,b) for a,b in zip(desc['bits'],connections[port]) if type(a) is int)
                offset=origins.get(full,[0,0])
                walk(kind2,full+'.',mapping,(origin[0]+offset[0],origin[1]+offset[1]),(*stack,kind))
            else:raise MapError(f'{full}: ожидается стандартная нативная вычислительная операция')
        if used != set(coords):raise MapError(f'{kind}: геометрия содержит отсутствующие вычисления')
        for i,view in enumerate(views):
            port=view.get('port')
            if port:
                desc=module.get('ports',{}).get(port)
                if desc is None or desc['direction']!='input':raise MapError('Представление должно подавать сигнал на input HDL')
                bit=wire(desc['bits'][view.get('index',0)])
                connections=dict(I=['0']*11,B=['0']*11,S=['0'],O=[bit])
            else:
                counter+=1;connections=dict(I=['0']*11,B=['0']*11,S=['0'],O=[counter])
            if view['type'] not in (21,24,25):raise MapError('Представление не может добавлять вычислительные операции')
            records.append(dict(id=prefix+'view:'+str(i),at=[view['at'][0]+origin[0],view['at'][1]+origin[1]],
                type=view['type'],rotation=view['rotation'],mirrored=view.get('mirrored',False),connections=connections))
        return {name:dict(desc,bits=[wire(v) for v in desc['bits']]) for name,desc in module.get('ports',{}).items()}
    port_map=walk(top,'',{},(0,0),())
    for item in records:
        item['connections']={p:[canonical(v) for v in values] for p,values in item['connections'].items()}
    # A prepared control may contain several button squares. Their collection
    # network is presentation data, including native propagation among squares.
    from arrowshdl.arrowasm import Cell
    from arrowshdl.physical import dependencies
    cells={tuple(n['at']):Cell(n['type'],n['rotation'],n['mirrored']) for n in records}
    links=dependencies(cells)
    signals={tuple(n['at']):n['connections']['O'][0] for n in records}
    for item in records:
        if '.view:' in item['id'] or item['id'].startswith('view:'):
            for port in ('I','B','S'):
                width=1 if port=='S' else 11
                values=[signals[p] for p in sorted(links[tuple(item['at'])][port])]
                if len(values)>width:raise MapError('Слишком много контактов у виджета')
                item['connections'][port]=values+['0']*(width-len(values))
    return dict(schema=1,top=top,kind='physical',creator=raw.get('creator'),ports=port_map,nodes=records)


def elaborate_template(project,template_path,timeout):
    """Compile reusable HDL units once, then link their real module interfaces.

    Avoid elaborating thousands of repeated stateful instances in a WASI
    address space. The computation objects are RTLIL, not saved arrow maps.
    """
    from arrowshdl.verilog_frontend import elaborate
    template_path=Path(template_path).resolve()
    template=tomllib.loads(template_path.read_text(encoding='utf-8-sig'))
    rows=template.get('modules',[])
    names=[row['hdl'] for row in rows]
    available=set(project.sources)
    units=[row for row in rows if 'source' in row and (template_path.parent/row['source']).resolve() in available]
    if not units:
        return elaborate(project.sources,project.top,timeout,standard=project.standard,
            include_dirs=project.include_dirs,defines=project.defines,parameters=project.parameters)
    merged={};logs=[];creator=None
    for row in units:
        sources=project.sources
        defines=project.defines
        if template.get('interfaces'):
            sources=[template_path.parent/template['interfaces'],template_path.parent/row['source']]
            defines=(*defines,'ARROWSHDL_UNIT_'+row['hdl'])
        raw,log=elaborate(sources,row['hdl'],timeout,standard=project.standard,
            include_dirs=project.include_dirs,defines=defines,parameters=project.parameters if row['hdl']==project.top else {},
            blackbox_modules=[name for name in names if name!=row['hdl']])
        logs.append(log);creator=raw.get('creator')
        for name,module in raw['modules'].items():
            if module.get('attributes',{}).get('blackbox'):
                merged.setdefault(name,module)
            else:
                module.get('attributes',{}).pop('top',None)
                merged[name]=module
    if project.top not in merged:raise MapError('В объектных модулях отсутствует верхняя логика')
    merged[project.top].setdefault('attributes',{})['top']='1'
    return {'modules':merged,'creator':creator},'\n'.join(logs)
