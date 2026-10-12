"""Reimported save verification for mechanically stackable modules."""
import json
from .context import *
from .context import EXPECTED
from .context import simulate

MINE_PORTS=('W:NM','N:M','E:NM','W:M','E:M','W:SM','S:M','E:SM')
DIAGONAL_MINE_PORTS=('DG:NWM','N:M','DG:NEM','W:M','E:M','DG:SWM','S:M','DG:SEM')
AGGREGATE_MINE_PORTS=('W:MP','W:MC','N:M','E:MP','E:MC','S:M')

def aggregate_mine_inputs(mask):
    """Encode the same NW,N,NE,W,E,SW,S,SE mask at reduced contacts."""
    west=sum((mask>>i)&1 for i in (0,3,5))
    east=sum((mask>>i)&1 for i in (2,4,7))
    return {'W:MP':west&1,'W:MC':west>>1,'N:M':(mask>>1)&1,
            'E:MP':east&1,'E:MC':east>>1,'S:M':(mask>>6)&1}

def sources(cells,meta,ports):
    result={}
    for name in ports:
        es=meta['inputs'][name];p=tuple(es[0]['fixture']);rotation=es[0]['rotation']
        if name.startswith('DG:'):
            from diagonal_ports import ROTATIONS,OPPOSITE
            assert p not in cells
            cells[p]=Cell(11,ROTATIONS[OPPOSITE[name[3:5]]])
            p=(p[0]-1,p[1]) if rotation==1 else (p[0]+1,p[1])
        if name.startswith('button'):
            p=p[0]+2,p[1]
            if meta.get('serial_control'):
                p=tuple(meta['button'][0]);rotation=cells[p].rotation
        assert p not in cells or cells[p].type==24
        cells[p]=Cell(22,rotation);result[name]=p
    return result

def register_probes(cells,meta,board=False):
    out={}
    for name,p in meta['states'].items():
        if name in ('cascade','loss'):
            if board:continue
            cascade_port='N:Z' if meta.get('aggregate_neighbors') else 'E:Z'
            e=meta['outputs'][cascade_port if name=='cascade' else 'E:prefixLoss'][0]
            q=tuple(e['fixture']);assert q not in cells
            cells[q]=Cell(23,0);out[name]=q;continue
        p=tuple(p);q=p[0],p[1]+1;r=p[0],p[1]+2
        assert q not in cells and r not in cells,(name,p)
        cells[q]=Cell(5,2);cells[r]=Cell(23,0);out[name]=r
    return out

def segment_probes(cells,meta):
    out=[]
    for p in meta['segment_registers']:
        p=tuple(p);q=next(destinations(p,cells[p]));cells[q]=Cell(23,0);out.append(q)
    return out

def verify_cell(stem='tile'):
    cells=read_map(BUILD/(stem+'.save.txt'));meta=json.loads((BUILD/(stem+'.layout.json')).read_text())
    mine_ports=AGGREGATE_MINE_PORTS if meta.get('aggregate_neighbors') else DIAGONAL_MINE_PORTS if meta.get('diagonal_contacts') else MINE_PORTS
    inp=sources(cells,meta,list(mine_ports)+['N:ready','button0'])
    seg=segment_probes(cells,meta);states={name:tuple(p) for name,p in meta['states'].items()}
    masks=list(range(256))+list(reversed(range(256)));hold=1600
    scenario=dict(ticks=len(masks)*hold,hold_ticks=hold,
        inputs=[dict(at=list(p),values=[aggregate_mine_inputs(mask)[name] if meta.get('aggregate_neighbors') and name in mine_ports else (mask>>mine_ports.index(name))&1 if name in mine_ports else 1 for mask in masks]) for name,p in inp.items()],
        expect=[dict(at=list(p),values=[(EXPECTED[mask.bit_count()]>>j)&1 for mask in masks]) for j,p in enumerate(seg)],
        observe=[list(p) for p in states.values()])
    r=simulate(cells,scenario,optimize_cycles=False,timeout=180)
    if not r['passed']:raise AssertionError(r['failures'][:12])
    for name,actual in zip(states,r['observations']):
        expected=[int(name in ('opened','request','busy')) if name!='cascade' else int(mask==0) for mask in masks]
        if meta.get('serial_control') and name=='busy':expected=[0]*len(masks)
        assert actual['values']==expected,('state',name)
    # Exercise each physical button square separately on the complete save.
    # Observe its common collector before the stateful game logic.
    button_cells=read_map(BUILD/(stem+'.save.txt'))
    buttons=list(map(tuple,meta['button']))
    contact=meta['inputs']['button0'][0]['contact']
    for p in buttons:
        # Replace only the pressed square. Replacing the entire rectangle by
        # Sources would destroy the button-to-button collector inside V1.
        tested=dict(button_cells);tested[p]=Cell(22,button_cells[p].rotation)
        collector=p
        visited=set()
        while collector in buttons:
            assert collector not in visited,'Button collector contains a cycle'
            visited.add(collector)
            collector=next(destinations(collector,button_cells[collector]))
        assert collector in button_cells
        button_report=simulate(tested,dict(ticks=320,hold_ticks=160,
            inputs=[dict(at=list(p),values=[1,0])],expect=[],observe=[list(collector)]),optimize_cycles=False)
        assert button_report['observations'][0]['values']==[1,0],('button square',p)
    result=dict(passed=True,neighbor_masks=256,transition_vectors=512,segment_checks=7*512,checked_samples=r['checked_samples']+len(states)*len(masks),read_only_state_checks=True,button_squares=len(buttons),button_press_release_checks=2*len(buttons),side=meta['side'],map_hash=meta['map_hash'])
    result['save_sha256']=save_sha256(BUILD/(stem+'.save.txt'))
    write_json(BUILD/(stem+'.verification.json'),result)
    print('Framed cell verified:',result,flush=True)
    return result

