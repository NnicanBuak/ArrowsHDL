"""Small native arrow templates with shared, synchronized input branches.

Input contacts belong to the template. Route each signal to its contact; keep
the contact's existing outgoing links. Output fixtures are the first empty
positions after the output gates. Templates expose their gate positions so a
tile builder can observe native state directly, without reserving probe tails.
"""
from dataclasses import dataclass
from itertools import product
from collections import defaultdict

from arrowasm import Cell,MapError,validate_cell
from arrow_layout import destinations,bounds_of,depth_of
from simulation import simulate
from mapdata import map_hash


def replace_native_cells(cells,replacement,*,combinational=False):
    """Recompile a fixed native footprint while preserving every external edge."""
    footprint=set(replacement)
    if not footprint or not footprint<=cells.keys():
        raise MapError('Native replacement must occupy existing cells')
    for p,c in replacement.items():validate_cell(*p,c)
    updated=dict(cells);updated.update(replacement)
    def interfaces(current):
        return {(p,q) for p,c in current.items() for q in destinations(p,c)
                if q in current and ((p in footprint)!=(q in footprint))}
    if interfaces(cells)!=interfaces(updated):
        raise MapError('Native replacement changes an external connection')
    if combinational:depth_of(replacement)
    return updated


@dataclass
class Macro:
    cells: dict
    inputs: dict
    outputs: dict
    gates: dict

    def moved(self,x,y):
        shift=lambda p:(p[0]+x,p[1]+y)
        return Macro({shift(p):c for p,c in self.cells.items()},
                     {n:shift(p) for n,p in self.inputs.items()},
                     {n:shift(p) for n,p in self.outputs.items()},
                     {n:shift(p) for n,p in self.gates.items()})

    def rotated(self,turns):
        turns%=4
        def turn(p):
            x,y=p
            for _ in range(turns):x,y=-y,x
            return x,y
        return Macro({turn(p):Cell(c.type,(c.rotation+turns)%4,c.mirrored)
                      for p,c in self.cells.items()},
                     {n:turn(p) for n,p in self.inputs.items()},
                     {n:turn(p) for n,p in self.outputs.items()},
                     {n:turn(p) for n,p in self.gates.items()})

    def describe(self):
        return dict(arrows=len(self.cells),bounds=bounds_of(self.cells),
                    inputs=self.inputs,outputs=self.outputs,gates=self.gates,
                    map_hash=map_hash(self.cells))


def adder(full=True):
    """Five-arrow full adder / four-arrow half adder, two shared gate inputs.

    Both operations use the same signal forks. Native #16 is >=2, so it is
    AND for the half adder and majority for the full adder.
    """
    cells={(0,0):Cell(17,1),(0,1):Cell(16,1),
           (0,-1):Cell(12,2),(0,2):Cell(12,0)}
    inputs={'a':(0,-1),'b':(0,2)}
    if full:
        cells[(-1,1)]=Cell(14,1,True)
        inputs['cin']=(-1,1)
    return Macro(cells,inputs,{'sum':(1,0),'carry':(1,1)},
                 {'sum':(0,0),'carry':(0,1)})


def sticky_latch():
    """One synchronized fork drives both native SET pins; four arrows, 2x2."""
    cells={(0,0):Cell(7,1),(1,0):Cell(1,2),
           (0,1):Cell(1,1),(1,1):Cell(18,1)}
    return Macro(cells,{'trigger':(0,0)},{'state':(2,1)},
                 {'state':(1,1)})


def edge_detector(rising=True):
    """Shared fork + one-tick delay + native gate; three arrows, 2x2.

    Rising: NOT delay and AND gate. Both edges: BUF delay and XOR gate.
    The native pulse reaches the output fixture three ticks after the source.
    """
    cells={(0,0):Cell(14,2,True),
           (0,1):Cell(15 if rising else 1,1),
           (1,1):Cell(16 if rising else 17,1)}
    return Macro(cells,{'signal':(0,0)},{'pulse':(2,1)},
                 {'delay':(0,1),'pulse':(1,1)})


def column_edge_detector(rising=True):
    """Three arrows in one column; useful for adjacent display segment ports."""
    cells={(0,2):Cell(12,0),
           (0,1):Cell(15 if rising else 1,0),
           (0,0):Cell(16 if rising else 17,0)}
    return Macro(cells,{'signal':(0,2)},{'pulse':(0,-1)},
                 {'delay':(0,1),'pulse':(0,0)})


