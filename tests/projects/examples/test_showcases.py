from itertools import islice
from pathlib import Path
import tempfile
import unittest
from arrowshdl import build
from arrowshdl.mapdata import read_map,map_hash
from arrowshdl.test_harness import add_fixture,make_scenario
from arrowshdl.simulation import simulate
from tests.projects.examples.catalog import ROOT
from tests.projects.examples.showcases import vectors

class ShowcaseTests(unittest.TestCase):
    def check_project(self,top):
        folder=ROOT/'examples'/top
        with tempfile.TemporaryDirectory(prefix='arrowshdl-showcase-') as directory:
            saved=Path(directory)/f'{top}.save.txt'
            result=build(folder/'project.toml',out=saved)
            meta=result.metadata
            cells=read_map(saved)
            self.assertEqual(cells,result.cells)
        self.assertEqual(map_hash(cells),meta['map_hash'])
        fixture=add_fixture(cells,meta)
        count=min(4096,1000000//meta['settle_ticks'])
        self.assertGreater(count,0)
        summary=dict(passed=True,vectors=0,checked_samples=0,batches=0,
            oracle='independent Python arithmetic / frame routing protocol',failures=[])
        stream=iter(vectors(top))
        while batch:=list(islice(stream,count)):
            report=simulate(fixture,make_scenario(meta,batch,compressed=True),timeout=120)
            summary['passed'] &= report['passed'];summary['vectors']+=len(batch)
            summary['checked_samples']+=report['checked_samples'];summary['batches']+=1
            summary['failures']+=report['failures'][:10]
            self.assertTrue(report['passed'],report['failures'])
        self.assertTrue(summary['passed'],summary['failures'])

    def test_alu_all_2048_words(self):self.check_project('alu_workbench')
    def test_router_all_65536_frames_controls_and_backpressure(self):self.check_project('packet_router')
