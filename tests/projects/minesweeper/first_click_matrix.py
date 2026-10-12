"""Native cold-start and simultaneous first-click arbitration audit."""
from .snap_verify import *


def verify(stem='minesweeper_10x10'):
    meta=json.loads((BUILD/(stem+'.layout.json')).read_text());size=meta['size']
    center=(size//2)*size+size//2
    cases=[(0,size*size-1),(center,center+1),(size-1,size*(size-1)),
           ((size//2-1)*size+size//2,(size//2)*size+size//2-1),(size*size-1,)]
    results=[]
    for pressed in cases:
        cells=read_map(BUILD/(stem+'.save.txt'));inputs=[];observe=[];names=[]
        for i,t in enumerate(meta['tiles']):
            tm=moved(meta['cell'],*t['origin'])
            if i in pressed:
                p=sources(cells,tm,['button0'])['button0']
                inputs.append(dict(at=list(p),values=[0,1,0]))
            for name in ('selected','mine','opened'):
                names.append((i,name));observe.append(tm['states'][name])
        report=simulate(cells,dict(ticks=80065,frame_ticks=[1,64,80000],seed=123456789,inputs=inputs,expect=[],observe=observe),timeout=240)
        values={(i,name):v['values'][-1] for (i,name),v in zip(names,report['observations'])}
        chosen={i for i in range(size*size) if values[i,'selected']}
        assert chosen=={min(pressed)},('cold tie selection',pressed,chosen)
        first=min(pressed);x,y=first%size,first//size
        protected={first}|{(y+dy)*size+x+dx for dx,dy in DIRECTIONS if 0<=x+dx<size and 0<=y+dy<size}
        mines={i for i in range(size*size) if values[i,'mine']}
        assert not mines&protected,('cold protection',pressed,mines&protected)
        assert values[first,'opened']==1
        results.append(dict(pressed=list(pressed),selected=sorted(chosen),protected=sorted(protected),passed=True))
    result=dict(passed=True,map_hash=meta['map_hash'],cold_ticks=1,cases=results)
    write_json(BUILD/(stem+'.first-click-matrix.json'),result);print(result,flush=True)
    return result


if __name__=='__main__':verify()