def level_timer(exponent):
    """One-shot monotone level after roughly 8 * 2**exponent ticks.

    The input is a permanent start level. A native eight-tick oscillator
    clocks a ripple counter; the last bit sets a sticky output. No reset is
    provided. Actual latency depends on start phase and ripple propagation,
    so use timer_latency_bounds() for the physical timing contract.
    """
    if type(exponent) is not int or not 0 <= exponent <= 20:
        raise ValueError('Timer exponent must be an integer from 0 to 20')
    cells={(0,0):Cell(15,1),(1,0):Cell(7,1),
           (1,1):Cell(1,3),(0,1):Cell(1,0),
           (4,1):Cell(16,1),(4,2):Cell(1,0),(4,3):Cell(1,0)}
    cells.update(edge_detector().moved(2,0).cells)
    gates={}
    for bit in range(exponent+1):
        x=5+3*bit
        cells[x,1]=Cell(12 if bit<exponent else 1,1)
        cells[x+1,1]=Cell(19,1);gates['bit'+str(bit)]=(x+1,1)
        if bit<exponent:cells[x+2,1]=Cell(16,1)
    latch=sticky_latch().moved(7+3*exponent,1)
    cells.update(latch.cells);gates['done']=latch.gates['state']
    return Macro(cells,{'start':(4,3)},{'done':latch.outputs['state']},gates)


def timer_latency_bounds(exponent):
    """Conservative start-fixture to done-fixture bounds, all clock phases."""
    nominal=8*(2**exponent)
    return {'min':nominal+2*exponent+1,'max':nominal+2*exponent+8}


def adder_groups(graph,scope_prefix=None):
    """Find compiler pairs that can share input forks without changing logic.

    Each result supplies the template, logical node objects, and pin/net
    bindings. An assembler removes both ordinary placements, places the
    template, routes each input net once to its named fork, and routes outputs
    from named output gate positions. Include output fixture cells as owned
    wires if the router requires a separate root after an ordinary gate.
    """
    buckets=defaultdict(list)
    for node in graph['nodes']:
        if scope_prefix and not node.get('scope','').startswith(scope_prefix):continue
        if len(node['inputs']) not in (2,3):continue
        if node['op'] not in ('XOR','AND','MAJ'):continue
        buckets[tuple(sorted(node['inputs']))].append(node)
    result=[]
    for nodes in buckets.values():
        xor=next((n for n in nodes if n['op']=='XOR'),None)
        if xor is None:continue
        full=len(xor['inputs'])==3
        carry=next((n for n in nodes if n['op']==('MAJ' if full else 'AND')),None)
        if carry is None:continue
        macro=adder(full)
        result.append(dict(macro=macro,nodes={'sum':xor,'carry':carry},
                           inputs=dict(zip(macro.inputs,xor['inputs'])),
                           outputs={'sum':xor['output'],'carry':carry['output']}))
    return result


def latch_groups(graph):
    """Bind native SET nodes whose two inputs are one synchronized trigger."""
    result=[]
    for node in graph['nodes']:
        if node['op']!='SET' or len(node['inputs'])!=2 or node['inputs'][0]!=node['inputs'][1]:continue
        result.append(dict(macro=sticky_latch(),nodes={'state':node},
                           inputs={'trigger':node['inputs'][0]},outputs={'state':node['output']}))
    return result


def edge_groups(graph, column_outputs=()):
    """Bind a dedicated BUF/NOT delay and its XOR/AND transition gate.

    Delay nodes used by additional consumers are excluded. The pulse node
    may be a panel output port; callers must retain its fixed panel position
    when placing the template rather than moving that interface silently.
    """
    nodes={n['output']:n for n in graph['nodes']};uses=defaultdict(int)
    for node in nodes.values():
        for net in node['inputs']:uses[net]+=1
    result=[];used=set()
    for pulse in nodes.values():
        if pulse['op'] not in ('XOR','AND') or len(pulse['inputs'])!=2:continue
        for delayed in pulse['inputs']:
            delay=nodes.get(delayed)
            if not delay or delayed in used or uses[delayed]!=1 or len(delay['inputs'])!=1:continue
            rising=pulse['op']=='AND'
            if delay['op']!=('NOT' if rising else 'BUF'):continue
            source=delay['inputs'][0]
            if source not in pulse['inputs']:continue
            macro=column_edge_detector(rising) if pulse['output'] in column_outputs else edge_detector(rising)
            result.append(dict(macro=macro,nodes={'delay':delay,'pulse':pulse},
                               inputs={'signal':source},outputs={'pulse':pulse['output']}))
            used.add(delayed);break
    return result


def validate_template(macro):
    """Reject unintended internal links and reciprocal arrow connections."""
    allowed=set(macro.outputs.values())
    for p,c in macro.cells.items():
        for q in destinations(p,c):
            if q not in macro.cells and q not in allowed:
                raise AssertionError(('unnamed output',p,q))
            if q in macro.cells and p in destinations(q,macro.cells[q]):
                raise AssertionError(('reciprocal connection',p,q))


