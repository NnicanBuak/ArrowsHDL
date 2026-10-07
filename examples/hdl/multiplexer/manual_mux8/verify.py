"""Verify the user's compact mux8 against all input combinations."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'src'))
from arrow_layout import bounds_of,depth_of,edges,logic_core_metrics
from mapdata import map_hash,read_map,write_json,write_map
from output_layout import exterior_bounds
from input_buses import verify_exterior
from test_harness import run_vectors


def run():
    folder=Path(__file__).resolve().parent
    cells=read_map(folder/'mux8.manual.original.save.txt')
    incoming={p:[] for p in cells}
    links=edges(cells)
    for p,targets in links.items():
        for q in targets:incoming[q].append(p)
    gates={p:{'id':f'manual:{p[0]}:{p[1]}','output':f'at:{p[0]}:{p[1]}',
              'op':{15:'NOT',16:'AND'}.get(cell.type,'OR')}
           for p,cell in cells.items() if cell.type in (15,16) or len(incoming[p])>1}
    inputs={'data':[{'index':i,'contact':[0,y],'fixture':[-1,y],'rotation':1}
                    for i,y in enumerate((1,2,4,5,7,8,10,11))],
            'sel':[{'index':i,'contact':[x,0],'fixture':[x,-1],'rotation':2}
                   for i,x in enumerate((1,4,7))]}
    outputs={'y':[{'index':0,'contact':[8,7],'fixture':[9,7],'rotation':0}]}
    meta={'schema':1,'top':'mux8_manual','map_hash':map_hash(cells),
          'inputs':inputs,'outputs':outputs,'bounds':bounds_of(cells),
          'full_bounds':exterior_bounds(cells,inputs,outputs),'cells':len(cells),
          'settle_ticks':depth_of(cells)+2,'logic_core':logic_core_metrics(cells,gates,{'port:y'}),
          'gate_labels':[dict(at=list(p),**g) for p,g in gates.items()]}
    verify_exterior(cells,meta)
    write_map(folder,'mux8.manual',cells)
    write_json(folder/'mux8.manual.build.json',meta)
    vectors=[{'inputs':{'data':value,'sel':select},'expect':{'y':(value>>select)&1}}
             for value in range(256) for select in range(8)]
    vectors+=list(reversed(vectors))
    _,report=run_vectors(cells,meta,vectors,folder,'mux8.manual',compressed=True)
    print({'passed':report['passed'],'checked_samples':report['checked_samples'],
           'cells':meta['cells'],'bounds':meta['bounds'],'core':meta['logic_core'],
           'hold_ticks':meta['settle_ticks']})
    if not report['passed']:raise RuntimeError(report['failures'][:3])


if __name__=='__main__':run()
