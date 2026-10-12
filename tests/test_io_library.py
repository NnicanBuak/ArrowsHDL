"""Packaged I/O components work without any example build artifacts."""
from pathlib import Path
import shutil
import tempfile
import unittest

from arrowshdl.artifacts import read_metadata
from arrowshdl.components import load_component
from arrowshdl.manifest import component_file, load_project
from arrowshdl.mapdata import read_map
from arrowshdl.simulation import simulate
from arrowshdl.test_harness import add_fixture


class IoLibraryTests(unittest.TestCase):
    def test_example_inputs_do_not_depend_on_build_directory(self):
        examples=Path(__file__).resolve().parents[1]/'examples'
        for name in ('minesweeper','pulse_sequencer'):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                for source in (examples/name).iterdir():
                    if source.suffix in ('.toml','.v','.sv'):
                        shutil.copy2(source,root/source.name)
                self.assertFalse((root/'build').exists())
                project=load_project(root/'project.toml')
                for row in project.components:
                    if row.get('kind')=='text':
                        from arrowshdl.text_display import compile_display
                        self.assertTrue(compile_display(root,row)[0])
                        continue
                    path=component_file(root,row['file'])
                    self.assertTrue(load_component(path)[0])

    def test_all_seven_segment_patterns_on_physical_display(self):
        path=component_file(Path.cwd(),'library:seven_segment')
        meta=read_metadata(path)
        cells=add_fixture(read_map(path),meta)
        hold=meta['settle_ticks']
        scenario=dict(ticks=128*hold,hold_ticks=hold,expect=[],
            inputs=[dict(at=e['fixture'],values=[(value>>e['index'])&1 for value in range(128)])
                    for e in meta['inputs']['segments']])
        scenario['assert']=[dict(at=point,values=[(value>>bit)&1 for value in range(128)])
            for bit,points in enumerate(meta['segment_pixels']) for point in points]
        result=simulate(cells,scenario)
        self.assertTrue(result['passed'],result['failures'])
        self.assertEqual(result['checked_samples'],4736)

    def test_text_preserves_font_raster_colors_and_clears_every_pixel(self):
        from arrowshdl.text_display import compile_display,font_file
        from arrowshdl.lettering import text_pixels
        from arrowshdl.test_harness import make_scenario
        from arrowshdl.arrow_layout import depth_of
        for text in ('WIN','LOSE'):
            for size in (1,2):
                cells,meta=compile_display(Path.cwd(),dict(name='message',text=text,size=size))
                pixels,_=text_pixels(font_file(Path.cwd(),'library:arrow4'),text,size)
                self.assertEqual(set(map(tuple,meta['display']['pixels'])),pixels)
                self.assertTrue(all(cells[p].type in (1,6,7,8) for p in pixels))
                self.assertTrue(all(cell.type in (10,11,12,13,14) for p,cell in cells.items() if p not in pixels))
                self.assertLess(depth_of(cells),meta['settle_ticks'])
                scenario=make_scenario(meta,[dict(inputs={'signal':v},expect={}) for v in (0,1,0,1)],compressed=True)
                scenario['assert']=[dict(at=list(p),values=[0,1,0,1]) for p in pixels]
                result=simulate(add_fixture(cells,meta),scenario,optimize_cycles=False)
                self.assertTrue(result['passed'],result['failures'])

    def test_controller_drives_two_independent_text_displays(self):
        import arrowshdl
        from arrowshdl.test_harness import make_scenario
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'controller.v').write_text('module controller(input win,loss,output victory,defeat); assign victory=win; assign defeat=loss; endmodule')
            project=root/'project.toml'
            project.write_text('''version=2
top="text_demo"
sources=["controller.v"]
[[modules]]
name="game"
hdl="controller"
[[components]]
name="win_display"
kind="text"
text="WIN"
[[components]]
name="loss_display"
kind="text"
text="LOSE"
[[inputs]]
name="win"
[[inputs]]
name="loss"
[[connections]]
from="win"
to="game.win"
[[connections]]
from="loss"
to="game.loss"
[[connections]]
from="game.victory"
to="win_display.signal"
[[connections]]
from="game.defeat"
to="loss_display.signal"
''',encoding='utf-8')
            result=arrowshdl.build(project,out=root/'result.json')
            fixture=add_fixture(result.cells,result.metadata)
            sequence=[(0,0),(1,0),(0,1),(1,1),(0,0)]
            scenario=make_scenario(result.metadata,[dict(inputs={'win':w,'loss':l},expect={}) for w,l in sequence],compressed=True)
            scenario['assert']=[dict(at=p,values=[row[index] for row in sequence])
                for index,name in enumerate(('win_display','loss_display'))
                for p in result.metadata['components'][name]['display']['pixels']]
            report=simulate(fixture,scenario,optimize_cycles=False)
            self.assertTrue(report['passed'],report['failures'])
