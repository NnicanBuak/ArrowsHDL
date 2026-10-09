"""Native behavioral audit, with a separate coordinate/tick oracle."""
from pathlib import Path
import importlib.util
from arrowasm import Cell
from arrow_layout import destinations
from compact_layout import wire_cell
from simulation import simulate
from mapdata import write_json


def fixture(kind,rotation=0,mirrored=False,origin=(0,0)):
    center=(0,0);receiver=Cell(kind,0,mirrored)
    output=set(destinations(center,receiver));cells={center:receiver};ports=[]
    candidates=[(-1,0),(1,0),(0,1),(0,-1),(-1,-1),(1,-1),(-1,1),(1,1),(-2,0),(2,0),(0,-2),(0,2)]
    for q in candidates:
        if q in output:continue
        dx,dy=q
        driver=wire_cell(q,{center})
        if abs(dx)+abs(dy)==1:
            cells[q]=Cell(22,driver.rotation);ports.append(q)
        else:
            cells[q]=driver
            source=(dx+(1 if dx>0 else -1),dy) if dx else (dx,dy+(1 if dy>0 else -1))
            step=wire_cell(source,{q})
            assert step.type==1
            cells[source]=Cell(22,step.rotation);ports.append(source)
    for q in output:
        assert q not in cells
        cells[q]=Cell(23,0)
    def point(p):
        x,y=p
        for _ in range(rotation):x,y=-y,x
        return x+origin[0],y+origin[1]
    cells={point(p):Cell(c.type,(c.rotation+rotation)%4,c.mirrored) for p,c in cells.items()}
    return cells,[point(p) for p in ports],point(center),[point(p) for p in output]


