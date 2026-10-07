"""Drive the screenshot's existing directional buttons with one-tick pulses."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0,str(ROOT/"src"))
from arrow_layout import bounds_of,depth_of,destinations
from mapdata import map_hash,read_map
from test_harness import add_fixture
from simulation import simulate

CONTROLS={"load_a":(-2,4),"load_b":(-2,15),"invert_a":(13,6),"read_sum":(13,12),"lsb_toggle":(33,8)}
FRAME=160
PHASES=[1,9,1,88,1,60]


def manifest(cells):
    inputs={}
    for name,y in (("a_buttons",0),("b_buttons",19)):
        inputs[name]=[]
        for bit in range(8):
            key=2*(7-bit),y
            cell=cells[key]
            dx,dy=next(destinations((0,0),cell))
            inputs[name].append({"index":bit,"contact":list(key),"fixture":[key[0]-dx,key[1]-dy],"rotation":cell.rotation})
    for name,key in CONTROLS.items():
        cell=cells[key]
        dx,dy=next(destinations((0,0),cell))
        inputs[name]=[{"index":0,"contact":list(key),"fixture":[key[0]-dx,key[1]-dy],"rotation":cell.rotation}]
    outputs={"sum":[{"index":bit,"contact":[37+2*bit,8],"fixture":[37+2*bit,7],"rotation":0} for bit in range(8)],
             "cout":[{"index":0,"contact":[15,9],"fixture":[13,9],"rotation":0}]}
    return {"schema":1,"top":"reference_adder8","map_hash":map_hash(cells),"profile":"GraphDLC-01232bd",
            "verified_against_current_game":False,"inputs":inputs,"outputs":outputs,"cells":len(cells),
            "geometry_depth":depth_of(cells),"operation_ticks":FRAME,"bounds":bounds_of(cells),"layout":"reference-image",
            "gate_labels":[]}


def scenario(meta,cases,frame=FRAME):
    ticks=len(cases)*frame
    assert frame==sum(PHASES)
    samples=len(cases)*len(PHASES)
    inputs=[]
    for name,entries in meta["inputs"].items():
        for bit,entry in enumerate(entries):
            values=[0]*samples
            previous=0
            for i,case in enumerate(cases):
                start=i*len(PHASES)
                if name=="a_buttons" or name=="b_buttons":
                    word=case["a" if name=="a_buttons" else "b"]
                    value=(word>>bit)&1
                    values[start]=previous^value
                    previous=value
                elif name in ("load_a","load_b"):values[start+2]=1
                elif name=="read_sum":values[start+4]=1
            inputs.append({"at":entry["fixture"],"values":values})
    expect=[]
    for name,entries in meta["outputs"].items():
        for bit,entry in enumerate(entries):
            values=[None]*samples
            for i,case in enumerate(cases):
                total=case["a"]+case["b"]
                value=(total&255) if name=="sum" else total>>8
                values[(i+1)*len(PHASES)-1]=(value>>bit)&1
            expect.append({"at":entry["fixture"],"values":values})
    return {"ticks":ticks,"frame_ticks":PHASES*len(cases),"inputs":inputs,"expect":expect}


def run(cases):
    cells=read_map(HERE/"build/reference.map.json")
    meta=manifest(cells)
    test=add_fixture(cells,meta)
    case=scenario(meta,cases)
    report=simulate(test,case,optimize_cycles=False)
    measured={tuple(p["at"]):p["values"] for p in report["outputs"]}
    for i,values in enumerate(cases):
        actual={name:sum(measured[tuple(e["fixture"])][(i+1)*len(PHASES)-1]<<bit for bit,e in enumerate(entries)) for name,entries in meta["outputs"].items()}
        print(values,actual)
    print('passed',report['passed'],'failures',report['failures'][:10])
    return report


if __name__=="__main__":
    run([{"a":a,"b":b} for a,b in ((1,0),(128,0),(1,1),(255,1),(0,0),(85,170))])
