"""Independent integer expectations for the image map and its arithmetic core."""
import argparse
from itertools import islice,product
import json
from pathlib import Path
import random
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/"src"))
from arrow_layout import bounds_of,depth_of,destinations,logic_core_metrics
from arrowasm import Cell
from mapdata import map_hash,read_map,write_map,write_json
from map_preview import render
from simulation import simulate
from test_harness import add_fixture,run_vectors,run_vector_batches
from protocol import FRAME,PHASES,manifest,scenario

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


def write_comparison(out,cells,meta,part,part_meta):
    def describe(cells,meta,function):
        result={"cells":len(cells),"bounds":bounds_of(cells),"map_hash":map_hash(cells),
                "function":function,"fixture_cells":sum(len(bits) for side in ("inputs","outputs") for bits in meta[side].values()),
                "state_cells":sum(c.type in (18,19) for c in cells.values()),
                "timing":{"kind":"word_protocol" if "operation_ticks" in meta else "settle_bound",
                          "ticks":meta.get("operation_ticks",meta.get("settle_ticks"))}}
        if 'logic_core' in meta:result['logic_core']=meta['logic_core']
        return result
    comparison={"schema":1,"profile":meta["profile"],"verified_against_current_game":False,
                "reference":describe(cells,meta,"a+b; stored inputs and serial transport"),
                "reference_core":describe(part,part_meta,"a+b; cin=0"),
                "comparison_scope":"Compare arrow counts of arithmetic cores. Full reference includes state and serial transport."}
    compiled_dir=ROOT/"examples/hdl/adder8/build"
    if (compiled_dir/"adder8.build.json").exists():
        compiled_meta=json.loads((compiled_dir/"adder8.build.json").read_text(encoding="utf-8"))
        compiled=read_map(compiled_dir/"adder8.map.json")
        if map_hash(compiled)!=compiled_meta["map_hash"]:
            raise ValueError("compiled adder manifest does not match its map")
        comparison["compiled_core"]=describe(compiled,compiled_meta,"a+b+cin")
        comparison["compiled_core"]["logic_sha256"]=compiled_meta["logic_sha256"]
        comparison["extra_compiled_cells"]={"count":len(compiled)-len(part),"reason":"Cin contact and separate Cout terminal"}
    write_json(out/"comparison.json",comparison)


def run(exhaustive=True,progress=None):
    out=HERE/"build"
    cells=read_map(out/"reference.map.json")
    assert cells==read_map(out/"reference.save.txt")
    meta=manifest(cells)
    meta["layout"]="compact-reference-image"
    meta["logic_nodes"]=sum(c.type in (16,17) for c in cells.values())
    meta["gate_labels"]=[{"at":list(p),"op":{16:"AND",17:"XOR",18:"REG",19:"TGL"}[c.type],"id":f"image:{p}"} for p,c in cells.items() if c.type in (16,17,18,19)]
    fixture=add_fixture(cells,meta)
    write_map(out,"reference.test",fixture)
    assert fixture==read_map(out/"reference.test.map.json")==read_map(out/"reference.test.save.txt")
    write_json(out/"reference.build.json",meta)
    rng=random.Random(14008)
    cases=[{"a":a,"b":b} for a,b in EXAMPLES]
    cases += [{"a":a,"b":b} for bit in range(8) for a,b in ((1<<bit,0),(0,1<<bit),(255,1<<bit),(0,0))]
    cases += [{"a":rng.randrange(256),"b":rng.randrange(256)} for _ in range(512)]
    test=scenario(meta,cases)
    write_json(out/"reference.scenario.json",test)
    write_json(out/"reference.cases.json",{"expectation":"Python a+b, independent of the image recognition","cases":cases})
    report=simulate(read_map(out/"reference.test.save.txt"),test,optimize_cycles=False)
    report.update(vectors=len(cases),operation_ticks=FRAME,truth_table=measure(meta,report,cases),production_cells=len(cells),fixture_cells=len(fixture)-len(cells))
    write_json(out/"reference.report.json",report)
    graph={"schema":1,"map_hash":map_hash(cells),"nodes":[{"at":list(p),"type":c.type,"rotation":c.rotation,"mirrored":c.mirrored,
          "targets":[list(q) for q in destinations(p,c) if q in cells],
          "open_ends":[list(q) for q in destinations(p,c) if q not in cells]} for p,c in sorted(cells.items())]}
    write_json(out/"reference.graph.json",graph)
    part,part_meta=core(cells)
    write_map(out,"reference.core",part)
    write_json(out/"reference.core.build.json",part_meta)
    write_comparison(out,cells,meta,part,part_meta)
    vectors=[{"inputs":case,"expect":{"sum":(case['a']+case['b'])&255,"cout":(case['a']+case['b'])>>8}} for case in cases]
    _,core_report=run_vectors(part,part_meta,vectors,out,"reference.core",compressed=True)
    render(read_map(out/"reference.save.txt"),meta,out/"reference.preview.png")
    render(read_map(out/"reference.test.save.txt"),meta,out/"reference.test.preview.png",report,report['truth_table'][:8])
    render(read_map(out/"reference.core.test.save.txt"),part_meta,out/"reference.core.preview.png",core_report,core_report['truth_table'][:8])
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
        write_json(out/"reference.exhaustive.report.json",summary)
        all_vectors=({"inputs":{"a":a,"b":b},"expect":{"sum":(a+b)&255,"cout":(a+b)>>8}} for a,b in product(range(256),range(256)))
        core_summary=run_vector_batches(part,part_meta,all_vectors,out,"reference.core")
        report['exhaustive']=summary
        report['core_exhaustive']=core_summary
        report['passed'] &= summary['passed'] and core_summary['passed']
    report['passed'] &= core_report['passed']
    write_json(out/"reference.report.json",report)
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument('--quick',action='store_true')
    args=parser.parse_args()
    r=run(not args.quick,progress=lambda s:print(f"reference: {s['vectors']}/65536, failures={s['failure_count']}",flush=True))
    print(f"reference passed={r['passed']}, cases={r['vectors']}, exhaustive={r.get('exhaustive',{}).get('vectors',0)}")
    raise SystemExit(0 if r['passed'] else 1)
