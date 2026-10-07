"""Check one bit per tick with a fixed channel; switching hazards are separate."""
import random
from mapdata import read_map,write_json
from simulation import simulate


def verify_streaming(manifest,folder,stem):
    cells=read_map(folder/f'{stem}.test.save.txt')
    count=len(manifest['inputs']['data'])
    warm=2*manifest['settle_ticks'];samples=240
    rng=random.Random(711)
    words=[0]*warm+[rng.randrange(1<<count) for _ in range(samples)]+[0]*warm
    results=[]
    for select in range(count):
        ports=[{'at':entry['fixture'],'values':[(value>>i)&1 for value in values]}
               for name,values in (('data',words),('sel',[select]*len(words)))
               for i,entry in enumerate(manifest['inputs'][name])]
        report=simulate(cells,{'ticks':len(words),'inputs':ports,
                        'expect':[{'at':manifest['outputs']['y'][0]['fixture'],
                                   'values':[0]+[None]*(len(words)-1)}]},optimize_cycles=False)
        actual=report['outputs'][0]['values']
        lags=[lag for lag in range(1,manifest['settle_ticks']+1)
              if all(actual[t]==((words[t-lag]>>select)&1) for t in range(warm+lag,len(words)))]
        if len(lags)!=1:raise RuntimeError(f'{stem}: stream fails on channel {select}: {lags}')
        results.append({'sel':select,'latency_ticks':lags[0],'input_period_ticks':1,'samples':samples})
    write_json(folder/f'{stem}.streaming.json',{'passed':True,'mode':'fixed_select','channels':results})
    return results