def audit():
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('audit_scalar',root/'tests/test_simulator.py')
    oracle_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(oracle_module)
    cells={};ports=[];observe=[];records=[];frames=2048;hold=5
    for kind in range(1,26):
        if kind==20:continue
        part,inputs,center,outputs=fixture(kind,origin=(kind*16,0));cells.update(part)
        for i,p in enumerate(inputs):ports.append(dict(at=list(p),values=[(mask>>i)&1 for mask in range(frames)]))
        observe += [center]+outputs
        records.append(dict(type=kind,input_contacts=len(inputs),center=list(center)))
    # The scalar oracle receives the full tick sequence, not the engine's graph.
    full=dict(ticks=frames*hold,inputs=[dict(at=p['at'],values=[v for v in p['values'] for _ in range(hold)]) for p in ports],
              expect=[dict(at=list(p)) for p in observe])
    expected=oracle_module.oracle(cells,full)
    case=dict(ticks=frames*hold,hold_ticks=hold,inputs=ports,
              observe=[list(p) for p in observe],
              expect=[dict(at=list(p),values=[vs[i*hold+hold-1] for i in range(frames)]) for p,vs in expected.items() if cells[p].type==23])
    result=simulate(cells,case,optimize_cycles=False,timeout=180)
    assert result['passed'],result['failures'][:8]
    # Explicit known truth checks at high fan-in, independently of the oracle.
    traces={tuple(p['at']):p['values'] for p in result['observations']}
    for p,vs in expected.items():assert traces[p]==[vs[i*hold+hold-1] for i in range(frames)],('native trace',p)
    for record in records:
        kind=record['type'];values=traces[tuple(record['center'])]
        if kind in (1,15,16,17):
            for mask,value in enumerate(values):
                count=(mask&((1<<record['input_contacts'])-1)).bit_count()
                truth={1:count>0,15:count==0,16:count>=2,17:count%2==1}[kind]
                assert value==int(truth),(kind,mask,value,count)
    # Check every transient tick as well as the settled mask samples.
    transient_case=dict(full,observe=[list(p) for p in observe],
        expect=[dict(at=list(p),values=vs) for p,vs in expected.items() if cells[p].type==23])
    transient=simulate(cells,transient_case,optimize_cycles=False,timeout=180)
    assert transient['passed'],transient['failures'][:8]
    for trace in transient['observations']:
        assert trace['values']==expected[tuple(trace['at'])],('transient trace',trace['at'])
    # Rotation and reflection of every deterministic type, with individual pulses.
    geometry={};inputs=[];outputs=[];geometry_cases=0
    for kind in range(1,26):
        if kind==20:continue
        for rotation in range(4):
            for mirrored in (False,True):
                part,src,center,taps=fixture(kind,rotation,mirrored,(geometry_cases%16*16,geometry_cases//16*16))
                geometry.update(part);outputs += [center]+taps
                for i,p in enumerate(src):inputs.append(dict(at=list(p),values=[int(t//4==i) for t in range(52)]))
                geometry_cases+=1
    case=dict(ticks=52,inputs=inputs,expect=[dict(at=list(p)) for p in outputs])
    truth=oracle_module.oracle(geometry,case)
    case['observe']=[list(p) for p in outputs]
    case['expect']=[dict(at=list(p),values=values) for p,values in truth.items() if geometry[p].type==23]
    rotated=simulate(geometry,case,optimize_cycles=False,timeout=180)
    assert rotated['passed'],rotated['failures'][:8]
    for trace in rotated['observations']:assert trace['values']==truth[tuple(trace['at'])],('rotation trace',trace['at'])
    # Random also covers all rotations/reflections, with seeded reproducibility.
    for rotation in range(4):
        for mirrored in (False,True):
            part,src,center,taps=fixture(20,rotation,mirrored)
            case=dict(ticks=1200,seed=3451,inputs=[dict(at=list(p),values=[0]*200+[1]*800+[0]*200) for p in src],
                      expect=[],observe=[list(center)]+[list(p) for p in taps])
            a=simulate(part,case,optimize_cycles=False);b=simulate(part,case,optimize_cycles=False)
            assert a['observations']==b['observations']
            values=a['observations'][0]['values']
            assert not any(values[:200]) and not any(values[1005:]) and set(values[210:990])=={0,1}
            for tap in a['observations'][1:]:assert tap['values'][1:]==values[:-1]
    # Run the feedback, pending-delay, input-contact and mapping regressions too.
    import sys,unittest
    sys.path.insert(0,str(root/'tests'))
    from test_native_rules import NativeRuleTests
    regressions=unittest.TestResult()
    unittest.defaultTestLoader.loadTestsFromTestCase(NativeRuleTests).run(regressions)
    assert regressions.wasSuccessful(),(regressions.errors,regressions.failures)
    report=dict(passed=True,profile='GraphDLC-01232bd',deterministic_types=records,
        input_masks=frames,geometry_cases=geometry_cases,geometry_ticks=52,
        deterministic_samples=result['checked_samples']+rotated['checked_samples'],
        transient_samples=transient['checked_samples'],every_transient_tick_checked=True,
        total_types=25,total_geometry_cases=geometry_cases+8,
        semantic_regressions=regressions.testsRun,
        random=dict(seeded_repeatability=True,zero_input_off=True,output_one_tick_later=True,geometry_cases=8),
        findings=['type 16 counts at least two active inputs; AND needs exactly two',
                  'type 17 computes parity of every active input',
                  'type 18: one input resets; at least two set; zero retain',
                  'type 19 toggles every active-input tick, not only on an edge',
                  'type 5 reads the cell behind, including pending delay state',
                  'reciprocal emissions are real feedback',
                  'ordinary inputs do not control types 2, 9 and 21; blockers do',
                  'a one-output receiver can use eleven distinct incoming contacts'],
        limitation='Pinned engine profile; passive buttons only; this does not certify current browser behavior')
    (root/'build').mkdir(exist_ok=True)
    write_json(root/'build/native-rules.audit.json',report)
    print('Native rule audit passed:',len(records)+1,'types;',report['deterministic_samples'],'samples',flush=True)
    return report


if __name__=='__main__':audit()
