"""Opaque saves, interface errors, physical controls and external fonts."""
import json
from pathlib import Path
import tempfile
import unittest

from arrowshdl.arrowasm import Cell,MapError
from arrowshdl.components import load_component
from arrowshdl.lettering import text_pixels,attach_labels
from arrowshdl.mapdata import write_map,map_hash
from arrowshdl.presentation import attach_io,button_cells
from arrowshdl.scheme import build_scheme
from arrowshdl.simulation import simulate


class ComponentTests(unittest.TestCase):
    def component(self,folder,name,cells,ports):
        write_map(folder,name,cells)
        path=folder/(name+'.toml')
        path.write_text(f'version=1\nmap="{name}.save.txt"\n'+ports,encoding='utf-8')
        return path

    def test_legacy_component_graph_is_rejected_and_component_geometry_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            original={(0,0):Cell(1,1),(0,2):Cell(25,0),(2,2):Cell(25,0)}
            source=self.component(root,'source',original,'[[ports.inputs.key]]\nindex=0\ncontact=[0,0]\nfixture=[-1,0]\nrotation=1\n'
                '[[ports.outputs.bit]]\nindex=0\ncontact=[0,0]\nfixture=[1,0]\nrotation=1\n')
            loaded,meta=load_component(source,(5,7))
            self.assertEqual({(x-5,y-7):cell for (x,y),cell in loaded.items()},original)
            self.assertEqual(meta['source_map_hash'],map_hash(original))
            scheme=root/'scheme.toml'
            scheme.write_text('version=1\ntop="linked"\n',encoding='utf-8')
            with self.assertRaisesRegex(MapError,'unsupported'):
                build_scheme(scheme,root/'out')

    def test_rotation_and_interface_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            path=self.component(root,'key',{(0,0):Cell(1,1,True)},
                '[interface]\nkind="keyboard"\nencoding="cp1251"\nprotocol="data plus strobe"\n'
                '[[ports.outputs.data]]\nindex=0\ncontact=[0,0]\nfixture=[1,0]\nrotation=1\n')
            cells,meta=load_component(path,[10,20],1)
            self.assertEqual(cells,{(10,20):Cell(1,2,True)})
            self.assertEqual(meta['outputs']['data'][0]['fixture'],[10,21])
            self.assertEqual(meta['interface']['encoding'],'cp1251')
            path.write_text(path.read_text().replace('index=0','index=1'))
            with self.assertRaises(MapError):load_component(path)

    def test_each_button_square_reaches_input(self):
        original={(0,0):Cell(1,1)}
        manifest=dict(map_hash=map_hash(original),inputs={'key':[dict(index=0,contact=[0,0],fixture=[-1,0],rotation=1)]},outputs={})
        cells,meta=attach_io(original,manifest,[dict(name='key',to='key',size=[3,4])],[])
        buttons=button_cells((-1,0),1,[3,4])
        self.assertEqual(len(buttons),12)
        for p,c in buttons.items():
            tested=dict(cells);tested[p]=Cell(22,c.rotation)
            report=simulate(tested,dict(ticks=40,hold_ticks=20,inputs=[dict(at=list(p),values=[1,0])],expect=[],observe=[[0,0]]),optimize_cycles=False)
            self.assertEqual(report['observations'][0]['values'],[1,0],p)
        with self.assertRaises(MapError):
            attach_io(original,manifest,[dict(name='a',to='key'),dict(name='b',to='key[0]')],[])

    def test_label_scaling_is_integral_passive_and_bound_to_io(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);font=root/'font.json'
            font.write_text(json.dumps(dict(version=1,height=2,glyphs={'A':['.#','##'],'Я':['##','.#']})))
            pixels,bounds=text_pixels(font,'AЯ',1)
            large,larger=text_pixels(font,'AЯ',3)
            self.assertEqual(larger,tuple(v*3 for v in bounds));self.assertEqual(len(large),len(pixels)*9)
            for bad in (0,1.5,True):
                with self.assertRaises(MapError):text_pixels(font,'A',bad)
            with self.assertRaises(MapError):text_pixels(font,'Б')
            original={(0,0):Cell(1,1)}
            meta=dict(inputs={'key':[dict(index=0,fixture=[-1,0],contact=[0,0])]},outputs={})
            cells,meta=attach_labels(original,meta,[dict(name='label',io='key',font='font.json',text='AЯ',size=2,at=[-20,5])],root)
            self.assertEqual(cells[(0,0)],original[(0,0)])
            self.assertTrue(all(c.type==25 for p,c in cells.items() if p!=(0,0)))


if __name__=='__main__':unittest.main()
