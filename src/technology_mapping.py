"""Match Boolean full-adder cones to native parity and threshold gates.

This pass derives a separate technology graph; the original Yosys graph and
source stay intact. Extra observers on an intermediate net prevent its removal.
"""
from collections import Counter,defaultdict
from copy import deepcopy


def merge_duplicate_logic(netlist):
    """Share equivalent combinational cells, retaining every output terminal."""
    graph=deepcopy(netlist)
    terminals={entry['net'] for entries in graph['outputs'].values() for entry in entries}
    canonical,aliases,kept,rewrites={},{},[],[]
    for node in graph['nodes']:
        node['inputs']=[aliases.get(net,net) for net in node['inputs']]
        key=(node['op'],tuple(sorted(node['inputs']) if node['op'] in ('AND','OR','XOR','MAJ') else node['inputs']))
        if node['output'] not in terminals and key in canonical:
            shared=canonical[key]
            aliases[node['output']]=shared['output']
            rewrites.append({'removed':node['id'],'kept':shared['id'],'output':node['output'],'shared_net':shared['output']})
        else:
            canonical.setdefault(key,node)
            kept.append(node)
    graph['nodes']=kept
    for entries in graph.get('wire_names',{}).values():
        for entry in entries:entry['net']=aliases.get(entry['net'],entry['net'])
    for instance in graph.get('instances',[]):
        instance['nodes']=[node for node in instance['nodes'] if any(n['id']==node for n in kept)]
        for category in ('inputs','outputs'):
            for entries in instance[category].values():
                for entry in entries:entry['net']=aliases.get(entry['net'],entry['net'])
    return graph,rewrites


def map_native_gates(netlist):
    graph=deepcopy(netlist)
    by_net={n['output']:n for n in graph['nodes']}
    consumers=defaultdict(list)
    for node in graph['nodes']:
        for net in node['inputs']:consumers[net].append(node['id'])
    replacements,removed,rewrites={},{},[]
    for carry in graph['nodes']:
        if carry['op']!='OR' or len(carry['inputs'])!=2:continue
        branches=[by_net.get(net) for net in carry['inputs']]
        if any(n is None or n['op']!='AND' or len(n['inputs'])!=2 for n in branches):continue
        match=None
        for h,g in (branches,branches[::-1]):
            for pnet in h['inputs']:
                p=by_net.get(pnet)
                if p is None or p['op']!='XOR' or len(p['inputs'])!=2:continue
                a,b=p['inputs']
                if Counter(g['inputs'])!=Counter([a,b]):continue
                ci=next((n for n in h['inputs'] if n!=pnet),None)
                if ci is None:continue
                sums=[n for n in graph['nodes'] if n['op']=='XOR' and Counter(n['inputs'])==Counter([pnet,ci])]
                if len(sums)!=1:continue
                s=sums[0]
                if Counter(consumers[pnet])!=Counter([h['id'],s['id']]):continue
                if consumers[g['output']]!=[carry['id']] or consumers[h['output']]!=[carry['id']]:continue
                ids={p['id'],g['id'],h['id'],s['id'],carry['id']}
                if ids & (set(removed)|set(replacements)):continue
                match=p,g,h,s,a,b,ci
                break
            if match:break
        if match is None:continue
        p,g,h,s,a,b,ci=match
        replacements[s['id']]=dict(s,inputs=[a,b,ci],mapping='native-xor3')
        replacements[carry['id']]=dict(carry,op='MAJ',inputs=[a,b,ci],mapping='native-majority3')
        for node in (p,g,h):removed[node['id']]=True
        rewrites.append({'kind':'full_adder','a':a,'b':b,'cin':ci,'sum':s['output'],'cout':carry['output'],
                         'sum_id':s['id'],'cout_id':carry['id'],'removed':[p['id'],g['id'],h['id']]})
    graph['nodes']=[replacements.get(n['id'],n) for n in graph['nodes'] if n['id'] not in removed]
    # Re-establish dependency order after replacing cones, independently of Yosys IDs.
    available={e['net'] for es in graph['inputs'].values() for e in es}|{'const0','const1'}
    pending,ordered=graph['nodes'][:],[]
    while pending:
        ready=[n for n in pending if set(n['inputs'])<=available]
        if not ready:raise ValueError('Native technology mapping left an undriven net')
        for n in ready:
            ordered.append(n);available.add(n['output']);pending.remove(n)
    graph['nodes']=ordered
    return graph,rewrites
