"""Derive the physical module graph from the elaborated HDL hierarchy."""
from collections import defaultdict
from types import SimpleNamespace

from arrowshdl.arrowasm import MapError
from arrowshdl.verilog_frontend import elaborate


class _Signals:
    def __init__(self): self.parent = {}
    def find(self, item):
        self.parent.setdefault(item, item)
        if self.parent[item] != item: self.parent[item] = self.find(self.parent[item])
        return self.parent[item]
    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a == b: return
        if a[0] == 'constant' and b[0] == 'constant':
            raise MapError('Conflicting constant drivers in HDL hierarchy')
        if b[0] == 'constant': a,b=b,a
        self.parent[b] = a
    def net(self, scope, bit):
        if bit in ('0','1'): return self.find(('constant',bit))
        return self.find((scope,bit))


def _hdl_name(raw, kind):
    attrs = raw.get('modules',{}).get(kind,{}).get('attributes',{})
    name = attrs.get('hdlname')
    if isinstance(name,str): return name.split()[0]
    # Yosys encodes parameterized specializations as module$parent.instance.
    if '$' in kind and '.' in kind.split('$',1)[1]: return kind.split('$',1)[0]
    return kind


def _parameter_value(value):
    if type(value) is int: return value
    if isinstance(value,str) and value and set(value) <= {'0','1'}: return int(value,2)
    return value


def _is_arrow_primitive(kind):
    return kind.startswith('arrows_') or (kind.startswith('$paramod') and 'arrows_' in kind)


def _module_is_composite(raw, kind):
    module = raw['modules'][kind]
    children = False
    for cell in module.get('cells',{}).values():
        cell_kind = cell['type']
        if cell_kind in ('$scopeinfo','$buf'): continue
        if cell_kind in raw['modules'] and not _is_arrow_primitive(cell_kind):
            children = True
        else:
            return False
    return children


