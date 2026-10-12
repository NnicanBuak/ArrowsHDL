"""Native application regressions use independent expectations on saved cells."""
from itertools import product,islice
import json
import unittest

from arrowshdl.mapdata import read_map,save_sha256,write_json
from arrowshdl.simulation import simulate
from arrowshdl.test_harness import add_fixture
from tests.projects.examples.catalog import ROOT
from tests.helpers.reference_adder8.protocol import manifest,scenario


class NativeExampleTests(unittest.TestCase):
    def test_digit3_all_values_and_64_transitions(self):
        folder=ROOT/'tests/fixtures/circuits/digit3'
        meta=json.loads((folder/'build/digit3.build.json').read_text())
        observations=meta['observations']
        cells=add_fixture(read_map(folder/'build/digit3.save.txt'),meta)
        masks=(0x3f,0x06,0x5b,0x4f,0x66,0x6d,0x7d,0x07)
        values=[v for old,new in product(range(8),repeat=2) for v in (old,new,old)]
        data=[v for v in values for _ in range(25)]
        phases=[d for v in values for d in [160]+[1]*24]
        test=dict(ticks=sum(phases),frame_ticks=phases,expect=[],
            inputs=[dict(at=e['fixture'],values=[(v>>e['index'])&1 for v in data]) for e in meta['inputs']['n']],
            assert_=[dict(at=p,values=[(masks[v]>>i)&1 for v in data]) for i,p in enumerate(observations['segments'])])
        test['assert']=test.pop('assert_')
        write_json(folder/'scenario.json',test)
        checks=0
        for optimized in (False,True):
            report=simulate(cells,test,optimize_cycles=optimized)
            self.assertTrue(report['passed'],report['failures'])
            checks+=report['checked_samples']
        write_json(folder/'build/digit3.report.json',dict(passed=True,save_sha256=save_sha256(folder/'build/digit3.save.txt'),
            all_64_transitions=True,steady_window_ticks=24,checked_samples=checks,cycle_modes=[False,True]))

    def test_loop_mux8_held_simultaneous_masks_and_history(self):
        from tests.projects.examples.loop_oracle import run
        report=run()
        self.assertTrue(report['passed'])

    def test_reference_adder_all_65536_pairs(self):
        folder=ROOT/'tests/fixtures/circuits/reference_adder8'
        saved=folder/'build/reference.save.txt'
        original=read_map(saved)
        meta=manifest(original)
        fixture=add_fixture(original,meta)
        cases=[dict(a=a,b=b) for a,b in ((0,0),(255,0),(255,255),(85,170),(127,1),(0,0))]
        write_json(folder/'scenario.json',scenario(meta,cases))
        summary=dict(passed=True,save_sha256=save_sha256(saved),vectors=0,checked_samples=0,
                     oracle='independent Python integer a+b',operation_ticks=160,batches=0,failures=[])
        pairs=iter(product(range(256),repeat=2))
        while batch:=list(islice(pairs,4096)):
            report=simulate(fixture,scenario(meta,[dict(a=a,b=b) for a,b in batch]),optimize_cycles=False,timeout=120)
            summary['vectors']+=len(batch)
            summary['checked_samples']+=report['checked_samples']
            summary['batches']+=1
            summary['passed'] &= report['passed']
            summary['failures']+=report['failures'][:10]
        write_json(folder/'build/reference.report.json',summary)
        self.assertTrue(summary['passed'],summary['failures'])


if __name__=='__main__':unittest.main()
