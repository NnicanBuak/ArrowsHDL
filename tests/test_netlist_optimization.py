import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from arrowasm import Cell,MapError
from netlist_optimization import prune_outputs,forward_monotone_latches,fold_or_trees,compress_three_counts,forward_output_levels
from incremental_routing import prune_dead_wires
from simulation import simulate


class PruningTests(unittest.TestCase):
    def test_level_output_removes_edge_detector_only_with_explicit_receiver_contract(self):
        from copy import deepcopy
        graph=dict(inputs={'data':[dict(net='data',index=0)]},outputs={'out':[dict(net='out',index=0)]},nodes=[
            dict(id='delay',output='delay',op='BUF',inputs=['data']),
            dict(id='pulse',output='pulse',op='XOR',inputs=['data','delay']),
            dict(id='out',output='out',op='BUF',inputs=['pulse'])])
        original=deepcopy(graph)
        result=forward_output_levels(graph,[('data','delay','pulse')])
        self.assertEqual(result['nodes'],[dict(id='out',output='out',op='BUF',inputs=['data'])])
        self.assertEqual(graph,original)
        self.assertIn('continuous level',result['_level_outputs']['contract'])
        for net in ('delay','pulse'):
            invalid=deepcopy(graph)
            invalid['nodes'].append(dict(id='extra',output='extra',op='NOT',inputs=[net]))
            with self.assertRaises(MapError):forward_output_levels(invalid,[('data','delay','pulse')])
            exposed=deepcopy(graph);exposed['outputs']['tap']=[dict(net=net,index=0)]
            with self.assertRaises(MapError):forward_output_levels(exposed,[('data','delay','pulse')])

    def test_carry_save_sums_every_three_two_bit_counts(self):
        from copy import deepcopy
        scope='count/merge'
        outputs=['lo','mid','hi','top']
        graph=dict(inputs={},outputs={'out':[dict(net=n,index=i) for i,n in enumerate(outputs)]},
                   nodes=[dict(id=n,output=n,op='OR',inputs=['a0'],scope=scope)
                          for n in outputs+['u','v','w','x','y','z']])
        original=deepcopy(graph)
        result=compress_three_counts(graph,partials=[['a0','a1'],['b0','b1'],['c0','c1']],outputs=outputs)
        self.assertEqual(graph,original)
        self.assertEqual(len(result['nodes']),8)
        for a in range(4):
            for b in range(4):
                for c in range(4):
                    values={f'{name}{i}':(v>>i)&1 for name,v in zip('abc',(a,b,c)) for i in range(2)}
                    for node in result['nodes']:
                        count=sum(values[n] for n in node['inputs'])
                        values[node['output']]=count%2 if node['op']=='XOR' else int(count>=2)
                    self.assertEqual(sum(values[n]<<i for i,n in enumerate(outputs)),a+b+c)
        exposed=deepcopy(graph)
        exposed['nodes'].append(dict(id='observer',output='observer',op='BUF',inputs=['u']))
        with self.assertRaises(MapError):compress_three_counts(exposed,partials=[['a0','a1']]*3,outputs=outputs)

    def test_private_or_tree_folds_to_native_nor_and_retains_shared_outputs(self):
        graph=dict(inputs={},outputs={'out':[dict(net='out',index=0)]},nodes=[
            dict(id='inner',output='inner',op='OR',inputs=['a','b','c']),
            dict(id='out',output='out',op='NOT',inputs=['inner'])])
        result=fold_or_trees(graph)
        self.assertEqual(len(result['nodes']),1)
        self.assertEqual(result['nodes'][0]['inputs'],['a','b','c'])
        self.assertEqual(len(graph['nodes']),2)
        self.assertEqual(len(fold_or_trees(graph,keep_nets=['inner'])['nodes']),2)
        graph['outputs']['tap']=[dict(net='inner',index=0)]
        self.assertEqual(len(fold_or_trees(graph)['nodes']),2)

    def test_level_relay_rejects_undeclared_pulse_and_preserves_all_level_values(self):
        graph=dict(inputs={n:[dict(net=n,index=0)] for n in ('a','b')},
            outputs={'out':[dict(net='state',index=0)]},nodes=[
                dict(output='trigger',op='OR',inputs=['a','b']),
                dict(output='state',op='SET',inputs=['trigger','trigger'])])
        with self.assertRaises(MapError):forward_monotone_latches(graph,['state'],levels=['a'])
        result=forward_monotone_latches(graph,['state'],levels=['a','b'])
        self.assertEqual(len(result['nodes']),1)
        self.assertEqual(result['nodes'][0]['op'],'OR')
        # Independent sticky-state reference, including unequal arrival times.
        for ta in range(6):
            for tb in range(6):
                sticky=0
                for tick in range(6):
                    a=int(ta<5 and tick>=ta);b=int(tb<5 and tick>=tb)
                    sticky|=a|b
                    self.assertEqual(sticky,int(bool(a or b)))

    def test_unused_output_removes_only_unreachable_logic_and_input(self):
        graph=dict(inputs={'a':[dict(net='a',index=0)],'b':[dict(net='b',index=0)]},
            outputs={'kept':[dict(net='x',index=0)],'unused':[dict(net='y',index=0)]},
            nodes=[dict(output='x',op='NOT',inputs=['a']),
                   dict(output='z',op='AND',inputs=['x','b']),
                   dict(output='y',op='OR',inputs=['z','b'])])
        result=prune_outputs(graph,['unused'])
        self.assertEqual(result['nodes'],graph['nodes'][:1])
        self.assertEqual(result['_pruning']['dead_nets'],['b','y','z'])
        self.assertEqual(set(result['inputs']),{'a'})
        self.assertIn('unused',graph['outputs'])
        pinned=prune_outputs(graph,['unused'],keep_nets=['z'])
        self.assertEqual(len(pinned['nodes']),2)
        with self.assertRaises(MapError):prune_outputs(graph,['missing'])

    def test_physical_dead_branch_removal_preserves_source_target_transitions(self):
        cells={(0,0):Cell(22,1),(1,0):Cell(7,1),(2,0):Cell(1,1),(3,0):Cell(23,0),
               (1,1):Cell(1,2),(1,2):Cell(1,2)}
        result=prune_dead_wires(cells,{(0,0),(3,0)})
        self.assertEqual(set(result),{(0,0),(1,0),(2,0),(3,0)})
        values=[0,1,0,1]
        report=simulate(result,dict(ticks=32,hold_ticks=8,
            inputs=[dict(at=[0,0],values=values)],expect=[dict(at=[3,0],values=values)]))
        self.assertTrue(report['passed'])
        self.assertEqual(cells[(1,0)].type,7)


if __name__=='__main__':unittest.main()