def harness(macro):
    cells=dict(macro.cells);sources={}
    for name,(x,y) in macro.inputs.items():
        choices=[((x-1,y),1),((x,y-1),2),((x,y+1),0),((x+1,y),3)]
        forbidden=set(destinations((x,y),macro.cells[(x,y)]))|set(macro.outputs.values())
        p,rotation=next(((p,r) for p,r in choices if p not in cells and p not in forbidden),(None,None))
        if p is None:raise AssertionError(('no harness ingress',name,(x,y)))
        cells[p]=Cell(22,rotation);sources[name]=p
    for p in macro.outputs.values():
        if p in cells:raise AssertionError(('output collision',p))
        cells[p]=Cell(23,0)
    return cells,sources


def checked_native(cells,scenario):
    report=simulate(cells,scenario,optimize_cycles=False)
    if report['failures'] or (scenario.get('expect') and not report['passed']):
        raise AssertionError(report['failures'][:10])
    return report


def verify_adders(turns=0):
    summaries=[]
    for full in (False,True):
        macro=adder(full).rotated(turns);validate_template(macro)
        cells,sources=harness(macro);names=list(macro.inputs)
        patterns=list(product((0,1),repeat=len(names)))
        # Every ordered transition, including simultaneous changes of all bits.
        vectors=[v for first in patterns for second in patterns for v in (first,second)]
        hold=16
        report=checked_native(cells,dict(ticks=len(vectors)*hold,hold_ticks=hold,
            inputs=[dict(at=list(sources[n]),values=[v[i] for v in vectors]) for i,n in enumerate(names)],
            expect=[dict(at=list(macro.outputs['sum']),values=[sum(v)%2 for v in vectors]),
                    dict(at=list(macro.outputs['carry']),values=[int(sum(v)>=2) for v in vectors])]))
        summaries.append(dict(kind='full' if full else 'half',rotation=turns,**macro.describe(),
                              input_patterns=len(patterns),ordered_transitions=len(patterns)**2,
                              checked_samples=report['checked_samples']))
    return summaries


def verify_latch():
    macro=sticky_latch();validate_template(macro)
    cells={};inputs=[];expected=[]
    for i,(first,second) in enumerate(product((0,1),repeat=2)):
        piece=macro.moved(i*6,0);part,sources=harness(piece);cells.update(part)
        values=[0,first,second,0,0]
        state=0;wanted=[]
        for bit in values:state|=bit;wanted.append(state)
        inputs.append(dict(at=list(sources['trigger']),values=values))
        expected.append(dict(at=list(piece.outputs['state']),values=wanted))
    report=checked_native(cells,dict(ticks=5*16,hold_ticks=16,inputs=inputs,expect=expected))
    # A single source tick must set the latch and remain set after it ends.
    pulse_cells,sources=harness(macro)
    trace=[0]*5+[1]+[0]*14
    pulse_report=checked_native(pulse_cells,dict(ticks=len(trace),hold_ticks=1,
        inputs=[dict(at=list(sources['trigger']),values=trace)],expect=[],
        observe=[list(macro.gates['state'])]))
    actual=pulse_report['observations'][0]['values']
    first=next((i for i,bit in enumerate(actual) if bit),None)
    expected=[int(tick>=8) for tick in range(len(trace))]
    if actual!=expected:raise AssertionError(('latch pulse retention/timing',actual,expected))
    return dict(**macro.describe(),ordered_transitions=4,checked_samples=report['checked_samples'],
                single_tick_trigger_retained=True,set_tick=first)


def verify_edges(column=False):
    summaries=[]
    # All four ordered binary transitions plus consecutive one-tick edges.
    trace=[0]*5+[1]*5+[0]*5+[1,0,1,0,0,0,1,1,0]+[0]*6
    for rising in (False,True):
        macro=(column_edge_detector(rising) if column else edge_detector(rising));validate_template(macro)
        cells,sources=harness(macro)
        report=checked_native(cells,dict(ticks=len(trace),hold_ticks=1,
            inputs=[dict(at=list(sources['signal']),values=trace)],expect=[],
            observe=[list(macro.outputs['pulse'])]))
        actual=report['observations'][0]['values']
        expected=[0]*len(trace)
        for tick in range(3,len(trace)):
            now=trace[tick-3];before=trace[tick-4] if tick>=4 else 0
            expected[tick]=int(now and not before) if rising else now^before
        if actual!=expected:raise AssertionError(('edge timing',rising,actual,expected))
        summaries.append(dict(kind='rising' if rising else 'both',column=column,**macro.describe(),
                              checked_ticks=len(trace),source_to_fixture_ticks=3,
                              pulse_count=sum(actual)))
    return summaries


def verify_macros():
    return dict(passed=True,profile='GraphDLC-01232bd',
                adders=[summary for rotation in range(4) for summary in verify_adders(rotation)],
                latch=verify_latch(),edges=verify_edges(),column_edges=verify_edges(True))


if __name__=='__main__':
    import json
    print(json.dumps(verify_macros(),indent=2))
