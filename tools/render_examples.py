"""Reproduce diagrams and measured behavior from the repository's final saves."""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw
from arrowshdl.map_preview import font, render_cells
from arrowshdl.mapdata import read_map, save_sha256
from arrowshdl.simulation import simulate
from arrowshdl.artifacts import read_metadata
from arrowshdl.test_harness import add_fixture, make_scenario

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tests.projects.examples.artifacts import save_artifact
INK, MUTED, BLUE, GREEN = '#172b46', '#586a80', '#2774d4', '#157d68'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def canvas(title, subtitle, height=620):
    im = Image.new('RGB', (1440, height), '#f5f8fc')
    d = ImageDraw.Draw(im)
    d.text((44, 28), title, fill=INK, font=font(34))
    d.text((44, 82), subtitle, fill=MUTED, font=font(20))
    return im, d


def diagram(spec, path):
    im, d = canvas(spec['title'], spec['subtitle'], 720)
    # The JSON describes actual HDL units, rather than an inferred netlist drawing.
    for edge in spec['edges']:
        a, b = (spec['blocks'][i] for i in edge)
        start, end = (a['at'][0]+260, a['at'][1]+70), (b['at'][0], b['at'][1]+70)
        middle = (start[0]+end[0])//2
        d.line([start, (middle,start[1]), (middle,end[1]), end], fill=BLUE, width=4)
        d.polygon([end,(end[0]-12,end[1]-7),(end[0]-12,end[1]+7)], fill=BLUE)
    for block in spec['blocks']:
        x,y = block['at']
        d.rounded_rectangle((x,y,x+260,y+140), radius=15, fill='white', outline='#bed0e7', width=2)
        d.text((x+16,y+16), block['name'], fill=INK, font=font(22))
        for i,line in enumerate(block['lines']):
            d.text((x+16,y+53+i*27), line, fill=MUTED, font=font(18))
    d.text((44,650), spec['note'], fill=MUTED, font=font(19))
    im.save(path)


def measured_table(folder, top, spec):
    saved = folder/'build'/f'{top}.json'
    meta = read_metadata(saved)
    vectors_file=ROOT/'tests/fixtures/examples'/folder.name/'vectors.json'
    vectors = read(vectors_file)
    report = simulate(add_fixture(read_map(saved),meta), make_scenario(meta,vectors,compressed=True))
    assert report['passed'], report['failures']
    trace = {tuple(row['at']):row['values'] for row in report['outputs']}
    rows=[]
    for i,vector in enumerate(vectors):
        actual={name:sum(trace[tuple(e['fixture'])][i]<<bit for bit,e in enumerate(entries))
                for name,entries in meta['outputs'].items()}
        assert actual==vector['expect']
        rows.append(dict(inputs=vector['inputs'],actual=actual))
    im,d = canvas(spec['title']+' · поведение', 'Значения сняты с выходов физической карты после установления', 290+len(rows)*57)
    columns=spec['columns']; widths=[c['width'] for c in columns]
    x=44
    for c,w in zip(columns,widths):
        d.text((x+10,146),c['label'],font=font(19),fill=MUTED);x+=w
    for i,row in enumerate(rows):
        y=189+i*57
        d.rounded_rectangle((44,y,1396,y+47),radius=8,fill='white')
        x=44
        for c,w in zip(columns,widths):
            value=row[c['from']][c['key']]
            value=c.get('names',{}).get(str(value),str(value))
            d.text((x+10,y+9),value,font=font(21),fill=INK);x+=w
    digest=save_sha256(saved)
    d.text((44,im.height-40),'PASS · save SHA-256: '+digest[:20]+'…',font=font(18),fill=GREEN)
    im.save(folder/'visuals/behavior.png')
    save_artifact(folder.name,'behavior.report.json',dict(passed=True,save_sha256=digest,
               vectors_sha256=save_sha256(vectors_file),rows=rows,checked_samples=report['checked_samples']))


