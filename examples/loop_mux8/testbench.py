"""Independent tick oracle: toggle controls, priority, zero blocking and history."""
import json
import sys
from build import build, HERE, PROJECT, STEM, REQUESTS, CODE, DISPLAY, OUTPUT, LATCHES, WIDTHS
sys.path.insert(0,str(PROJECT/'src'))
from mapdata import read_map, write_json
from arrowasm import Cell
from simulation import simulate


def oracle(cells,requests):
    paths={1:[(0,-1)],2:[(0,-1),(1,0),(0,1),(-1,0)],3:[(0,-1)],
           6:[(0,-1),(0,1)],7:[(0,-1),(1,0)],8:[(0,-1),(1,0),(-1,0)],
           10:[(0,-2)],11:[(1,-1)],12:[(0,-1),(0,-2)],
           13:[(1,0),(0,-2)],14:[(0,-1),(1,-1)],15:[(0,-1)],
           16:[(0,-1)],17:[(0,-1)],19:[(0,-1)],22:[(0,-1)],23:[],24:[(0,-1)]}
    links={}
    for p,c in cells.items():
        links[p]=[]
        for dx,dy in paths[c.type]:
            if c.mirrored:dx=-dx
            for _ in range(c.rotation):dx,dy=-dy,dx
            target=p[0]+dx,p[1]+dy
            if target in cells:links[p].append(target)
    states=dict.fromkeys(cells,0)
    traces={p:[] for p in DISPLAY+CODE+LATCHES if p in cells}
    source_bits={p:i for i,p in enumerate(REQUESTS)}
    for pressed in requests:
        counts=dict.fromkeys(cells,0);blocked=set()
        for p,c in cells.items():
            if states[p]!=1:continue
            if c.type==3:blocked.update(links[p])
            else:
                for q in links[p]:counts[q]+=1
        updated={}
        for p,c in cells.items():
            n,old=counts[p],states[p]
            if p in blocked:value=0
            elif c.type==15:value=int(n==0)
            elif c.type==16:value=int(n>=2)
            elif c.type==17:value=n%2
            elif c.type==19:value=1-old if n else old
            elif c.type==22:value=int(bool(n or pressed&(1<<source_bits[p])))
            elif c.type==2:value=1
            elif c.type==24:value=0
            else:value=int(n>0)
            updated[p]=value
        states=updated
        for p in traces:traces[p].append(states[p])
    return traces


def check(cells,requests,label):
    expected=oracle(cells,requests)
    scenario={'ticks':len(requests),'inputs':[{'at':list(p),'values':[int(bool(r&(1<<i))) for r in requests]}
        for i,p in enumerate(REQUESTS) if cells[p].type==22],
        'expect':[{'at':list(p),'values':v} for p,v in expected.items()]}
    checked=0
    for optimized in (False,True):
        r=simulate(cells,scenario,optimize_cycles=optimized)
        if not r['passed']:raise RuntimeError(f"{label}: {r['failures'][:5]}")
        checked+=r['checked_samples']
    return expected,checked


def word(trace,ports,t):return sum(trace[p][t]<<i for i,p in enumerate(ports))


def run():
    _,_,meta=build();folder=HERE/'build'
    cells=read_map(folder/f'{STEM}.test.save.txt');checks=0;modes=[]
    for mode in range(8):
        # A long hold must toggle exactly once, then retain selection after release.
        requests=[1<<mode]*40+[0]*2008
        trace,count=check(cells,requests,f'mode{mode}');checks+=count
        if word(trace,LATCHES,-1)!=1<<mode or word(trace,CODE,-1)!=mode:
            raise RuntimeError('Held button toggled more than once or lost its state')
        tail=trace[OUTPUT][500:]
        if mode==0:
            if any(tail):raise RuntimeError('000 did not block output')
            size=0
        else:
            size=4*WIDTHS[mode]+8
            if set(tail)!={0,1} or any(tail[t]!=tail[t-size] for t in range(size,len(tail))):
                raise RuntimeError('Wrong selected oscillator')
        for i,p in enumerate(DISPLAY):
            if trace[p][500:]!=trace[OUTPUT][500-i:len(trace[OUTPUT])-i]:
                raise RuntimeError('Incorrect display history')
        modes.append({'mode':mode,'period_ticks':size,'output_disabled':mode==0})
        print(f'Mode {mode}: retained after release, period={size}',flush=True)
        (folder/f'mode{mode}.trace.json').write_text(json.dumps({'output':''.join(map(str,trace[OUTPUT])),
          'code':[word(trace,CODE,t) for t in range(len(requests))],
          'display':[f'{word(trace,DISPLAY,t):016x}' for t in range(len(requests))]},separators=(',',':')),encoding='utf-8')
    # Every possible latched mask, including simultaneous rising edges.
    schedule=[];samples=[];old=0
    for mask in range(256):
        schedule.extend([old^mask]+[0]*249);samples.append((len(schedule)-1,mask));old=mask
    trace,count=check(cells,schedule,'all_masks');checks+=count
    for t,mask in samples:
        code=(mask&-mask).bit_length()-1 if mask else 0
        if word(trace,LATCHES,t)!=mask or word(trace,CODE,t)!=code:
            raise RuntimeError(f'Priority failure for mask {mask}')
        if code==0 and any(trace[p][t] for p in DISPLAY):
            raise RuntimeError(f'Display not cleared at 000 for mask {mask}')
    # Several buttons rising together, held and released, then pressed again.
    trace,count=check(cells,[0]*250+[0b11000110]*80+[0]*250+[0b11000110]*80+[0]*250,'simultaneous');checks+=count
    if word(trace,LATCHES,550)!=0b11000110 or word(trace,CODE,550)!=1 or word(trace,LATCHES,-1)!=0:
        raise RuntimeError('Simultaneous toggles or second click failed')
    for mode in range(8):
        preset=read_map(folder/'presets'/f'mode{mode}.save.txt')
        for p in DISPLAY+CODE+LATCHES:preset[p]=Cell(23,0)
        trace,count=check(preset,[0]*2048,f'preset{mode}');checks+=count
        if word(trace,CODE,-1)!=mode or (mode==0 and any(trace[OUTPUT][500:])):
            raise RuntimeError('Wrong saved preset')
    report={'passed':True,'cells':meta['cells'],'map_hash':meta['map_hash'],'modes':modes,
       'checked_samples':checks,'all_256_latched_masks_verified':True,
       'held_buttons_toggle_once':True,'second_click_toggles_off':True,
       'simultaneous_clicks_verified':True,'all_eight_game_presets_verified':True,
       'zero_disables_output':True,'display_pixels':64,'verified_against_current_game':False}
    write_json(folder/f'{STEM}.report.json',report)
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':run()
