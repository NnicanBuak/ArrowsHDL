"""Audit source-built saves, visual evidence, packaged data and local links."""
from pathlib import Path
import argparse
import re
import subprocess
from tempfile import TemporaryDirectory
from urllib.parse import unquote

ROOT=Path(__file__).resolve().parent.parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheels',type=Path,help='Directory of freshly built platform wheels')
    args=parser.parse_args()
    from arrowshdl import compile
    from arrowshdl.mapdata import map_hash,read_map
    with TemporaryDirectory(prefix='arrowshdl-release-smoke-') as directory:
        source=Path(directory)/'half_adder.sv'
        source.write_text('module half_adder(input logic a,b,output logic sum,carry); '
                          'assign sum=a^b; assign carry=a&b; endmodule',encoding='utf-8')
        generated=Path(directory)/'half_adder.save.txt'
        result=compile(source,top='half_adder',out=generated)
        cells=read_map(generated)
        assert cells==result.cells and 0<len(cells)<=128
        assert map_hash(cells)==result.metadata['map_hash']

    tracked=subprocess.run(['git','ls-files','examples','tests/fixtures'],cwd=ROOT,
                           capture_output=True,text=True,check=True).stdout.splitlines()
    stale=[path for path in tracked if path.endswith('.json') and
           ('/build/' in path or path.endswith('.report.json'))]
    assert not stale,stale

    executable={'.py','.pyw','.ps1','.bat','.cmd','.sh','.js','.mjs','.ts','.exe'}
    assert not [p for p in (ROOT/'examples').rglob('*') if p.is_file() and p.suffix in executable]
    assert not (ROOT/'examples/pulse_sequencer/loop_mux8.v').exists()
    compiled_previews={
        'examples/alu_workbench/README.md':'visuals/map.png',
        'examples/packet_router/README.md':'visuals/map.png',
        'examples/pulse_sequencer/README.md':'visuals/map.png',
        'examples/minesweeper/README.md':'visuals/map.png',
        'tests/fixtures/historical/minesweeper/v1/README.md':'visuals/map.png',
        'tests/fixtures/historical/minesweeper/v2/README.md':'../visuals/board.png',
    }
    for relative,target in compiled_previews.items():
        path=ROOT/relative
        name=relative
        lines=path.read_text(encoding='utf-8-sig').splitlines()
        assert lines[0].startswith('![') and lines[0].endswith(f']({target})'),name
        assert not lines[1] and lines[2].startswith('# '),name
        assert (path.parent/target).is_file(),name

    image_count=sum(p.parent.name=='visuals' for p in (ROOT/'examples').rglob('*.png'))
    documentation=subprocess.run(['git','ls-files','*.md'],cwd=ROOT,
        capture_output=True,text=True,check=True).stdout.splitlines()
    files=[ROOT/name for name in documentation if (ROOT/name).is_file()]
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

    if args.wheels:
        from tools.release import verify
        verify(args.wheels)

    print(f'PASS: 1 lightweight source build, {image_count} visualizations, {links} local links')


if __name__=='__main__':main()
