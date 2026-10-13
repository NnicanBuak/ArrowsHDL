"""Independent board oracle and signal-driven WIN/LOSE checks on saved cells."""
from pathlib import Path
import tempfile
import unittest

from arrowshdl import build
from arrowshdl.mapdata import read_map,save_sha256
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
    def test_safe_first_flood_count_win_lose_and_reset(self):
        with tempfile.TemporaryDirectory(prefix='arrowshdl-minesweeper-') as directory:
            saved=Path(directory)/'minesweeper.save.txt'
            result=build(ROOT/'examples/minesweeper/project.toml',out=saved)
            self.assertEqual(read_map(saved),result.cells)
            self.report=self.verify(result.cells,result.metadata,save_sha256(saved))

    def verify(self,production_cells,meta,digest):
        cells=add_fixture(production_cells,meta)
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
                lost,_=run(actions,seed)
                check(lost[5],mines,opened,0,1)
                check(lost[7],mines,opened,0,1)
                self.assertEqual([lost[-1][k] for k in ('started','victory','defeat')],[0,0,0])
                self.assertFalse(board(lost[-1],'opened'))
                for name in ('win_message','loss_message'):
                    self.assertFalse(any(lost[-1][k] for k in points if k.startswith(name+':')))
            remaining=set(range(25))-mines-opened
            selection=sum(1<<i for i in remaining)
            actions=base+[(0,selection,4),(0,0,1),(0,sum(1<<i for i in mines),2),(0,0,1)]
            won,_=run(actions,seed)
            check(won[5],mines,set(range(25))-mines,1,0)
            check(won[7],mines,set(range(25))-mines,1,0)
        report=dict(passed=True,save_sha256=digest,
            checked_samples=checks,seeds=2,safe_first=True,flood=True,seven_segment=True,
            victory=True,defeat=True,late_clicks=True,reset=True,text_displays=['WIN','LOSE'],snapshots=snapshots,
            oracle='independent Python eight-neighbor board and digit masks')
        return report