def derive_project(project, timeout):
    """Elaborate hierarchy and produce the graph consumed by the block placer.

    Modules that contain logic are compiled as immutable blocks. Pure structural
    wrappers are traversed so generate arrays and their signal aliases become
    explicit block connections without a second manifest-level netlist.
    """
    raw, _ = elaborate(project.sources, project.top, timeout, standard=project.standard,
        include_dirs=project.include_dirs, defines=project.defines, parameters=project.parameters)
    if project.top not in raw.get('modules',{}): raise MapError(f'HDL top module not found: {project.top}')
    if any(cell['type']=='arrows_cell' or cell['type'].startswith('$paramod') and 'arrows_cell' in cell['type']
           for module in raw['modules'].values() for cell in module.get('cells',{}).values()):
        from arrowshdl.physical import normalize_physical_hierarchy
        return SimpleNamespace(physical_graph=normalize_physical_hierarchy(raw,project.top,project.layout))
    modules = raw['modules']; signals = _Signals()
    leaves=[]; active=[]
    def descend(kind, scope, port_bindings, stack):
        if kind in stack: raise MapError('Recursive HDL module hierarchy: '+' -> '.join((*stack,kind)))
        module=modules[kind]
        for cell in module.get('cells',{}).values():
            if cell['type'] == '$buf':
                a,y=cell.get('connections',{}).get('A',()),cell.get('connections',{}).get('Y',())
                if len(a)!=len(y): raise MapError(f'{scope or kind}: invalid HDL alias width')
                for left,right in zip(a,y): signals.union(signals.net(scope,left),signals.net(scope,right))
        if _module_is_composite(raw,kind):
            for instance,cell in sorted(module.get('cells',{}).items()):
                child_kind=cell['type']
                if child_kind in ('$scopeinfo','$buf') or child_kind not in modules or _is_arrow_primitive(child_kind):
                    continue
                child_scope=instance if not scope else scope+'.'+instance
                child=modules[child_kind]
                connections=cell.get('connections',{})
                for port,desc in child.get('ports',{}).items():
                    values=connections.get(port)
                    if values is None or len(values)!=len(desc['bits']):
                        raise MapError(f'{child_scope}.{port}: missing or incompatible HDL port connection')
                    for internal,external in zip(desc['bits'],values):
                        signals.union(signals.net(child_scope,internal),signals.net(scope,external))
                descend(child_kind,child_scope,cell.get('parameters',{}),(*stack,kind))
            return
        actual=_hdl_name(raw,kind)
        params={key:_parameter_value(value) for key,value in module.get('parameter_default_values',{}).items()}
        params.update({key:_parameter_value(value) for key,value in port_bindings.items()})
        # Specializations carry the instance overrides; defaults alone are not enough.
        leaves.append(dict(name=scope or project.top,hdl=actual,parameters=params,rtlil_kind=kind))
        active.append((kind,scope or project.top,scope))

    descend(project.top,'',{},())
    if not leaves: raise MapError('HDL hierarchy contains no compilable module instances')

    public_inputs=[]; public_outputs=[]
    top=modules[project.top]
    for name,desc in sorted(top.get('ports',{}).items()):
        indices=list(range(desc.get('offset',0),desc.get('offset',0)+len(desc['bits'])))
        if desc.get('upto'): indices.reverse()
        bits=[signals.net('',bit) for bit in desc['bits']]
        if desc['direction']=='input': public_inputs.append((name,indices,bits))
        elif desc['direction']=='output': public_outputs.append((name,indices,bits))
        else: raise MapError(f'Bidirectional HDL port is unsupported: {name}')

    leaf_ports={}; drivers=defaultdict(list); sinks=[]; transparent=set()
    for kind,instance_scope,signal_scope in active:
        module=modules[kind]; row=next(item for item in leaves if item['name']==instance_scope)
        row['_kind']=kind
        ports={'inputs':{},'outputs':{}}
        for name,desc in sorted(module.get('ports',{}).items()):
            indices=list(range(desc.get('offset',0),desc.get('offset',0)+len(desc['bits'])))
            if desc.get('upto'): indices.reverse()
            bits=[signals.net(signal_scope,bit) for bit in desc['bits']]
            side='inputs' if desc['direction']=='input' else 'outputs'
            ports[side][name]=list(zip(indices,bits))
            for index,net in zip(indices,bits):
                ref=f'{instance_scope}.{name}[{index}]'
                if side=='outputs': drivers[net].append(ref)
                else: sinks.append((net,ref))
        row['_ports']=ports
        input_nets={net for values in ports['inputs'].values() for _,net in values}
        for name,values in ports['outputs'].items():
            if any(net in input_nets for _,net in values):
                transparent.add(f'{instance_scope}.{name}')

    input_rows=[]; input_sources={}
    for name,indices,bits in public_inputs:
        if indices != list(range(len(indices))):
            raise MapError(f'{name}: public vectors must use zero-based indices')
        input_rows.append(dict(name=name,width=len(bits)))
        for index,net in enumerate(bits): drivers[net].append(f'{name}[{index}]')

    output_rows=[]; output_sources={}
    def sole_driver(net, context):
        root=signals.find(net)
        if root[0]=='constant': return root[1]
        raw_choices=drivers.get(root,[])
        choices=[item for item in raw_choices if item.rsplit('[',1)[0] not in transparent]
        # A lone output remains the block's driver even when optimization
        # makes it share a net with one of that block's input pins.
        if not choices and raw_choices: choices=raw_choices
        public=[item for item in choices if '.' not in item]
        # An HDL output may be a transparent alias of a public input. In that
        # case the public source already carries the exact signal into the graph.
        if len(public)==1: return public[0]
        if len(public)>1: raise MapError(f'{context}: HDL signal has multiple public drivers')
        if len(choices)!=1: raise MapError(f'{context}: HDL signal has {len(choices)} drivers: {", ".join(choices) or "none"}')
        return choices[0]
    for name,indices,bits in public_outputs:
        if indices != list(range(len(indices))):
            raise MapError(f'{name}: public vectors must use zero-based indices')
        refs=[]
        for net in bits:
            refs.append(sole_driver(net,name))
        output_rows.append(dict(name=name,width=len(bits)))
        output_sources[name]=refs

    connections=[]
    for net,target in sinks:
        source=sole_driver(net,target)
        if source!=target: connections.append({'from':source,'to':target})

    design=project.design or {'ports':(),'views':(),'components':(),'labels':(),'placement':{}}
    def selector_regex(pattern):
        import re
        return re.compile('^'+re.escape(pattern).replace(r'\[\*\]',r'\[\d+\]').replace(r'\*',r'[^.]+')+'$')
    for view in design['views']:
        matcher=selector_regex(view['select'])
        matches=[row for row in leaves if matcher.fullmatch(row['name'])]
        if not matches: raise MapError(f"design.views.select matched no HDL instances: {view['select']}")
        panel={'button':view['button'],'size':view.get('size',[7,7])}
        for side in ('left','right'):
            item=view.get(side)
            if item:
                panel[side]={'port':item['port']}
                if 'component' in item: panel[side]['file']=item['component']
                else: panel[side]['bitmap']=item['bitmap']
        for row in matches:
            for side,item in (('inputs',{'button':panel['button']}),('outputs',{s:panel[s]['port'] for s in ('left','right') if s in panel})):
                ports=row['_ports'][side]
                for port in item.values():
                    if port not in ports: raise MapError(f"{row['name']}: design view references missing {side[:-1]} {port}")
                if side=='inputs' and len(ports[panel['button']])!=1:
                    raise MapError(f"{row['name']}.{panel['button']}: design view button must be scalar")
            row['panel']=panel

    component_rows=[]
    for component in design['components']:
        row={key:value for key,value in component.items() if key not in ('bind','at','rotation')}
        if 'file' in row and not row['file'].startswith('library:'): row['file']=str((project.design_path.parent/row['file']).resolve())
        if 'at' in component: row['at']=component['at']
        if 'rotation' in component: row['rotation']=component['rotation']
        component_rows.append(row)
        binding=component.get('bind')
        if isinstance(binding,str):
            connections.append({'from':binding,'to':component['name']+'.signal'})
        elif isinstance(binding,dict):
            for port,source in binding.items(): connections.append({'from':source,'to':component['name']+'.'+port})

    for row in leaves:
        row.pop('_kind',None);row.pop('_ports',None)
    # Per-port output aliases let a single public HDL bus span several blocks.
    output_rows_for_graph=[dict(row,**{'from':row['name']}) for row in output_rows]
    return SimpleNamespace(path=project.path,design_path=project.design_path,top=project.top,version=3,
        sources=project.sources,include_dirs=project.include_dirs,standard=project.standard,
        defines=project.defines,parameters=project.parameters,layout=design.get('placement',{}),
        timing=project.timing,bindings=project.bindings,modules=tuple(leaves),components=tuple(component_rows),
        connections=tuple(connections),inputs=tuple(input_rows),outputs=tuple(output_rows_for_graph),hierarchy_raw=raw,
        labels=tuple(design['labels']),output_sources=output_sources,design=design)
