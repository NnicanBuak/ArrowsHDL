"""Compile two connected modules and verify both observed outputs."""
from itertools import product
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from verilog_compile import compile_file
from test_harness import run_vectors


def run():
    here = Path(__file__).resolve().parent
    folder = here / 'build'
    cells, meta = compile_file(here / 'composed_logic.v', 'composed_logic', folder)
    vectors = []
    for a, b, c, d in product(range(2), repeat=4):
        p = ((1-a)^b) & (a|c)
        y = ((1-p)^c) & (p|d)
        vectors.append({'inputs': dict(a=a, b=b, c=c, d=d), 'expect': dict(p=p, y=y)})
    _, report = run_vectors(cells, meta, vectors + list(reversed(vectors)), folder,
                            'composed_logic', compressed=True)
    if not report['passed']:
        raise RuntimeError(report['failures'])
    print({'cells': len(cells), 'bounds': meta['full_bounds'],
           'search': meta['placement_search'], 'checked_samples': report['checked_samples']})


if __name__ == '__main__':
    run()
