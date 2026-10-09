"""Remove explicitly unused outputs and their unreachable computations."""
from copy import deepcopy
from arrowasm import MapError


def prune_outputs(graph,outputs,*,keep_nets=()):
    outputs=list(outputs)
    result=deepcopy(graph)
    for name in outputs:
        if name not in result['outputs']:raise MapError('Unknown output to prune: '+name)
        del result['outputs'][name]
    nodes={n['output']:n for n in graph['nodes']}
    inputs={e['net'] for es in graph['inputs'].values() for e in es}
    live=set();pending=list(keep_nets)+[e['net'] for es in result['outputs'].values() for e in es]
    while pending:
        net=pending.pop()
        if net in live:continue
        live.add(net)
        if net in nodes:pending.extend(nodes[net]['inputs'])
        elif net not in inputs and net not in ('const0','const1'):
            raise MapError('Undefined dependency: '+net)
    result['nodes']=[n for n in result['nodes'] if n['output'] in live]
    result['inputs']={name:kept for name,es in graph['inputs'].items()
                      if (kept:=[e for e in es if e['net'] in live])}
    result['_pruning']=dict(removed_outputs=list(outputs),
        dead_nets=sorted((nodes.keys()|inputs)-live),
        removed_nodes=len(graph['nodes'])-len(result['nodes']))
    return result


def forward_monotone_latches(graph,states,*,levels):
    """Replace SET relays for declared initial-zero, permanently rising levels.

    The caller supplies the temporal contract. Pulses and resettable signals
    must retain their latches; their equivalence cannot be inferred here.
    """
    states=list(states)
    result=deepcopy(graph);nodes={n['output']:n for n in result['nodes']}
    declared=set(levels)
    for state in states:
        node=nodes.get(state)
        if not node or node['op']!='SET' or len(node['inputs'])!=2 or node['inputs'][0]!=node['inputs'][1]:
            raise MapError('Not a shared-trigger SET relay: '+state)
        trigger=nodes.get(node['inputs'][0])
        if not trigger or trigger['op'] not in ('OR','BUF') or not trigger['inputs'] or not set(trigger['inputs'])<=declared:
            raise MapError('SET relay depends on undeclared level signals: '+state)
        node.update(op='OR',inputs=list(trigger['inputs']))
    result=prune_outputs(result,[])
    result['_monotone_relays']=dict(states=list(states),levels=sorted(declared),
        contract='initial zero; each input may rise once and stays high until map reload')
    return result


def fold_or_trees(graph,*,max_inputs=9,keep_nets=()):
    """Fold private OR trees into OR/NOR receivers; rebuild physical timing.

    This preserves Boolean levels, not arbitrary transient pulse waveforms.
    Shared intermediates and explicitly retained state/interface nets stay.
    """
    if type(max_inputs) is not int or max_inputs<1:raise MapError('Invalid native fan-in limit')
    result=deepcopy(graph);retained=set(keep_nets)
    retained.update(e['net'] for es in graph['outputs'].values() for e in es)
    folded=[]
    while True:
        nodes={n['output']:n for n in result['nodes']};uses={}
        for n in nodes.values():
            for net in set(n['inputs']):uses.setdefault(net,set()).add(n['output'])
        changed=False
        for node in list(nodes.values()):
            if node['op'] not in ('OR','NOT'):continue
            for net in list(node['inputs']):
                child=nodes.get(net)
                if not child or child['op']!='OR' or net in retained or uses[net]!={node['output']}:continue
                if node['output'] in child['inputs']:continue
                values=[]
                for source in node['inputs']:
                    for value in (child['inputs'] if source==net else [source]):
                        if value not in values:values.append(value)
                if len(values)>max_inputs:continue
                node['inputs']=values
                result['nodes']=[n for n in result['nodes'] if n['output']!=net]
                folded.append(dict(receiver=node['output'],removed=net,fanin=len(values)))
                changed=True;break
            if changed:break
        if not changed:break
    result['_or_folding']=dict(folded=folded,max_inputs=max_inputs,
        contract='Boolean levels; recompute timing and verify transient behavior after routing')
    return result


def compress_three_counts(graph,*,partials,outputs,scope='count/merge'):
    """Add three two-bit counts using a carry-save layer: eight native gates.

    Each partial is (parity,carry); every carry has weight two. Output net names
    stay stable. Shared or externally visible intermediate results prohibit
    replacing their arithmetic, rather than silently changing those results.
    """
    if len(partials)!=3 or any(len(p)!=2 for p in partials) or len(outputs)!=4:
        raise MapError('Three two-bit partial counts and four output bits required')
    result=deepcopy(graph)
    old=[n for n in result['nodes'] if n.get('scope')==scope]
    names={n['output'] for n in old};kept=set(outputs)
    if not kept<=names:raise MapError('Count output is outside the replaced arithmetic')
    for node in result['nodes']:
        if node not in old and any(n in names-kept for n in node['inputs']):
            raise MapError('Count intermediate is used outside its arithmetic')
    if any(e['net'] in names-kept for es in result['outputs'].values() for e in es):
        raise MapError('Count intermediate is externally visible')
    spare=[n['output'] for n in old if n['output'] not in kept]
    if len(spare)<4:raise MapError('No stable intermediate names available')
    a,b,c,d=spare[:4];lo,mid,hi,top=outputs
    parity=[p[0] for p in partials];carry=[p[1] for p in partials]
    definitions=[(lo,'XOR',parity),(a,'MAJ',parity),(b,'XOR',carry),(c,'MAJ',carry),
                 (mid,'XOR',[a,b]),(d,'AND',[a,b]),(hi,'XOR',[c,d]),(top,'AND',[c,d])]
    replacement=[dict(id=n,output=n,op=op,inputs=inputs,scope=scope) for n,op,inputs in definitions]
    first=next(i for i,n in enumerate(result['nodes']) if n in old)
    result['nodes']=result['nodes'][:first]+replacement+[n for n in result['nodes'][first:] if n not in old]
    result['_carry_save']=dict(old_merge_gates=len(old),new_merge_gates=len(replacement),partials=[list(p) for p in partials])
    return result


def forward_output_levels(graph,branches):
    """Change an explicitly selected output bank from edge pulses to levels.

    Receivers must be recompiled for level input, rather than native TOGGLE.
    This preserves the output data expression, not the old pulse waveform.
    """
    result=deepcopy(graph);nodes={n['output']:n for n in result['nodes']};aliases={};removed=set()
    for enable,delay,pulse in branches:
        b,c=nodes[delay],nodes[pulse]
        if b['op']!='BUF' or b['inputs']!=[enable] or c['op']!='XOR' or set(c['inputs'])!={enable,delay}:
            raise MapError('Not an output edge detector: '+pulse)
        users=[n for n in result['nodes'] if pulse in n['inputs']]
        if not users or any(n['op']!='BUF' or n['inputs']!=[pulse] for n in users):
            raise MapError('Pulse is used outside output terminals: '+pulse)
        if any(delay in n['inputs'] for n in result['nodes'] if n['output']!=pulse):
            raise MapError('Output delay is used elsewhere: '+delay)
        if any(e['net'] in (delay,pulse) for es in result['outputs'].values() for e in es):
            raise MapError('Edge detector is exposed outside its output terminals: '+pulse)
        aliases[pulse]=enable;removed.update((delay,pulse))
    for node in result['nodes']:node['inputs']=[aliases.get(n,n) for n in node['inputs']]
    result['nodes']=[n for n in result['nodes'] if n['output'] not in removed]
    result['_level_outputs']=dict(branches=len(branches),contract='continuous level receivers, not toggle registers')
    return result
