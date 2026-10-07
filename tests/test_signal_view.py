"""Net boundaries, independent input ancestry, and exact save-based views."""
from copy import deepcopy
import base64
from io import BytesIO
from itertools import product
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from arrowasm import Cell,MapError
from arrow_layout import bounds_of,depth_of
from compact_layout import Router,router_manifest
from mapdata import map_hash
from signal_metadata import describe_signals
from signal_view import export_views,view_data,render_poster
from simulation import simulate
from technology_mapping import merge_duplicate_logic
from test_harness import add_fixture,make_scenario


class SignalViewTests(unittest.TestCase):
    def test_each_input_bit_has_its_own_colour_and_sprites_keep_original_colours(self):
        graph={'top':'parity','inputs':{'a':[{'index':i,'net':f'a{i}'} for i in range(2)],'b':[{'index':0,'net':'b0'}]},
               'outputs':{'y':[{'index':0,'net':'port:y'}]},'nodes':[
                   {'id':'xor','op':'XOR','inputs':['a0','a1'],'output':'n'},
                   {'id':'port:y','op':'BUF','inputs':['n'],'output':'port:y'}]}
        vertices=[{'kind':'input','net':name,'fixture':[-4,4*i],'rotation':1} for i,name in enumerate(('a0','a1','b0'))]
        vertices += [{'kind':'gate','node':n} for n in graph['nodes']]
        router=Router(graph,1,100,(vertices,[(-3,0),(-3,4),(-3,8),(2,2),(12,2)],{}));cells=router.route()
        manifest=router_manifest(graph,router,cells,'test-colours')
        original=deepcopy(manifest);data=view_data(cells,manifest)
        self.assertEqual(manifest,original)
        self.assertEqual([s['label'] for s in data['sources']],['a[0]','a[1]','b[0]'])
        self.assertEqual(len({s['color'] for s in data['sources']}),3)
        net=next(n for n in data['nets'] if n['id']=='n')
        self.assertEqual(net['origins'],[{'bus':'a','bit':0},{'bus':'a','bit':1}])
        for kind,uri in data['sprites'].items():
            sprite=Image.open(BytesIO(base64.b64decode(uri.split(',')[1]))).convert('RGBA')
            original=Image.open(ROOT/f'assets/sprites/arrow{kind}.png').convert('RGBA')
            self.assertEqual(sprite.tobytes(),original.tobytes())
        self.assertEqual(len(data['markers']),sum(len(entries) for ports in (manifest['inputs'],manifest['outputs']) for entries in ports.values()))

    def test_duplicate_inversions_share_logic_but_retain_output_contacts(self):
        graph={'top':'share','inputs':{'a':[{'index':0,'net':'a'}]},
               'outputs':{name:[{'index':0,'net':'port:'+name}] for name in ('x','y')},
               'nodes':[{'id':'inv0','op':'NOT','inputs':['a'],'output':'n0'},
                        {'id':'inv1','op':'NOT','inputs':['a'],'output':'n1'},
                        {'id':'terminal_x','op':'BUF','inputs':['n0'],'output':'port:x'},
                        {'id':'terminal_y','op':'BUF','inputs':['n1'],'output':'port:y'}],
               'wire_names':{'alias':[{'index':0,'net':'n1'}]}}
        original=deepcopy(graph);mapped,rewrites=merge_duplicate_logic(graph)
        self.assertEqual(graph,original)
        self.assertEqual(len(rewrites),1)
        self.assertEqual(len(mapped['nodes']),3)
        self.assertEqual([n['inputs'] for n in mapped['nodes'][-2:]],[['n0'],['n0']])
        self.assertEqual(mapped['wire_names']['alias'][0]['net'],'n0')
        self.assertEqual(mapped['outputs'],graph['outputs'])

    def test_red_splitter_has_three_outputs_and_one_shared_source(self):
        graph={'top':'fanout','inputs':{'a':[{'index':0,'net':'a'}]},
               'outputs':{name:[{'index':0,'net':'port:'+name}] for name in ('x','y','z')},
               'nodes':[{'id':'port:'+name,'op':'BUF','inputs':['a'],'output':'port:'+name} for name in ('x','y','z')]}
        vertices=[{'kind':'input','net':'a','fixture':[0,2],'rotation':0}]
        vertices += [{'kind':'gate','node':node,'pins':[[0,1]],'rotation':rot} for node,rot in zip(graph['nodes'],(1,3,0))]
        positions=[(0,1),(1,1),(-1,1),(0,0)]
        router=Router(graph,1,100,(vertices,positions,{}));cells=router.route()
        self.assertEqual(cells[(0,1)].type,8)
        self.assertEqual(len(router.outs[(0,1)]),3)
        manifest=router_manifest(graph,router,cells,'test-shared-contact')
        self.assertEqual(manifest['shared_input_contacts'],1)
        vectors=[{'inputs':{'a':a},'expect':dict.fromkeys(('x','y','z'),a)} for a in (0,1,0,1,1,0)]
        report=simulate(add_fixture(cells,manifest),make_scenario(manifest,vectors,compressed=True))
        self.assertTrue(report['passed'],report['failures'])
        with tempfile.TemporaryDirectory() as folder:
            export_views(cells,manifest,Path(folder),'fanout')
            self.assertTrue((Path(folder)/'fanout.viewer.html').exists())

    def test_net_colour_changes_at_operator_but_input_dependency_survives(self):
        graph={'top':'invert','inputs':{'a':[{'index':0,'net':'a'}]},'outputs':{'y':[{'index':0,'net':'port:y'}]},
               'nodes':[{'id':'inv','op':'NOT','inputs':['a'],'output':'n'},
                        {'id':'port:y','op':'BUF','inputs':['n'],'output':'port:y'}]}
        vertices=[{'kind':'input','net':'a','fixture':[-4,0],'rotation':1}]+[{'kind':'gate','node':n} for n in graph['nodes']]
        router=Router(graph,1,100,(vertices,[(-3,0),(1,0),(7,0)],{}));cells=router.route()
        manifest=router_manifest(graph,router,cells,'test-net-boundary')
        data=view_data(cells,manifest);nets={n['id']:n for n in data['nets']}
        self.assertNotEqual(nets['a']['color'],nets['n']['color'])
        self.assertEqual(nets['n']['origins'],[{'bus':'a','bit':0}])
        self.assertEqual(nets['n']['inputs'],['a'])
        self.assertIn([[0,0],[1,0]],nets['a']['edges'])
        self.assertEqual(len(data['cells']),len(cells))
        self.assertEqual(nets['n']['driver']['at'],[1,0])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'routing.png'
            render_poster(cells,manifest,path,'routing',whole=True)
            image=Image.open(path).convert('RGB')
            left,top=data['bounds']['min']
            def border(at):
                return image.getpixel((24+(at[0]-left+2)*34+2,56+(at[1]-top+2)*34+2))
            self.assertEqual(border((1,0)),(255,255,255))
            self.assertNotEqual(border((7,0)),(255,255,255))
        with self.assertRaises(MapError):view_data({**cells,(20,20):Cell(1,1)},manifest)

    def test_constant_only_view_uses_board_bounds_when_core_is_empty(self):
        cells={(0,0):Cell(1,1)}
        graph={'top':'constant','inputs':{},'outputs':{},'nodes':[]}
        signals=describe_signals(graph,cells,{(0,0):'const0'}, {})
        manifest={'top':'constant','map_hash':map_hash(cells),'inputs':{},'outputs':{},'bounds':bounds_of(cells),
                  'signals':signals,'logic_core':{'cells':0,'ticks':0,'bounds':{'min':None,'max':None,'width':0,'height':0}}}
        with tempfile.TemporaryDirectory() as folder:
            export_views(cells,manifest,Path(folder),'constant')
            text=(Path(folder)/'constant.viewer.html').read_text(encoding='utf-8')
            self.assertNotIn('__MAP_DATA__',text)
            self.assertTrue((Path(folder)/'constant.signals.preview.png').is_file())


if __name__=='__main__':unittest.main()
