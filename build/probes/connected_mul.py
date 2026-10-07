import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from technology_mapping import map_native_gates,merge_duplicate_logic
from packed_layout import arrange_packed
from compact_layout import Router
from arrow_layout import logic_core_metrics
from arrowasm import MapError
graph=json.loads((ROOT/'examples/hdl/candidates/mul4/build/mul4.logic.json').read_text())
graph,_=map_native_gates(graph);graph,_=merge_duplicate_logic(graph)
for aspect in (1.8,2.0,2.2,2.8,3.0,3.5):
    for gap in (0,1,2):
        started=time.perf_counter()
        try:
            placement,blocks=arrange_packed(graph,{'core':gap},0,aspect,(170,170),True)
            router=Router(graph,1,100000,placement);cells=router.route()
            core=logic_core_metrics(cells,router.gates,router.output_nets)
            print(dict(aspect=aspect,gap=gap,cells=len(cells),core=core,seconds=round(time.perf_counter()-started,2)),flush=True)
            break
        except MapError as e:print(dict(aspect=aspect,gap=gap,error=str(e),seconds=round(time.perf_counter()-started,2)),flush=True)
