"""Periods, held clicks, priority and history are independent functional checks."""
import json
from pathlib import Path
import unittest

from arrowshdl.mapdata import read_map,save_sha256
from tests.projects.examples.artifacts import save_artifact
from arrowshdl.simulation import simulate
from arrowshdl.test_harness import add_fixture
from arrowshdl.artifacts import read_metadata

ROOT=Path(__file__).resolve().parents[3]


def run():
    folder=ROOT/'examples/pulse_sequencer'; build=folder/'build'
    meta=read_metadata(build/'pulse_sequencer.json')
    cells=add_fixture(read_map(build/'pulse_sequencer.json'),meta)
    coordinates={name:[e['fixture'] for e in es] for name,es in meta['outputs'].items()}
    display=meta['components']['history']['inputs']['signal'][0]['contact']
    pixels=[[display[0]+i,display[1]] for i in range(64)]
    points=coordinates['active']+coordinates['selection']+coordinates['waveform']+pixels
    periods=(0,20,24,32,40,48,64,80)
    checks=0; snapshots=[]
    hold=max(300,meta['settle_ticks']); tail=hold+500
    for mode,period in enumerate(periods):
        controls=[1<<mode]*hold+[0]*tail
        scenario=dict(ticks=len(controls),inputs=[dict(at=e['fixture'],values=[(v>>i)&1 for v in controls])
                for i,e in enumerate(meta['inputs']['controls'])],expect=[],observe=points)
        report=simulate(cells,scenario,optimize_cycles=False,timeout=60)
        traces={tuple(row['at']):row['values'] for row in report['observations']}
        def word(name,t): return sum(traces[tuple(p)][t]<<i for i,p in enumerate(coordinates[name]))
        assert word('active',-1)==1<<mode,(mode,word('active',-1))
        assert word('selection',-1)==mode,(mode,word('selection',-1))
        wave=traces[tuple(coordinates['waveform'][0])][-400:]
        if period:
            assert set(wave)=={0,1}
            assert all(wave[t]==wave[t-period] for t in range(period,len(wave)))
            assert sum(wave[-period:])==period//2
        else: assert not any(wave)
        for i,p in enumerate(pixels):
            assert traces[tuple(p)][-300:]==traces[tuple(pixels[0])][-300-i:len(controls)-i],(mode,i)
        checks+=len(points)*len(controls)
        if mode==2:
            save_artifact('pulse_sequencer','scenario.json',scenario)
            save_artifact('pulse_sequencer','waveform.trace.json',report)
        snapshots.append(dict(mode=mode,period_ticks=period))
    masks=[];frames=[];pressed=0
    for mask in range(256):
        masks.extend([pressed^mask,0]);frames.extend([hold,hold]);pressed=mask
    scenario=dict(ticks=sum(frames),frame_ticks=frames,inputs=[dict(at=e['fixture'],values=[(v>>i)&1 for v in masks])
                  for i,e in enumerate(meta['inputs']['controls'])],expect=[],observe=points[:11])
    # Each simulator request has a million-tick limit. Every batch starts from
    # cold state and first selects its own starting mask.
    batch_size=max(1,1000000//(2*hold))
    for start in range(0,256,batch_size):
        stop=min(256,start+batch_size); previous=0; values=[]
        for mask in range(start,stop):values.extend([previous^mask,0]);previous=mask
        report=simulate(cells,dict(ticks=2*hold*(stop-start),hold_ticks=hold,
            inputs=[dict(at=e['fixture'],values=[(v>>i)&1 for v in values]) for i,e in enumerate(meta['inputs']['controls'])],
            expect=[],observe=points[:11]),optimize_cycles=False,timeout=90)
        traces=[row['values'] for row in report['observations']]
        for index,mask in enumerate(range(start,stop)):
            t=index*2+1
            active=sum(traces[i][t]<<i for i in range(8)); code=sum(traces[8+i][t]<<i for i in range(3))
            assert active==mask,(mask,active)
            assert code==((mask&-mask).bit_length()-1 if mask else 0),(mask,code)
    summary=dict(passed=True,save_sha256=save_sha256(build/'pulse_sequencer.json'),
        all_256_latched_masks_verified=True,held_clicks=True,history_pixels=64,modes=snapshots,
        checked_samples=checks+256*11,oracle='independent periods, priority encoder and one-tick history relation')
    save_artifact('pulse_sequencer','pulse_sequencer.report.json',summary)
    return summary


class SequencerTests(unittest.TestCase):
    def test_modes_held_buttons_priority_and_history(self): self.assertTrue(run()['passed'])