def moved(meta,dx,dy):
    result=dict(meta)
    result['states']={name:[p[0]+dx,p[1]+dy] for name,p in meta['states'].items()}
    result['segment_registers']=[[p[0]+dx,p[1]+dy] for p in meta['segment_registers']]
    result['button']=[[p[0]+dx,p[1]+dy] for p in meta['button']]
    result['inputs']={name:[dict(e,contact=[e['contact'][0]+dx,e['contact'][1]+dy],fixture=[e['fixture'][0]+dx,e['fixture'][1]+dy]) for e in es] for name,es in meta['inputs'].items()}
    return result

def verify_board(size=10,seed=123456789,first=None,stem=None):
    from .context import simulate as run_native
    from .reference_model import flood
    stem=stem or f'minesweeper_{size}x{size}'
    cells=read_map(BUILD/(stem+'.save.txt'));meta=json.loads((BUILD/(stem+'.layout.json')).read_text())
    first=(size//2)*size+size//2 if first is None else first
    ports={};buttons=[];mine_pixels={}
    for i,t in enumerate(meta['tiles']):
        tm=moved(meta['cell'],*t['origin'])
        buttons.append(sources(cells,tm,['button0'])['button0'])
        for name,p in tm['states'].items():
            if name not in ('cascade','loss'):ports[f'{i}:{name}']=tuple(p)
        for j,p in enumerate(segment_probes(cells,tm)):ports[f'{i}:segment{j}']=p
        dx,dy=t['origin']
        marker=meta['cell'].get('mine_indicator')
        points=marker['pixels'] if marker else [meta['cell']['outputs'][f'explosion:{j}'][0]['contact'] for j in range(5)]
        for j,p in enumerate(points):
            mine_pixels[f'{i}:minePixel{j}']=(p[0]+dx,p[1]+dy)
    observed={name:tuple(meta['header']['outputs'][name][0]['contact']) for name in ('victory','defeat')}
    observed.update(mine_pixels)
    for name,display in meta.get('status',{}).get('displays',{}).items():
        for j,p in enumerate(display['pixels']):observed[f'{name}:pixel{j}']=tuple(p)
    status_frames={}
    wait=max(50000,meta['full_settle_bound']*2+meta['logic_settle_bound']*2)
    initial=[max(2000,meta['logic_settle_bound']),64,wait]
    def run(events=()):
        durations=initial+[d for event in events for d in (64,max(20000,meta['logic_settle_bound']*3))]
        scenario=dict(ticks=sum(durations),frame_ticks=durations,seed=seed,
            inputs=[dict(at=list(p),values=[0,int(i==first),0]+[b for event in events for b in (int(i in event),0)]) for i,p in enumerate(buttons)],
            expect=[],observe=[list(p) for p in ports.values()]+[list(p) for p in observed.values()])
        r=run_native(cells,scenario,optimize_cycles=False,timeout=240)
        assert not r['failures'],r['failures'][:10]
        for j,name in enumerate(ports):assert r['observations'][j]['values'][0]==0,('cold state',name)
        values={name:r['observations'][j]['values'][-1] for j,name in enumerate(ports)}
        for j,name in enumerate(observed):
            samples=r['observations'][len(ports)+j]['values']
            assert samples[0]==0,('indicator lit before game',name)
            values[name]=samples[-1]
        status_frames['cold']={name:r['observations'][len(ports)+j]['values'][0] for j,name in enumerate(observed)}
        return values
    v=run();mines={i for i in range(size*size) if v[f'{i}:mine']}
    if size>=5:assert mines,'Fixed verification seed must produce mines'
    opened=flood(size,mines,set(),[first])
    selected={i for i in range(size*size) if v[f'{i}:selected']}
    write_json(BUILD/(stem+'.observed.json'),v)
    assert selected=={first},('selection',selected)
    x,y=first%size,first//size
    protected={first}|{(y+dy)*size+x+dx for dx,dy in DIRECTIONS if 0<=x+dx<size and 0<=y+dy<size}
    assert not mines&protected,('first protection',mines&protected)
    def check(values,expected,defeat=False):
        actual={i for i in range(size*size) if values[f'{i}:opened']}
        assert actual==expected,('opened',sorted(actual^expected))
        for i in range(size*size):
            assert values[f'{i}:mine']==int(i in mines),('mine changed',i)
            x,y=i%size,i//size
            count=sum((y+dy)*size+x+dx in mines for dx,dy in DIRECTIONS if 0<=x+dx<size and 0<=y+dy<size)
            word=EXPECTED[count] if i in expected and i not in mines else 0
            actualword=sum(values[f'{i}:segment{j}']<<j for j in range(7))
            assert actualword==word,('display',i,count,actualword,word)
            for j in range(len(points)):
                assert values[f'{i}:minePixel{j}']==int(defeat and i in mines and (bool(marker) or i in expected)),('mine indicator',i,j)
        assert values['defeat']==int(defeat)
        assert values['victory']==int(not defeat and len(expected-mines)==size*size-len(mines))
        for name,display in meta.get('status',{}).get('displays',{}).items():
            for j in range(len(display['pixels'])):
                assert values[f'{name}:pixel{j}']==values[name],('status pixel',name,j)
    check(v,opened)
    status_frames['first_move']={name:v[name] for name in observed}
    write_json(BUILD/(stem+'.demo.json'),dict(size=size,first=first,mines=sorted(mines),opened=sorted(opened),measured=v))
    cases=['first-safe','neighbor-counts','cascade','closed-blank','visible-zero','stacked-connectors']
    if mines:
        mine=min(mines);dv=run([{mine},set(range(size*size))-mines-opened]);check(dv,opened|{mine},True)
        write_json(BUILD/(stem+'.defeat.demo.json'),dict(size=size,first=first,mines=sorted(mines),
                   opened=sorted(opened|{mine}),clicked_mine=mine,measured=dv))
        status_frames['defeat']={name:dv[name] for name in observed}
        cases+=['mine-defeat','blocked-after-defeat','safe-cells-stay-closed-after-defeat']
        if marker:cases+=['all-mines-revealed']
    vv=run([set(range(size*size))-mines,mines]);check(vv,set(range(size*size))-mines)
    status_frames['victory']={name:vv[name] for name in observed}
    write_json(BUILD/(stem+'.status.observed.json'),dict(map_hash=meta['map_hash'],frames=status_frames))
    cases+=['victory','blocked-after-victory']
    if meta.get('status'):cases+=['status-blank-before-start','win-lose-all-pixels']
    result=dict(passed=True,size=size,seed=seed,first=first,mines=sorted(mines),first_opened=sorted(opened),scenarios=cases,map_hash=meta['map_hash'],
        measured_outputs=len(ports)+len(observed),status_pixels=sum(len(d['pixels']) for d in meta.get('status',{}).get('displays',{}).values()),
        mine_indicator_pixels=len(mine_pixels),
        wait_ticks=wait,identical_modules=True,connection_wires_added=meta.get('connection_wires_added',0))
    result['save_sha256']=save_sha256(BUILD/(stem+'.save.txt'))
    write_json(BUILD/(stem+'.verification.json'),result)
    print('Snap board verified:',result,flush=True)
    return result

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--size',type=int,default=10);p.add_argument('--cell-only',action='store_true')
    p.add_argument('--seed',type=int,default=123456789);p.add_argument('--first',type=int);p.add_argument('--two-seeds',action='store_true');a=p.parse_args()
    verify_cell()
    if not a.cell_only:
        if a.two_seeds:
            assert a.size==10,'Two-seed delivery audit uses the base 10x10 board'
            runs=[verify_board(10,123456789,55),verify_board(10,987654321,0)]
            write_json(BUILD/'minesweeper-10x10.seeds.verification.json',dict(passed=True,runs=runs))
        else:verify_board(a.size,a.seed,a.first)
