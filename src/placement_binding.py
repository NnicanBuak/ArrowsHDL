"""Reuse physical hints after synthesis renames or changes Boolean nets."""
import re


def rebind_positions(before,after,positions,*,fallback=(0,0)):
    def signatures(graph):
        nodes={n['output']:n for n in graph['nodes']};cache={};pending=set()
        def key(net):
            if net in cache:return cache[net]
            node=nodes.get(net)
            if node is None:return ('input',net)
            if node['op'] in ('SET','TOGGLE') or net in pending:return ('state',net)
            pending.add(net);inputs=[key(n) for n in node['inputs']];pending.remove(net)
            if node['op'] in ('AND','OR','XOR','MAJ','ATLEAST2'):inputs.sort(key=repr)
            cache[net]=(node['op'],tuple(inputs));return cache[net]
        for net in nodes:key(net)
        return cache
    oldkeys=signatures(before);newkeys=signatures(after);matches={}
    for net,key in oldkeys.items():
        if net in positions:matches.setdefault(key,[]).append(net)
    bound={name:list(p) for name,p in positions.items() if name in after['inputs']}
    renamed={}
    for node in after['nodes']:
        net=node['output']
        if net in positions and not re.fullmatch(r'n\d+',net):bound[net]=list(positions[net])
        elif newkeys[net] in matches:
            match=matches[newkeys[net]][0];bound[net]=list(positions[match]);renamed[net]=match
        else:
            points=[bound[n] for n in node['inputs'] if n in bound]
            bound[net]=[sum(p[i] for p in points)/len(points) for i in (0,1)] if points else list(fallback)
    return bound,renamed
