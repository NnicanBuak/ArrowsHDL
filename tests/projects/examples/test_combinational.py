"""Exhaustive arithmetic/Boolean checks of final encoded saves."""
from itertools import islice
from pathlib import Path
import tempfile
import tomllib
import unittest

from arrowshdl import compile
from arrowshdl.mapdata import read_map,map_hash
from arrowshdl.simulation import simulate
from arrowshdl.test_harness import add_fixture,make_scenario
from tests.projects.examples.catalog import ROOT,PROJECTS,vectors


class SavedCombinationalTests(unittest.TestCase):
    def test_all_saved_combinational_examples(self):
        for top,rel in PROJECTS.items():
            if top in ('digit3','loop_mux8','reference'):continue
            with self.subTest(top=top):
                with tempfile.TemporaryDirectory(prefix='arrowshdl-test-') as directory:
                    saved=Path(directory)/f'{top}.save.txt'
                    project=ROOT/'tests/fixtures/circuits'/rel/'project.toml'
                    config=tomllib.loads(project.read_text(encoding='utf-8-sig'))
                    sources=[project.parent/name for name in config['sources']]
                    result=compile(sources,top=config['top'],out=saved,
                                   standard=config.get('language',{}).get('standard','1800-2023'))
                    meta=result.metadata
                    cells=read_map(saved)
                    self.assertEqual(cells,result.cells)
                self.assertEqual(map_hash(cells),meta['map_hash'])
                fixture=add_fixture(cells,meta)
                summary=dict(passed=True,vectors=0,checked_samples=0,batches=0,failures=[])
                iterator=iter(vectors(top))
                batch_size=min(4096,1000000//meta['settle_ticks'])
                while batch:=list(islice(iterator,batch_size)):
                    report=simulate(fixture,make_scenario(meta,batch,compressed=True),optimize_cycles=False,timeout=120)
                    summary['vectors']+=len(batch)
                    summary['checked_samples']+=report['checked_samples']
                    summary['batches']+=1
                    summary['passed'] &= report['passed']
                    summary['failures'] += report['failures'][:10]
                self.assertTrue(summary['passed'],summary['failures'])


if __name__=='__main__':unittest.main()
