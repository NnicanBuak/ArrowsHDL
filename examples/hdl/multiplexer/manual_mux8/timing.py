"""Measure streaming latency and find selector-switch glitches in the manual map."""
import json
from pathlib import Path
import random
import sys

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'src'))
from mapdata import read_map,write_json
from simulation import simulate


def run():
    folder=Path(__file__).resolve().parent
    cells=read_map(folder/'mux8.manual.test.save.txt')
    meta=json.loads((folder/'mux8.manual.build.json').read_text())
    def trace(data,select):
        ports=[{'at':entry['fixture'],'values':[(value>>i)&1 for value in values]}
               for name,values in (('data',data),('sel',select))
               for i,entry in enumerate(meta['inputs'][name])]
        report=simulate(cells,{'ticks':len(data),'inputs':ports,
                        'expect':[{'at':meta['outputs']['y'][0]['fixture'],
                                   'values':[0]+[None]*(len(data)-1)}]},optimize_cycles=False)
        return report['outputs'][0]['values']
    rng=random.Random(711)
    words=[0]*40+[rng.randrange(256) for _ in range(240)]+[0]*30
    streams=[]
    for select in range(8):
        actual=trace(words,[select]*len(words))
        lags=[lag for lag in range(1,26) if all(
              actual[t]==((words[t-lag]>>select)&1) for t in range(40+lag,len(words)))]
        if len(lags)!=1:raise RuntimeError(f'No unique stream latency: {select}, {lags}')
        streams.append({'sel':select,'matching_latency':lags,'samples':240})
    cases=[(1<<hot,a,b) for hot in range(8) for a in range(8) for b in range(8)
           if a!=b and a!=hot and b!=hot]
    data=[];select=[]
    for word,a,b in cases:
        data.extend([word]*70);select.extend([a]*40+[b]*30)
    actual=trace(data,select);glitches=[]
    for index,(word,a,b) in enumerate(cases):
        start=index*70+40
        hits=[t-start+1 for t in range(start,start+30) if actual[t]]
        if hits:glitches.append({'data':word,'old_sel':a,'new_sel':b,
                                'relative_ticks_after_change':hits,'actual_y':actual[start-5:start+25]})
    selectors=[0]*40+[rng.randrange(8) for _ in range(240)]+[0]*30
    actual=trace(words,selectors)
    mixed=[{'lag':lag,'errors':sum(actual[t]!=((words[t-lag]>>selectors[t-lag])&1)
                                   for t in range(40+lag,280))} for lag in range(1,26)]
    write_json(folder/'mux8.manual.timing.json',{
        'stable_select_streams':streams,'mixed_stream':mixed,
        'positive_glitch_scan':{'cases':len(cases),'glitch_cases':len(glitches),'examples':glitches[:12]}})
    print({'latencies':[s['matching_latency'][0] for s in streams],
           'glitch_cases':len(glitches),'cases':len(cases),'example':glitches[:1],
           'best_mixed_stream':min(mixed,key=lambda c:c['errors'])})


if __name__=='__main__':run()
