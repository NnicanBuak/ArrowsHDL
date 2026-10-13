"""The public scheme contract, default I/O, reusable views and test substitution."""
import json
from pathlib import Path
import tempfile
import unittest

from arrowshdl.arrowasm import Cell,MapError
from arrowshdl.manifest import load_project
from arrowshdl.mapdata import map_hash,write_map,read_map
from arrowshdl.scheme import build_scheme
from arrowshdl.test_harness import add_fixture,make_scenario
from arrowshdl.simulation import simulate


class SchemeTests(unittest.TestCase):
    def prepare(self,folder,design=''):
        (folder/'logic.v').write_text('module logic_unit(input a,b, output y); assign y=a^b; endmodule',encoding='utf-8')
        path=folder/'scheme.toml'
        path.write_text('version=3\nsources=["logic.v"]\ntop="logic_unit"\ndesign="design.toml"\n',encoding='utf-8')
        (folder/'design.toml').write_text('version=1\n'+design,encoding='utf-8')
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
            path=self.prepare(folder,
                '[[ports]]\npath="a"\nhidden=true\n'
                '[[ports]]\npath="b"\nhidden=true\n'
                '[[ports]]\npath="y"\nhidden=true\n')
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
            path=self.prepare(folder,'[[ports]]\npath="missing"\n')
            with self.assertRaises(MapError):build_scheme(path,folder/'out')

    def test_prepared_display_connected_to_computations(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            # An already prepared display: one input, two visible cells.
            write_map(folder,'display',{(0,0):Cell(1,1),(1,0):Cell(1,1)})
            (folder/'display.toml').write_text('version=1\nmap="display.save.txt"\n'
                '[[ports.inputs.signal]]\nindex=0\ncontact=[0,0]\nfixture=[-1,0]\nrotation=1\n',encoding='utf-8')
            path=self.prepare(folder,
                '[[components]]\nname="screen"\nfile="display.toml"\nbind="y"\n')
            cells,meta=build_scheme(path,folder/'out')
            source_map={(0,0):Cell(1,1),(1,0):Cell(1,1)}
            self.assertEqual(meta['components']['screen']['source_map_hash'],map_hash(source_map))
            tested,test_meta=build_scheme(path,folder/'test',testing=True)
            vectors=[dict(inputs={'a':a,'b':b},expect={'y':a^b})
                     for a,b in ((0,0),(0,1),(1,1),(1,0))]
            report=simulate(tested,make_scenario(test_meta,vectors))
            self.assertTrue(report['passed'],report['failures'])
            self.assertIn('screen',test_meta['components'])


if __name__=='__main__':unittest.main()
