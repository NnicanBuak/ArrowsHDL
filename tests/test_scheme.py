"""The public scheme contract, default I/O, reusable views and test substitution."""
import json
from pathlib import Path
import tempfile
import unittest

from arrowshdl.arrowasm import Cell,MapError
from arrowshdl.manifest import load_project
from arrowshdl.mapdata import write_map,read_map
from arrowshdl.scheme import build_scheme
from arrowshdl.test_harness import add_fixture,make_scenario
from arrowshdl.simulation import simulate


class SchemeTests(unittest.TestCase):
    def prepare(self,folder,extra=''):
        (folder/'logic.v').write_text('module logic_unit(input a,b, output y); assign y=a^b; endmodule',encoding='utf-8')
        path=folder/'scheme.toml'
        path.write_text('version=1\nsources=["logic.v"]\ntop="logic_unit"\n'+extra,encoding='utf-8')
        return path

    def test_buttons_displays_and_fixture_substitution(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            path=self.prepare(folder)
            cells,meta=build_scheme(path,folder/'out')
            self.assertEqual(sum(c.type==24 for c in cells.values()),2)
            self.assertEqual(len(meta['io_devices']),3)
            original=dict(cells)
            fixture=add_fixture(cells,meta)
            self.assertEqual(cells,original)
            self.assertEqual(sum(c.type==22 for c in fixture.values()),2)
            self.assertEqual(sum(c.type==23 for c in fixture.values()),1)
            vectors=[dict(inputs={'a':a,'b':b},expect={'y':a^b}) for a,b in ((0,0),(0,1),(1,1),(1,0),(0,0))]
            report=simulate(fixture,make_scenario(meta,vectors))
            self.assertTrue(report['passed'],report['failures'])
            tested,test_meta=build_scheme(path,folder/'test',testing=True)
            self.assertEqual(sum(c.type==22 for c in tested.values()),2)
            display=next(d for d in meta['io_devices'] if d['direction']=='outputs')
            self.assertEqual(tested[tuple(display['at'])].type,23)

    def test_explicit_empty_lists_disable_default_widgets(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            path=self.prepare(folder,'inputs=[]\noutputs=[]\n')
            cells,meta=build_scheme(path,folder/'out')
            self.assertFalse(meta['io_devices'])
            self.assertFalse(any(c.type in (22,23,24) for c in cells.values()))

    def test_unknown_versions_policies_and_ports_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            path=self.prepare(folder)
            for text in ('version=2\nsources=["logic.v"]\ntop="logic_unit"',
                         'version=true\nsources=["logic.v"]\ntop="logic_unit"',
                         'version=1\nsources=["logic.v"]\ntop="logic_unit"\n[placement]\nmode="compact"'):
                path.write_text(text,encoding='utf-8')
                with self.assertRaises(MapError):load_project(path)
            path=self.prepare(folder,'[[inputs]]\nname="wrong"\nto="missing"\n')
            with self.assertRaises(MapError):build_scheme(path,folder/'out')

    def test_prepared_display_connected_to_computations(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            # An already prepared display: one input, two visible cells.
            write_map(folder,'display',{(0,0):Cell(1,1),(1,0):Cell(1,1)})
            (folder/'display.toml').write_text('version=1\nmap="display.save.txt"\n'
                '[[ports.inputs.signal]]\nindex=0\ncontact=[0,0]\nfixture=[-1,0]\nrotation=1\n',encoding='utf-8')
            path=self.prepare(folder,'outputs=[]\n[[modules]]\nname="calc"\nhdl="logic_unit"\nat=[0,0]\n'
                '[[components]]\nname="screen"\nfile="display.toml"\nat=[25,0]\n'
                '[[connections]]\nfrom="calc.y"\nto="screen.signal"\n')
            cells,meta=build_scheme(path,folder/'out')
            self.assertEqual(cells[(25,0)],Cell(1,1))
            self.assertEqual(cells[(26,0)],Cell(1,1))
            tested,test_meta=build_scheme(path,folder/'test',testing=True)
            self.assertEqual(tested[(25,0)],cells[(25,0)])
            scenario=dict(ticks=160,hold_ticks=40,inputs=[dict(at=e['at'],values=[0,1,0,1] if e['port']=='calc.a' else [0,0,0,0]) for e in test_meta['io_devices']],
                          expect=[],observe=[[26,0]])
            scenario['expect']=[dict(at=test_meta['outputs']['calc.y'][0]['fixture'],values=[0,1,0,1])]
            report=simulate(tested,scenario,optimize_cycles=False)
            self.assertTrue(report['passed'],report['failures'])
            self.assertEqual(report['observations'][0]['values'],[0,1,0,1])


if __name__=='__main__':unittest.main()
