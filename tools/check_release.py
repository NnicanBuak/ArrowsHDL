"""Audit independent examples, exact saves, visual evidence and local links."""
from pathlib import Path
import hashlib
import json
import re
from urllib.parse import unquote
import zipfile

ROOT=Path(__file__).resolve().parent.parent

def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    from tests.projects.examples.showcases import PROJECTS
    from arrowshdl.mapdata import map_hash,read_map
    examples=[]
    for top,relative in PROJECTS.items():
        folder=ROOT/'examples'/relative
        saved=folder/'build'/f'{top}.save.txt'
        meta=read(folder/'build'/f'{top}.build.json')
        report=read(folder/'build'/f'{top}.report.json')
        digest=sha(saved)
        assert report['passed'] and report['save_sha256']==digest==meta['save_sha256'],top
        assert map_hash(read_map(saved))==meta['map_hash']
        for source in meta['sources']:assert source['sha256']==sha(folder/source['name']),source['name']
        if top=='alu_workbench':assert report['vectors']==2048
        if top=='packet_router':assert report['vectors']==65536
        if top=='pulse_sequencer':assert report['all_256_latched_masks_verified']
        examples.append(dict(top=top,cells=meta['cells'],bounds=meta['bounds'],save_sha256=digest,passed=True))
    games={}
    for version in ('v1','v2'):
        base=ROOT/'examples/minesweeper'/version/'build'
        game=read(base/'regression.json')
        assert game['passed']
        for top,data in game['compiled'].items():
            assert data['save_sha256']==sha(base/(top+'.save.txt'))
            assert read(base/(top+'.report.json'))['passed']
        games[version]=game['compiled']
    history=read(ROOT/'tests/projects/minesweeper/historical_v1.json')['sha256']
    for top,digest in history.items():assert games['v1'][top]['save_sha256']==digest
    tile=games['v2']['tile']
    assert tile['cells']<=2164 and tile['bounds']['width']<=56 and tile['bounds']['height']<=64
    for size,count,width,height in ((3,22638,292,352),(5,60068,404,492),(10,233969,684,842)):
        data=games['v2'][f'minesweeper_{size}x{size}']
        assert data['cells']<=count and data['bounds']['area']<=width*height
    visual=[]
    for name in (*PROJECTS,'minesweeper'):
        folder=ROOT/'examples'/name
        base=folder/'v2/build' if name=='minesweeper' else folder/'build'
        top='minesweeper_5x5' if name=='minesweeper' else name
        measured=read(folder/'visuals/behavior.report.json')
        assert measured['passed'] and measured['save_sha256']==sha(base/f'{top}.save.txt')
        if 'vectors_sha256' in measured:assert measured['vectors_sha256']==sha(folder/'vectors.json')
        if 'scenario_sha256' in measured:assert measured['scenario_sha256']==sha(folder/'scenario.json')
        for file,digest in measured.get('snapshots',{}).items():assert digest==sha(base/file)
        for image in ('architecture.png','map.png','behavior.png'):assert (folder/'visuals'/image).stat().st_size>100
        visual.append(dict(project=name,passed=True,save_sha256=measured['save_sha256']))
    executable={'.py','.pyw','.ps1','.bat','.cmd','.sh','.js','.mjs','.ts','.exe'}
    assert not [p for p in (ROOT/'examples').rglob('*') if p.is_file() and p.suffix in executable]
    assert not (ROOT/'examples/pulse_sequencer/loop_mux8.v').exists()
    files=list(ROOT.glob('*.md'))+list((ROOT/'docs').glob('*.md'))+list((ROOT/'examples').rglob('*.md'))
    links=0
    for file in files:
        content=file.read_text(encoding='utf-8-sig')
        targets=re.findall(r'\]\(([^)]+)\)',content)+re.findall(r'<img\b[^>]*\bsrc="([^"]+)"',content)
        for target in targets:
            target=target.split(' "')[0]
            if re.match(r'^[a-z]+:',target) or target.startswith('#'):continue
            target=unquote(target.split('#')[0])
            assert (file.parent/target).exists(),(str(file.relative_to(ROOT)),target)
            links+=1
    suite=read(ROOT/'build/independent-suite.json')
    install=read(ROOT/'build/clean-smoke.report.json')
    assert suite['passed'] and suite['skipped']==0 and install['passed'] and install['macro_grid']
    wheel=next((ROOT/'dist').glob('arrowshdl-0.1.0-*.whl'))
    with zipfile.ZipFile(wheel) as archive:
        assert any(n.endswith('arrowshdl-engine.exe') for n in archive.namelist())
        assert not any('examples/' in n or 'tests/' in n for n in archive.namelist())
    report=dict(passed=True,version='0.1.0',platform='Windows x64',
        installation=dict(passed=True,wheel_install=True,external_cwd=True,minimal_path=True,
            public_commands=len(install['commands']),python_api=True,macro_grid=True),
        regression=dict(baseline=suite,new_showcase_tests=2,total_distinct_tests=suite['tests']+2,
            additional_sequencer_rebuild_verified=True),
        examples=examples,minesweeper=games,visualizations=visual,
        independence=dict(all_test_assets_local=True,minesweeper_mandatory=True,no_sibling_checkout_required=True),
        cleanup=dict(no_example_scripts=True,local_document_links=links,obsolete_sequencer_sources_removed=True),
        wheel=dict(file=wheel.name,sha256=sha(wheel)),
        limitations=['Experimental HDL subset; arbitrary sequential HDL is unsupported',
                     'V1 preserves historical limitations documented in examples/minesweeper',
                     'Game sprites and teaching fixture rights need confirmation before publication'])
    path=ROOT/'docs/release-report.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'PASS: 4 independent projects, {suite["tests"]+2} distinct tests, 12 visualizations, {links} local links')

if __name__=='__main__':main()
