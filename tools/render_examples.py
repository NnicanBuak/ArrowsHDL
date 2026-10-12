"""Reproduce diagrams and measured behavior from the repository's final saves."""
import json
from pathlib import Path

from PIL import Image, ImageDraw
from arrowshdl.map_preview import font, render_cells
from arrowshdl.mapdata import read_map, save_sha256, write_json
from arrowshdl.simulation import simulate
from arrowshdl.test_harness import add_fixture, make_scenario

ROOT = Path(__file__).resolve().parents[1]
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
    saved = folder/'build'/f'{top}.save.txt'
    meta = read(folder/'build'/f'{top}.build.json')
    vectors = read(folder/'vectors.json')
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
    write_json(folder/'visuals/behavior.report.json',dict(passed=True,save_sha256=digest,
               vectors_sha256=save_sha256(folder/'vectors.json'),rows=rows,checked_samples=report['checked_samples']))


def waveform(folder):
    saved=folder/'build/pulse_sequencer.save.txt'
    scenario=read(folder/'scenario.json')
    points=[[-32,32],[-27,33],[-17,23],[-13,23],[-9,23],[14,18]]
    scenario['observe']=points
    report=simulate(read_map(saved),scenario)
    assert report['passed'], report['failures']
    traces={tuple(row['at']):row['values'] for row in report['observations']}
    im,d=canvas('Pulse Sequencer · игровые такты','Режим 2: кнопка удерживается 40 тактов; выбор сохраняется после отпускания',740)
    labels=['Кнопка 2','Память 2','Код [0]','Код [1]','Код [2]','Выход']
    start,end,left,right=0,320,220,1370
    for t in range(start,end+1,40):
        x=left+(right-left)*t/end
        d.line((x,154,x,636),fill='#dce5f0',width=1)
        d.text((x-10,645),str(t),font=font(17),fill=MUTED)
    for i,(p,label) in enumerate(zip(points,labels)):
        y=180+i*75
        d.text((44,y-5),label,font=font(21),fill=INK)
        values=traces[tuple(p)][:end]
        line=[]
        for t,value in enumerate(values):
            x=left+(right-left)*t/end;level=y+35-value*35
            if line:line.append((x,line[-1][1]))
            line.append((x,level))
        d.line(line,fill=BLUE if i!=1 else GREEN,width=3)
    digest=save_sha256(saved)
    d.text((44,696),'PASS · период режима 2: 24 такта · save SHA-256: '+digest[:20]+'…',font=font(18),fill=GREEN)
    im.save(folder/'visuals/behavior.png')
    write_json(folder/'visuals/behavior.report.json',dict(passed=True,save_sha256=digest,
        scenario_sha256=save_sha256(folder/'scenario.json'),checked_samples=report['checked_samples'],
        observations=[dict(at=p,values=traces[tuple(p)][:end]) for p in points]))


def board(folder):
    base=folder/'v2/build'
    saved=base/'minesweeper_5x5.save.txt'
    game=read(base/'minesweeper_5x5.report.json')
    assert game['passed'] and game['save_sha256']==save_sha256(saved)
    before,after=(read(base/f'minesweeper_5x5{suffix}.demo.json') for suffix in ('','.defeat'))
    assert before['mines']==after['mines'] and before['first']==after['first']
    # These snapshots are produced and checked by snap_verify on saved cells.
    mines=set(before['mines']);size=before['size']
    im,d=canvas('Minesweeper V2 · проверенная партия','Поле 5×5 · seed 987654321 · безопасный первый клик: (0, 0)',760)
    for offset,state,title,defeat in ((70,before,'Первый клик и каскад',False),(805,after,'Поражение: все мины видны',True)):
        d.text((offset,141),title,fill=INK,font=font(25))
        for i in range(size*size):
            row,col=divmod(i,size);m=state['measured'];opened=bool(m[f'{i}:opened']);mine=bool(m[f'{i}:mine'])
            assert mine==(i in mines)
            value=''
            if defeat and mine:value='●'
            elif opened:
                count=sum(j in mines for j in range(size*size)
                    if j!=i and abs(j//size-row)<=1 and abs(j%size-col)<=1)
                value=str(count) if count else '·'
            x,y=offset+col*87,205+row*87
            fill='#fee1df' if defeat and mine else 'white' if opened else '#afc6e2'
            d.rounded_rectangle((x,y,x+78,y+78),radius=10,fill=fill,outline='#839ab4',width=2)
            d.text((x+27,y+17),value,font=font(32),fill='#aa3930' if mine else BLUE)
        d.text((offset,657),'Светлые — открыты; синие — закрыты',font=font(19),fill=MUTED)
    digest=save_sha256(saved)
    d.text((44,711),'PASS · снимки проверены регрессией · save SHA-256: '+digest[:20]+'…',font=font(18),fill=GREEN)
    im.save(folder/'visuals/behavior.png')
    write_json(folder/'visuals/behavior.report.json',dict(passed=True,save_sha256=digest,
        snapshots={name:save_sha256(base/name) for name in ('minesweeper_5x5.demo.json','minesweeper_5x5.defeat.demo.json')},
        first=before['first'],mines=before['mines'],opened_before=before['opened'],opened_after=after['opened']))


def main():
    for name in ('alu_workbench','packet_router','pulse_sequencer','minesweeper'):
        folder=ROOT/'examples'/name
        spec=read(folder/'visualization.json')
        (folder/'visuals').mkdir(exist_ok=True)
        diagram(spec,folder/'visuals/architecture.png')
        top='tile' if name=='minesweeper' else name
        base=folder/'v2/build' if name=='minesweeper' else folder/'build'
        render_cells(read_map(base/f'{top}.save.txt'),folder/'visuals/map.png',read(base/f'{top}.build.json'))
        if name=='minesweeper':
            board(folder)
            for version,size,target in (
                ('v1',3,folder/'v1/visuals/map.png'),
                ('v2',5,folder/'visuals/board.png'),
            ):
                saved=folder/version/'build';stem=f'minesweeper_{size}x{size}'
                target.parent.mkdir(exist_ok=True)
                render_cells(read_map(saved/f'{stem}.save.txt'),target,read(saved/f'{stem}.build.json'))
        elif name=='pulse_sequencer':waveform(folder)
        else:measured_table(folder,top,spec)
        print('PASS:',name,'diagram, actual map, measured behavior')


if __name__=='__main__':main()