def waveform(folder):
    saved=folder/'build/pulse_sequencer.json'
    meta=read_metadata(saved)
    hold=max(300,meta['settle_ticks']);values=[4]*hold+[0]*(hold+500)
    scenario=dict(ticks=len(values),inputs=[dict(at=e['fixture'],values=[(v>>i)&1 for v in values])
        for i,e in enumerate(meta['inputs']['controls'])],expect=[],
        observe=[e['fixture'] for name in ('active','selection','waveform') for e in meta['outputs'][name]])
    report=simulate(add_fixture(read_map(saved),meta),scenario,optimize_cycles=False)
    assert report['passed'] is not False,report['failures']
    traces={tuple(row['at']):row['values'] for row in report['observations']}
    points=[meta['outputs']['active'][2]['fixture']]+[e['fixture'] for e in meta['outputs']['selection']]+[meta['outputs']['waveform'][0]['fixture']]
    labels=['Active mode 2','Selection [0]','Selection [1]','Selection [2]','Waveform']
    end=len(traces[tuple(points[0])]);start=max(0,end-320)
    im,d=canvas('Pulse Sequencer · physical waveform','Mode 2: retained selection, 24-tick period, 50% duty cycle',680)
    left,right=250,1370
    for t in range(start,end+1,40):
        x=left+(right-left)*(t-start)/(end-start)
        d.line((x,150,x,570),fill='#dce5f0')
        d.text((x-12,590),str(t),font=font(17),fill=MUTED)
    for i,(point,label) in enumerate(zip(points,labels)):
        y=190+i*75;d.text((44,y),label,font=font(20),fill=INK)
        line=[]
        for j,value in enumerate(traces[tuple(point)][start:end]):
            x=left+(right-left)*j/(end-start)
            if line:line.append((x,line[-1][1]))
            line.append((x,y+25-24*value))
        d.line(line,fill=BLUE,width=3)
    im.save(folder/'visuals/behavior.png')
    save_artifact(folder.name,'behavior.report.json',dict(passed=True,save_sha256=save_sha256(saved),
        start_tick=start,end_tick=end,
        observations=[dict(at=p,values=traces[tuple(p)][start:end]) for p in points]))


def main():
    import sys
    names=sys.argv[1:] or ('alu_workbench','packet_router','pulse_sequencer','minesweeper')
    for name in names:
        folder=ROOT/'examples'/name; saved=folder/'build'/f'{name}.json'
        meta=read_metadata(saved)
        (folder/'visuals').mkdir(exist_ok=True)
        render_cells(read_map(saved),folder/'visuals/map.png',meta)
        specfile=ROOT/'tests/fixtures/examples'/name/'visualization.json'
        if specfile.is_file():
            spec=read(specfile);diagram(spec,folder/'visuals/architecture.png')
            if name in ('alu_workbench','packet_router'):measured_table(folder,name,spec)
        if name=='pulse_sequencer':waveform(folder)
        if name=='minesweeper':
            from arrowshdl.text_display import compile_display
            from arrowshdl.components import move
            all_cells=read_map(saved)
            views=[]
            for row in meta['project_graph']['components']:
                if row.get('kind')!='text':continue
                part,desc=compile_display(folder,row)
                self_port=desc['inputs']['signal'][0]['contact']
                placed_port=meta['components'][row['name']]['inputs']['signal'][0]['contact']
                part,desc=move(part,desc,[placed_port[0]-self_port[0],placed_port[1]-self_port[1]])
                assert all(all_cells.get(p)==c for p,c in part.items())
                target=folder/'visuals'/f'{row["name"]}.png'
                render_cells({p:all_cells[p] for p in part},target,{'top':row['text']})
                views.append(Image.open(target))
            status=Image.new('RGB',(max(v.width for v in views),sum(v.height for v in views)),'#f6f8fb')
            cursor=0
            for view in views:status.paste(view,(0,cursor));cursor+=view.height
            status.save(folder/'visuals/status.png')
            from tests.projects.examples.test_minesweeper import MinesweeperTests
            check=MinesweeperTests('test_safe_first_flood_count_win_lose_and_reset')
            check.test_safe_first_flood_count_win_lose_and_reset()
            game=check.report
            assert game['passed'] and game['save_sha256']==save_sha256(saved)
            state=game['snapshots'][0];mines=set(state['mines']);opened=set(state['opened'])
            im,d=canvas('Minesweeper · verified game states','Physical simulation · safe first click, victory and defeat',670)
            for col,(title,visible,loss) in enumerate((('First click',opened,False),('WIN',set(range(25))-mines,False),('LOSE',opened,True))):
                offset=44+col*465;d.text((offset,143),title,font=font(25),fill=INK)
                for i in range(25):
                    y,x=divmod(i,5);px=offset+x*72;py=200+y*72
                    value=''
                    if loss and i in mines:value='X'
                    elif i in visible:
                        count=sum(j in mines for j in range(25) if j!=i and abs(j//5-y)<=1 and abs(j%5-x)<=1)
                        value=str(count) if count else '.'
                    fill='#fee1df' if loss and i in mines else 'white' if i in visible else '#afc6e2'
                    d.rounded_rectangle((px,py,px+65,py+65),radius=7,fill=fill,outline='#839ab4')
                    d.text((px+23,py+13),value,font=font(28),fill=BLUE)
            d.text((44,615),'Verified map SHA-256: '+save_sha256(saved)[:24],font=font(18),fill=GREEN)
            im.save(folder/'visuals/behavior.png')
            save_artifact(folder.name,'behavior.report.json',dict(passed=True,save_sha256=save_sha256(saved),
                snapshots=game['snapshots']))
        print('Rendered:',name,'from',saved)


if __name__=='__main__':main()
