"""Reproduce diagrams and measured behavior from the repository's final saves."""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw
from arrowshdl.map_preview import font, render_cells
from arrowshdl.mapdata import read_map
from arrowshdl.simulation import simulate
import arrowshdl
from arrowshdl.test_harness import add_fixture, make_scenario

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
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
    compiled=arrowshdl.build(folder/'project.toml')
    meta=compiled.metadata
    from tests.projects.examples.showcases import alu,route
    if top=='alu_workbench':
        cases=((15,1,0),(3,5,1),(6,10,2),(6,10,3),(6,10,4),(6,0,5),(9,0,6),(0,13,7))
        vectors=[dict(inputs=dict(a=a,b=b,operation=op),expect=alu(a,b,op)) for a,b,op in cases]
    else:
        cases=((3,37,3,3),(3,5,3,3),(3,37,3,1),(1,37,3,3),(3,37,0,3),(35,37,3,2))
        vectors=[dict(inputs=dict(frame0=f0,frame1=f1,valid=valid,ready=ready),
                      expect=route(f0,f1,valid,ready)) for f0,f1,valid,ready in cases]
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
    digest=meta['save_sha256']
    d.text((44,im.height-40),'PASS · save SHA-256: '+digest[:20]+'…',font=font(18),fill=GREEN)
    im.save(folder/'visuals/behavior.png')


def waveform(folder):
    compiled=arrowshdl.build(folder/'project.toml')
    meta=compiled.metadata
    hold=max(300,meta['settle_ticks']);values=[4]*hold+[0]*(hold+500)
    scenario=dict(ticks=len(values),inputs=[dict(at=e['fixture'],values=[(v>>i)&1 for v in values])
        for i,e in enumerate(meta['inputs']['controls'])],expect=[],
        observe=[e['fixture'] for name in ('active','selection','waveform') for e in meta['outputs'][name]])
    report=simulate(add_fixture(compiled.cells,meta),scenario,optimize_cycles=False)
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


def main():
    import sys
    names=sys.argv[1:] or ('mini_calculator','alu_workbench','packet_router','pulse_sequencer','minesweeper')
    for name in names:
        folder=ROOT/'examples'/name; saved=folder/'build'/f'{name}.save.txt'
        compiled=arrowshdl.build(folder/'project.toml',out=saved,layout='compact' if name=='minesweeper' else 'auto')
        meta=compiled.metadata
        (folder/'visuals').mkdir(exist_ok=True)
        temporary=folder/'visuals/map.rendering.png'
        render_cells(read_map(saved),temporary,meta)
        temporary.replace(folder/'visuals/map.png')
        specfile=ROOT/'tests/fixtures/examples'/name/'visualization.json'
        if specfile.is_file():
            spec=read(specfile);diagram(spec,folder/'visuals/architecture.png')
            if name in ('alu_workbench','packet_router'):measured_table(folder,name,spec)
        if name=='pulse_sequencer':waveform(folder)
        if name=='minesweeper' and meta['layout']=='fixed-native-verilog':
            all_cells=compiled.cells
            frame=meta['instances']['rows[0].cols[0].tile']['bounds']
            x,y=frame['min'];width,height=frame['width'],frame['height']
            tile={p:c for p,c in all_cells.items() if x<=p[0]<x+width and y<=p[1]<y+height}
            render_cells(tile,folder/'visuals/cell.png',{'top':'Minesweeper V2 cell'})
            pixels=[p for name,p in meta['probes'].items() if name.startswith('status:')]
            left,right=min(p[0] for p in pixels),max(p[0] for p in pixels)
            top,bottom=min(p[1] for p in pixels),max(p[1] for p in pixels)
            status={p:c for p,c in all_cells.items() if left<=p[0]<=right and top<=p[1]<=bottom}
            render_cells(status,folder/'visuals/status.png',{'top':'Minesweeper V2 status displays'})
        print('Rendered:',name,'from',saved)


if __name__=='__main__':main()
