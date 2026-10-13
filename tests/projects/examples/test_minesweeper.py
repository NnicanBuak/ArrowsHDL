"""Independent board oracle and signal-driven WIN/LOSE checks on saved cells."""
from pathlib import Path
import unittest

import arrowshdl
import json
import tempfile
from unittest.mock import patch
from arrowshdl.mapdata import read_map,save_sha256
from tests.projects.examples.artifacts import save_artifact
from arrowshdl.simulation import simulate
from arrowshdl.test_harness import add_fixture

ROOT=Path(__file__).resolve().parents[3]
SEGMENTS=(63,6,91,79,102,109,125,7,127)


def neighbors(index):
    y,x=divmod(index,5)
    return {j for j in range(25) if j!=index and abs(j//5-y)<=1 and abs(j%5-x)<=1}


def flood(mines,selected):
    opened=set(selected)-mines;pending=list(opened)
    while pending:
        i=pending.pop()
        if not (neighbors(i)&mines):
            for j in neighbors(i)-mines-opened:
                opened.add(j);pending.append(j)
    return opened


class MinesweeperTests(unittest.TestCase):
    def check_reference_board(self,compiled,saved):
        from arrowshdl.mapdata import map_hash
        from arrowshdl.arrowasm import encode
        expected='0aa0bab34deef1d58ec946c02b56f11f80a17bd5801c0200eff3f546fdb75824'
        self.assertEqual(map_hash(compiled.cells),expected)
        self.assertEqual(compiled.cells,read_map(saved))
        board=json.loads((ROOT/'tests/fixtures/examples/minesweeper/observations.json').read_text(encoding='utf-8'))
        # Inputs and observation coordinates come from this compilation's HDL labels and grid.
        for row in range(10):
            for col in range(10):
                name=f'rows[{row}].cols[{col}].tile'
                self.assertEqual(compiled.metadata['instances'][name]['bounds']['min'],board['tiles'][row*10+col]['origin'])
                for state,point in board['cell']['states'].items():
                    probe=compiled.metadata['probes'][name+'.state:'+state]
                    x,y=board['tiles'][row*10+col]['origin']
                    self.assertEqual(probe,[point[0]+x,point[1]+y])
        with tempfile.TemporaryDirectory() as directory:
            temporary=Path(directory)
            (temporary/'minesweeper.save.txt').write_text(encode(compiled.cells)+'\n',encoding='ascii')
            (temporary/'minesweeper.bindings.json').write_text(json.dumps(board),encoding='utf-8')
            with patch.dict('os.environ',{'ARROWSHDL_MINES_BUILD':str(temporary),
                                         'ARROWSHDL_MINES_SOURCE':str(temporary)}):
                from tests.projects.minesweeper import context,snap_verify
                with patch.object(context,'BUILD',temporary),patch.object(context,'SOURCE',temporary),patch.object(snap_verify,'BUILD',temporary):
                    runs=[snap_verify.verify_board(10,seed,first=first,stem='minesweeper')
                          for seed,first in ((123456789,None),(987654321,0))]
                    controls=dict(compiled.cells);point=(149,316)
                    controls[point]=arrowshdl.Cell(22,controls[point].rotation,controls[point].mirrored)
                    observed=[compiled.metadata['probes'][f'rows[{i//10}].cols[{i%10}].tile.state:selected'] for i in range(100)]
                    observed += [compiled.metadata['probes'][f'rows[{i//10}].cols[{i%10}].tile.state:mine'] for i in (10,11,20,21,30,31)]
                    report=context.simulate(controls,dict(ticks=80065,frame_ticks=[1,64,80000],seed=123456789,
                        inputs=[dict(at=list(point),values=[0,1,0])],expect=[],observe=observed))
                    values=[item['values'][-1] for item in report['observations']]
                    self.assertEqual({i for i,v in enumerate(values[:100]) if v},{20})
                    self.assertFalse(any(values[100:]))
        self.report=dict(passed=True,map_hash=expected,save_sha256=save_sha256(saved),size=10,runs=runs,rotated_button=True)
        save_artifact('minesweeper','behavior.report.json',self.report)

    def test_safe_first_flood_count_win_lose_and_reset(self):
        saved=ROOT/'examples/minesweeper/build/minesweeper.save.txt'
        compiled=arrowshdl.build(saved.parent.parent/'project.toml',layout='compact')
        meta=compiled.metadata
        if meta['layout']=='fixed-native-verilog':
            self.check_reference_board(compiled,saved)
            return
        cells=add_fixture(read_map(saved),meta)
        hold=max(1000,2*meta['settle_ticks']);points={}
        for i in range(25):
            for name in ('mine','opened','first_selected'):
                points[f'{i}:{name}']=meta['instances'][f'cell_{i}']['outputs'][name][0]['contact']
            panel=meta['instances'][f'cell_{i}'].get('panel')
            digit=panel['displays']['left'] if panel else meta['components'][f'digit_{i}']
            for bit,e in enumerate(digit['inputs']['segments']):
                points[f'{i}:segment{bit}']=e['contact']
            for bit,pixel in enumerate(panel['displays']['right']['pixels'] if panel else []):
                points[f'{i}:mine_pixel{bit}']=pixel
        for name in ('started','victory','defeat'):
            points[name]=meta['instances']['game']['outputs'][name][0]['contact']
        for name in ('win_message','loss_message'):
            for i,point in enumerate(meta['components'][name]['display']['pixels']):points[f'{name}:{i}']=point
        checks=0;snapshots=[]
        def run(actions,seed):
            inputs=[dict(at=meta['inputs']['new_game'][0]['fixture'],values=[a[0] for a in actions])]
            inputs.extend(dict(at=e['fixture'],values=[(a[1]>>b)&1 for a in actions]) for b,e in enumerate(meta['inputs']['selected']))
            frames=[a[2]*hold for a in actions]
            scenario=dict(ticks=sum(frames),frame_ticks=frames,seed=seed,inputs=inputs,expect=[],observe=list(points.values()))
            report=simulate(cells,scenario,timeout=180,optimize_cycles=False)
            traces={tuple(row['at']):row['values'] for row in report['observations']}
            states=[{name:traces[tuple(point)][t] for name,point in points.items()} for t in range(len(actions))]
            return states,scenario
        def board(state,name):return {i for i in range(25) if state[f'{i}:{name}']}
        def check(state,mines,opened,win,loss):
            nonlocal checks
            self.assertEqual(board(state,'mine'),mines)
            self.assertEqual(board(state,'opened'),opened)
            self.assertEqual(state['victory'],win);self.assertEqual(state['defeat'],loss)
            for i in range(25):
                mask=sum(state[f'{i}:segment{b}']<<b for b in range(7))
                self.assertEqual(mask,SEGMENTS[len(neighbors(i)&mines)] if i in opened else 0,(i,mask))
                for key in points:
                    if key.startswith(f'{i}:mine_pixel'):self.assertEqual(state[key],int(i in mines and loss),key)
            for name,value in (('win_message',win),('loss_message',loss)):
                for key in points:
                    if key.startswith(name+':'):self.assertEqual(state[key],value,key);checks+=1
            checks+=25*9+2
        for seed,first in ((123456789,0),(987654321,12)):
            base=[(1,0,1),(0,0,1),(0,1<<first,4),(0,0,1)]
            states,_=run(base,seed)
            original=board(states[1],'mine')
            mines=original-(neighbors(first)|{first})
            opened=flood(mines,{first})
            self.assertEqual(states[-1]['started'],1)
            self.assertEqual(board(states[-1],'first_selected'),{first})
            win=int(len(opened|mines)==25)
            check(states[-1],mines,opened,win,0)
            snapshots.append(dict(seed=seed,first=first,mines=sorted(mines),opened=sorted(opened)))
            if mines and not win:
                hit=min(mines)
                actions=base+[(0,1<<hit,3),(0,0,1),(0,(1<<25)-1,2),(0,0,1),(1,0,2)]
                lost,scenario=run(actions,seed)
                check(lost[5],mines,opened,0,1)
                check(lost[7],mines,opened,0,1)
                self.assertEqual([lost[-1][k] for k in ('started','victory','defeat')],[0,0,0])
                self.assertFalse(board(lost[-1],'opened'))
                for name in ('win_message','loss_message'):
                    self.assertFalse(any(lost[-1][k] for k in points if k.startswith(name+':')))
                save_artifact('minesweeper','defeat.scenario.json',scenario)
            remaining=set(range(25))-mines-opened
            selection=sum(1<<i for i in remaining)
            actions=base+[(0,selection,4),(0,0,1),(0,sum(1<<i for i in mines),2),(0,0,1)]
            won,scenario=run(actions,seed)
            check(won[5],mines,set(range(25))-mines,1,0)
            check(won[7],mines,set(range(25))-mines,1,0)
            save_artifact('minesweeper','victory.scenario.json',scenario)
        self.report=dict(passed=True,save_sha256=save_sha256(saved),
            checked_samples=checks,seeds=2,safe_first=True,flood=True,seven_segment=True,
            victory=True,defeat=True,late_clicks=True,reset=True,text_displays=['WIN','LOSE'],snapshots=snapshots,
            oracle='independent Python eight-neighbor board and digit masks')
        save_artifact('minesweeper','minesweeper.report.json',self.report)
