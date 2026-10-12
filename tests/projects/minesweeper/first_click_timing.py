"""Physical regression: clicks during preparation cannot re-elect the start."""
from .snap_verify import *


def verify(stem='minesweeper_10x10'):
    meta=json.loads((BUILD/(stem+'.layout.json')).read_text())
    size=meta['size'];first=(size//2)*size+size//2;second=0;cold=30000;ticks=65000
    tile=[moved(meta['cell'],*t['origin']) for t in meta['tiles']]
    gates={n['net']:n['at'] for n in meta['cell']['gate_positions']}
    phases=[tile[second]['states']['busy']]+[
        [gates['phase:'+name][0]+meta['tiles'][index]['origin'][0],
         gates['phase:'+name][1]+meta['tiles'][index]['origin'][1]]
        for index,name in ((second,'choose'),(first,'choose'),(first,'ready'))]
    cells=read_map(BUILD/(stem+'.save.txt'))
    button=sources(cells,tile[first],['button0'])['button0']
    baseline=simulate(cells,dict(ticks=ticks,seed=123456789,
        inputs=[dict(at=list(button),values=[0]*cold+[1]*64+[0]*(ticks-cold-64))],
        expect=[],observe=phases),timeout=240)
    events=[next(i for i,value in enumerate(o['values']) if i>=cold and value)
            for o in baseline['observations']]
    assert events[0]+256<events[1],('request capture not closed before election',events)
    cases=sorted(set((events[0]+256,events[1]-128,events[1]+128,events[2]-128,events[3]-128)))
    results=[]
    for at_tick in cases:
        cells=read_map(BUILD/(stem+'.save.txt'));inputs=[]
        for index,time in ((first,cold),(second,at_tick)):
            button=sources(cells,tile[index],['button0'])['button0']
            inputs.append(dict(at=list(button),values=[0]*time+[1]*64+[0]*(ticks-time-64)))
        names=[(i,name) for i in range(size*size) for name in ('selected','mine','opened','request')]
        report=simulate(cells,dict(ticks=ticks,seed=123456789,inputs=inputs,expect=[],
            observe=[tile[i]['states'][name] for i,name in names]),timeout=240)
        values={key:o['values'][-1] for key,o in zip(names,report['observations'])}
        selected=[i for i in range(size*size) if values[i,'selected']]
        x,y=first%size,first//size
        protected={first}|{(y+dy)*size+x+dx for dx,dy in DIRECTIONS if 0<=x+dx<size and 0<=y+dy<size}
        assert selected==[first],('late click changed election',at_tick-cold,selected)
        assert values[second,'request']==0,('late request was captured',at_tick-cold)
        assert values[first,'opened']==1
        assert not any(values[i,'mine'] for i in protected)
        results.append(dict(second_click_after_first=at_tick-cold,selected=selected,passed=True))
    result=dict(passed=True,map_hash=meta['map_hash'],size=size,first=first,second=second,
                events_after_click=dict(zip(('busy_second','choose_second','choose_first','ready_first'),[t-cold for t in events])),
                cases=results)
    write_json(BUILD/(stem+'.first-click-timing.json'),result)
    print('Late preparation clicks passed:',size,len(cases),result['events_after_click'],flush=True)
    return result


if __name__=='__main__':verify()
