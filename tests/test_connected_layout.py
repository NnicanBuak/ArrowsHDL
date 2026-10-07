"""Physical direct gate links, shared pin fanout, and signal provenance."""
from itertools import product
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from compact_layout import Router
from arrow_layout import bounds_of,depth_of,logic_core_metrics
from mapdata import map_hash
from signal_metadata import describe_signals
from simulation import simulate
from test_harness import add_fixture,make_scenario
from packed_layout import arrange_packed
from input_buses import apply_placement


def metadata(router,cells):
    return {'map_hash':map_hash(cells),'inputs':router.inputs,'outputs':router.outputs,'settle_ticks':depth_of(cells)+2}


class ConnectedTests(unittest.TestCase):
    def test_default_port_banks_stay_fixed_while_the_core_grows(self):
        graph={'top':'invert','inputs':{'a':[{'index':0,'net':'a'}]},
               'outputs':{'y':[{'index':0,'net':'port:y'}]},'nodes':[
                   {'id':'inv','op':'NOT','inputs':['a'],'output':'n'},
                   {'id':'port:y','op':'BUF','inputs':['n'],'output':'port:y'}]}
        contacts=[]
        for aspect,gap in product((0.5,2.5,4.0),(0,2)):
            placement,_=arrange_packed(graph,{'core':gap},0,aspect,(100,100),True)
            vertices,positions,_=apply_placement(graph,placement)
            contacts.append([p for v,p in zip(vertices,positions) if v['kind']=='input' or v.get('node',{}).get('output')=='port:y'])
        self.assertTrue(all(ports==contacts[0] for ports in contacts))
        self.assertEqual(contacts[0],[(-3,0),(103,0)])

    def test_adjacent_operators_need_no_intermediate_arrow(self):
        graph={'top':'double_not','inputs':{'a':[{'index':0,'net':'a'}]},'outputs':{'y':[{'index':0,'net':'port:y'}]},'nodes':[
            {'id':'n0','op':'NOT','inputs':['a'],'output':'n0'},
            {'id':'n1','op':'NOT','inputs':['n0'],'output':'n1'},
            {'id':'port:y','op':'BUF','inputs':['n1'],'output':'port:y'}]}
        vertices=[{'kind':'input','net':'a','rotation':1,'fixture':[-4,0]}]+[{'kind':'gate','node':node} for node in graph['nodes']]
        positions=[(-3,0),(0,0),(1,0),(10,0)]
        router=Router(graph,1,1000,(vertices,positions,{}));cells=router.route()
        core=logic_core_metrics(cells,router.gates,router.output_nets)
        self.assertEqual(core['cells'],2)
        self.assertEqual(core['ticks'],2)
        self.assertEqual(router.pins[(1,0)],[(0,0)])
        meta=metadata(router,cells)
        vectors=[{'inputs':{'a':a},'expect':{'y':a}} for a in (0,1,0,1,1,0)]
        report=simulate(add_fixture(cells,meta),make_scenario(meta,vectors,compressed=True))
        self.assertTrue(report['passed'],report['failures'])

    def test_native_pair_shares_three_physical_input_contacts(self):
        graph={'top':'pair','inputs':{name:[{'index':0,'net':name}] for name in ('a','b','c')},
               'outputs':{'sum':[{'index':0,'net':'port:sum'}],'carry':[{'index':0,'net':'port:carry'}]},'nodes':[
                   {'id':'sum','op':'XOR','inputs':['a','b','c'],'output':'sum'},
                   {'id':'carry','op':'MAJ','inputs':['a','b','c'],'output':'carry'},
                   {'id':'port:sum','op':'BUF','inputs':['sum'],'output':'port:sum'},
                   {'id':'port:carry','op':'BUF','inputs':['carry'],'output':'port:carry'}]}
        vertices=[{'kind':'input','net':name,'rotation':1,'fixture':[-5,4*i]} for i,name in enumerate(('a','b','c'))]
        vertices += [{'kind':'gate','node':node,**({'pins':[[0,-1],[0,2],[-1,1]]} if i<2 else {})} for i,node in enumerate(graph['nodes'])]
        positions=[(-4,0),(-4,4),(-4,8),(0,0),(0,1),(12,0),(12,4)]
        router=Router(graph,2,1000,(vertices,positions,{}));cells=router.route()
        self.assertEqual(router.pins[(0,0)],router.pins[(0,1)])
        meta=metadata(router,cells)
        vectors=[{'inputs':dict(zip(('a','b','c'),bits)),'expect':{'sum':sum(bits)%2,'carry':int(sum(bits)>=2)}} for bits in product(range(2),repeat=3)]*2
        report=simulate(add_fixture(cells,meta),make_scenario(meta,vectors,compressed=True))
        self.assertTrue(report['passed'],report['failures'])
        signals=describe_signals(graph,cells,router.owners,router.gates)
        nets={net['id']:net for net in signals['nets']}
        self.assertEqual({v['bus'] for v in nets['sum']['origins']},{'a','b','c'})
        self.assertEqual(nets['sum']['inputs'],['a','b','c'])
        self.assertEqual(sum(len(net['cells']) for net in signals['nets']),len(cells))


if __name__=='__main__':unittest.main()
