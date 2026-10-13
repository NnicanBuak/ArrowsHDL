from pathlib import Path
import json
import os
from arrowshdl.arrowasm import Cell
from arrowshdl.arrow_layout import destinations,bounds_of
from arrowshdl.mapdata import read_map,map_hash,save_sha256
from arrowshdl.simulation import simulate as _simulate

BUILD = Path(os.environ['ARROWSHDL_MINES_BUILD'])
SOURCE = Path(os.environ['ARROWSHDL_MINES_SOURCE'])
DIRECTIONS = ((-1,-1),(0,-1),(1,-1),(-1,0),(1,0),(-1,1),(0,1),(1,1))
EXPECTED = (0b0111111,0b0000110,0b1011011,0b1001111,0b1100110,0b1101101,0b1111101,0b0000111,0b1111111,0b1101111)

def load_layout(stem):
    name = 'cell.bindings.json' if stem == 'tile' else f'{stem}.bindings.json'
    return json.loads((SOURCE/name).read_text(encoding='utf-8-sig'))

def simulate(cells,scenario,optimize_cycles=False,timeout=240):
    return _simulate(cells,scenario,optimize_cycles,timeout,limits={'nodes':2000000,'ticks':2000000})
