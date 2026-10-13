"""Independent integer expectations for the image map and its arithmetic core."""
import argparse
from itertools import islice,product
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = ROOT / 'tests/fixtures/circuits/reference_adder8'
from arrowshdl.arrow_layout import bounds_of,depth_of,logic_core_metrics
from arrowshdl.arrowasm import Cell
from arrowshdl.mapdata import map_hash,read_map,write_map
from arrowshdl.map_preview import render
from arrowshdl.simulation import simulate
from arrowshdl.test_harness import add_fixture,run_vectors,run_vector_batches
from tests.helpers.reference_adder8.protocol import FRAME,PHASES,manifest,scenario

EXAMPLES=[(0,0),(1,1),(127,1),(255,1),(255,255),(85,170),(128,128),(255,0)]


def measure(meta,report,cases):
    traces={tuple(p["at"]):p["values"] for p in report["outputs"]}
    rows=[]
    for i,case in enumerate(cases):
        actual={name:sum(traces[tuple(e["fixture"])][(i+1)*len(PHASES)-1]<<bit for bit,e in enumerate(entries)) for name,entries in meta["outputs"].items()}
        total=case["a"]+case["b"]
        expected={"sum":total&255,"cout":total>>8}
        rows.append({"inputs":case,"expected":expected,"actual":actual,"passed":actual==expected})
    return rows


def core(cells):
    # This is an exact subset of the reconstructed image, not a regenerated adder.
    part={p:c for p,c in cells.items() if 15<=p[0]<=30 and 7<=p[1]<=10}
    inputs={name:[{"index":bit,"contact":[30-2*bit,y],"fixture":[30-2*bit,fy],"rotation":rot} for bit in range(8)]
            for name,y,fy,rot in (("a",7,6,2),("b",10,11,0))}
    outputs={"sum":[{"index":bit,"contact":[29-2*bit,10],"fixture":[29-2*bit,11],"rotation":0} for bit in range(8)],
             "cout":[{"index":0,"contact":[15,9],"fixture":[13,9],"rotation":0}]}
    meta={"schema":1,"top":"reference_core","map_hash":map_hash(part),"profile":"GraphDLC-01232bd",
          "verified_against_current_game":False,"inputs":inputs,"outputs":outputs,"cells":len(part),
          "settle_ticks":depth_of(part)+2,"bounds":bounds_of(part),"layout":"compact-reference-core","gate_labels":
          [{"at":list(p),"op":"XOR3" if c.type==17 else "MAJ","id":f"image:{p}"} for p,c in part.items() if c.type in (16,17)]}
    gates={p:{"output":f"gate:{p}"} for p,c in part.items() if c.type in (16,17)}
    meta['logic_core']=logic_core_metrics(part,gates,set())
    return part,meta


def run(exhaustive=True,progress=None):
    out=HERE/"build"
    cells=read_map(out/"reference.save.txt")
    meta=manifest(cells)
    meta["layout"]="compact-reference-image"
    meta["logic_nodes"]=sum(c.type in (16,17) for c in cells.values())
    meta["gate_labels"]=[{"at":list(p),"op":{16:"AND",17:"XOR",18:"REG",19:"TGL"}[c.type],"id":f"image:{p}"} for p,c in cells.items() if c.type in (16,17,18,19)]
    fixture=add_fixture(cells,meta)
    rng=random.Random(14008)
    cases=[{"a":a,"b":b} for a,b in EXAMPLES]
    cases += [{"a":a,"b":b} for bit in range(8) for a,b in ((1<<bit,0),(0,1<<bit),(255,1<<bit),(0,0))]
    cases += [{"a":rng.randrange(256),"b":rng.randrange(256)} for _ in range(512)]
    test=scenario(meta,cases)
    report=simulate(fixture,test,optimize_cycles=False)
    report.update(vectors=len(cases),operation_ticks=FRAME,truth_table=measure(meta,report,cases),production_cells=len(cells),fixture_cells=len(fixture)-len(cells))
    part,part_meta=core(cells)
    write_map(out,"reference.core",part)
    vectors=[{"inputs":case,"expect":{"sum":(case['a']+case['b'])&255,"cout":(case['a']+case['b'])>>8}} for case in cases]
    _,core_report=run_vectors(part,part_meta,vectors,out,"reference.core",compressed=True)
    render(cells,meta,out/"reference.preview.png")
    render(fixture,meta,out/"reference.test.preview.png",report,report['truth_table'][:8])
    render(add_fixture(part,part_meta),part_meta,out/"reference.core.preview.png",core_report,core_report['truth_table'][:8])
    if exhaustive:
        summary={"passed":True,"vectors":0,"checked_samples":0,"ticks":0,"batches":0,"failure_count":0,"failures":[],
                 "operation_ticks":FRAME,"map_hash":map_hash(cells),"profile":meta['profile'],"verified_against_current_game":False}
        iterator=iter(product(range(256),range(256)))
        while pairs:=list(islice(iterator,4096)):
            batch=[{"a":a,"b":b} for a,b in pairs]
            r=simulate(fixture,scenario(meta,batch),optimize_cycles=False)
            for field in ('ticks','checked_samples','failure_count'):summary[field]+=r[field]
            summary['passed'] &= r['passed']
            summary['vectors']+=len(batch)
            summary['batches']+=1
            summary['failures']=(summary['failures']+r['failures'])[:100]
            if progress:progress(summary)
        all_vectors=({"inputs":{"a":a,"b":b},"expect":{"sum":(a+b)&255,"cout":(a+b)>>8}} for a,b in product(range(256),range(256)))
        core_summary=run_vector_batches(part,part_meta,all_vectors,out,"reference.core")
        report['exhaustive']=summary
        report['core_exhaustive']=core_summary
        report['passed'] &= summary['passed'] and core_summary['passed']
    report['passed'] &= core_report['passed']
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument('--quick',action='store_true')
    args=parser.parse_args()
    r=run(not args.quick,progress=lambda s:print(f"reference: {s['vectors']}/65536, failures={s['failure_count']}",flush=True))
    print(f"reference passed={r['passed']}, cases={r['vectors']}, exhaustive={r.get('exhaustive',{}).get('vectors',0)}")
    raise SystemExit(0 if r['passed'] else 1)
