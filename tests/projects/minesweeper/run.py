"""Compile both project variants and run independent game rules against the saves."""
import argparse
import json
import os
from pathlib import Path

from arrowshdl.scheme import build_scheme
from arrowshdl.mapdata import map_hash,read_map,write_json,save_sha256


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',required=True,type=Path)
    parser.add_argument('--out',type=Path)
    parser.add_argument('--version',choices=('v1','v2'),default='v2')
    parser.add_argument('--sizes',nargs='+',type=int,default=[3,5,10])
    parser.add_argument('--matrix',action='store_true')
    parser.add_argument('--reuse',action='store_true',help='Проверить ранее скомпилированные карты с проверкой эталонных хешей')
    args=parser.parse_args()
    source=args.project/args.version
    args.sizes=[size for size in args.sizes if (source/f'minesweeper_{size}x{size}.toml').is_file()]
    output=(args.out or args.project)/args.version/'build'
    output.mkdir(parents=True,exist_ok=True)
    built={}
    for top,manifest in [('tile','cell.toml')]+[(f'minesweeper_{size}x{size}',f'minesweeper_{size}x{size}.toml') for size in args.sizes]:
        if args.reuse:
            cells=read_map(output/(top+'.save.txt'))
            meta=json.loads((output/(top+'.build.json')).read_text(encoding='utf-8'))
        else:
            cells,meta=build_scheme(source/manifest,output,timeout=600)
            cells=read_map(output/(top+'.save.txt'))
            meta=json.loads((output/(top+'.build.json')).read_text(encoding='utf-8'))
        # Legacy layout records are observations, never an input arrow map.
        binding=source/('cell.bindings.json' if top=='tile' else top+'.bindings.json')
        layout=json.loads(binding.read_text(encoding='utf-8'))
        assert map_hash(cells)==layout['map_hash']
        write_json(output/(top+'.layout.json'),layout)
        built[top]=dict(map_hash=meta['map_hash'],save_sha256=save_sha256(output/(top+'.save.txt')),cells=len(cells),bounds=meta['bounds'])
        if args.version=='v1':
            historical=json.loads(Path(__file__).with_name('historical_v1.json').read_text())
            assert built[top]['save_sha256']==historical['sha256'][top], 'Изменены точные байты исторического сохранения V1'
        print('Compiled:',top,len(cells),flush=True)
    os.environ['ARROWSHDL_MINES_BUILD']=str(output.resolve())
    from .snap_verify import verify_cell,verify_board
    cell=verify_cell('tile')
    results=[]
    for size in args.sizes:
        runs=[]
        for seed,first in ((123456789,None),(987654321,0)):
            result=verify_board(size,seed,first=first)
            runs.append(result);results.append(result)
        if args.matrix and args.version=='v2':
            from .first_click_matrix import verify as matrix
            from .first_click_timing import verify as timing
            extra=[matrix(f'minesweeper_{size}x{size}'),timing(f'minesweeper_{size}x{size}')]
            runs.extend(extra);results.extend(extra)
        top=f'minesweeper_{size}x{size}'
        write_json(output/(top+'.report.json'),dict(passed=True,**built[top],runs=runs))
    if args.version=='v2':
        limits={3:(22638,292,352),5:(60068,404,492),10:(233969,684,842)}
        assert built['tile']['cells']<=2164
        assert built['tile']['bounds']['width']<=56 and built['tile']['bounds']['height']<=64
        for size in args.sizes:
            got=built[f'minesweeper_{size}x{size}'];count,width,height=limits[size]
            assert got['cells']<=count and got['bounds']['area']<=width*height
    write_json(output/'tile.report.json',dict(passed=True,**built['tile'],checks=cell))
    write_json(output/'regression.json',dict(passed=True,version=args.version,compiled=built,cell=cell,boards=results))
    return 0


if __name__=='__main__':raise SystemExit(main())
