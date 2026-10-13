from itertools import islice
import json
import unittest
from arrowshdl.mapdata import read_map,save_sha256,map_hash
from tests.projects.examples.artifacts import save_artifact
from arrowshdl.test_harness import add_fixture,make_scenario
from arrowshdl.simulation import simulate
from tests.projects.examples.catalog import ROOT
from tests.projects.examples.showcases import vectors
from arrowshdl.artifacts import read_metadata

class ShowcaseTests(unittest.TestCase):
    def check_project(self,top):
        folder=ROOT/'examples'/top
        saved=folder/'build'/f'{top}.json'
        meta=read_metadata(saved)
        cells=read_map(saved)
        self.assertEqual(map_hash(cells),meta['map_hash'])
        fixture=add_fixture(cells,meta)
        count=min(4096,1000000//meta['settle_ticks'])
        self.assertGreater(count,0)
        summary=dict(passed=True,top=top,save_sha256=save_sha256(saved),vectors=0,checked_samples=0,batches=0,
            oracle='independent Python arithmetic / frame routing protocol',failures=[])
        stream=iter(vectors(top))
        while batch:=list(islice(stream,count)):
            report=simulate(fixture,make_scenario(meta,batch,compressed=True),timeout=120)
            summary['passed'] &= report['passed'];summary['vectors']+=len(batch)
            summary['checked_samples']+=report['checked_samples'];summary['batches']+=1
            summary['failures']+=report['failures'][:10]
            self.assertTrue(report['passed'],report['failures'])
        save_artifact(top,f'{top}.report.json',summary)

    def test_alu_all_2048_words(self):self.check_project('alu_workbench')
    def test_router_all_65536_frames_controls_and_backpressure(self):self.check_project('packet_router')
