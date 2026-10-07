"""Electrical nets and input ancestry for data-driven coloured circuit views."""
from collections import defaultdict
from arrow_layout import edges


def describe_signals(graph,cells,owners,gates):
    aliases=defaultdict(list)
    origins={"const0":set(),"const1":set()}
    for name,entries in graph['inputs'].items():
        for entry in entries:
            origins.setdefault(entry['net'],set()).add((name,entry['index']))
            aliases[entry['net']].append(f"{name}[{entry['index']}]")
    for name,entries in graph.get('wire_names',{}).items():
        for entry in entries:
            aliases[entry['net']].append(f"{name}[{entry['index']}]")
    for name,entries in graph['outputs'].items():
        for entry in entries:aliases[entry['net']].append(f"{name}[{entry['index']}]")
    for node in graph['nodes']:
        origins[node['output']]=set().union(*(origins[net] for net in node['inputs']))
    mapped={key:(gates[key]['output'] if key in gates else owner.removeprefix('constant:'))
            for key,owner in owners.items()}
    by_net={node['output']:node for node in graph['nodes']}
    gate_positions={node['id']:key for key,node in gates.items()}
    links=edges(cells)
    nets=[]
    for net in sorted(set(mapped.values())):
        node=by_net.get(net)
        points=sorted(key for key,n in mapped.items() if n==net)
        names=sorted(set(aliases[net]),key=lambda label:(label.count('.'),len(label),label))
        nets.append({'id':net,'label':names[0] if names else net,'aliases':names,
                     'origins':[{'bus':bus,'bit':bit} for bus,bit in sorted(origins.get(net,set()))],
                     'inputs':node['inputs'] if node else [],
                     'driver':dict(id=node['id'],op=node['op'],at=list(gate_positions[node['id']]),
                                   scope=node.get('scope','core'),source=node.get('origin')) if node and node['id'] in gate_positions else None,
                     'cells':[list(p) for p in points],
                     'edges':[[list(p),list(q)] for p in points for q in links[p]]})
    return {'schema':1,'input_buses':[{'name':name,'bits':[entry['index'] for entry in entries]}
                                    for name,entries in graph['inputs'].items()],
            'nets':nets}
