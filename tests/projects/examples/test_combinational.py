"""Exhaustive arithmetic/Boolean checks of the final saves, not synthesis graphs."""
from itertools import islice
import json
from pathlib import Path
import unittest

from arrowshdl.mapdata import read_map,map_hash,save_sha256,write_json
from arrowshdl.simulation import simulate
from arrowshdl.test_harness import add_fixture,make_scenario
from tests.projects.examples.catalog import ROOT,PROJECTS,vectors


class SavedCombinationalTests(unittest.TestCase):
    def test_all_saved_combinational_examples(self):
        for top,rel in PROJECTS.items():
            if top in ('digit3','loop_mux8','reference'):continue
            with self.subTest(top=top):
                folder=ROOT/'tests/fixtures/circuits'/rel/'build'
                saved=folder/f'{top}.save.txt'
                cells=read_map(saved)
                meta=json.loads((folder/f'{top}.build.json').read_text(encoding='utf-8'))
                self.assertEqual(map_hash(cells),meta['map_hash'])
                fixture=add_fixture(cells,meta)
                summary=dict(passed=True,top=top,save_sha256=save_sha256(saved),map_hash=map_hash(cells),
                             simulated_map_hash=map_hash(fixture),vectors=0,checked_samples=0,batches=0,
                             oracle='independent integer arithmetic / Boolean equations',failures=[])
                iterator=iter(vectors(top))
                batch_size=min(4096,1000000//meta['settle_ticks'])
                while batch:=list(islice(iterator,batch_size)):
                    report=simulate(fixture,make_scenario(meta,batch,compressed=True),optimize_cycles=False,timeout=120)
                    summary['vectors']+=len(batch)
                    summary['checked_samples']+=report['checked_samples']
                    summary['batches']+=1
                    summary['passed'] &= report['passed']
                    summary['failures'] += report['failures'][:10]
                write_json(folder/f'{top}.report.json',summary)
                self.assertTrue(summary['passed'],summary['failures'])


if __name__=='__main__':unittest.main()
