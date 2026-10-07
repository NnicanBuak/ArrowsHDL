"""Physical equivalence, two-row geometry, and safe structural recognition."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from arrow_layout import place
from arrowasm import Cell, MapError
from native_mux_layout import recognize_mux, mux_candidate, tree_candidate
from technology_mapping import merge_duplicate_logic
from test_harness import run_vectors
from verilog_compile import compile_file
from verilog_frontend import synthesize


class NativeMuxTests(unittest.TestCase):
    def test_exhaustive_saved_maps_and_total_size(self):
        for count, old_cells in ((2, 20), (4, 63), (8, 286)):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as d:
                folder = Path(d)
                source = ROOT / f'examples/hdl/multiplexer/mux{count}/mux{count}.v'
                graph, _ = synthesize(source, f'mux{count}')
                before = deepcopy(graph)
                cells, meta = place(graph, input_buses=['data,sel'], input_bus_gap=0)
                self.assertEqual(graph, before)
                self.assertEqual(meta['layout'], 'compact-native-mux-tree-v2')
                self.assertTrue(meta['compact_block'])
                self.assertTrue(meta['optimization']['io_in_objective'])
                self.assertTrue(meta['optimization']['fixed_input_bus'])
                self.assert_input_bus(meta)
                self.assert_exterior_ports(cells,meta)
                candidates=meta['optimization']['candidates']
                best=min(candidates,key=lambda c:(c['core']['cells'],c['core']['bounds']['area'],c['cells'],c['full_bounds']['area'],c['ticks']))
                self.assertEqual(len(cells),best['cells'])
                self.assertLess(len(cells), old_cells)
                self.assertLess(meta['logic_core']['bounds']['width'], count * 6)
                self.assertEqual((cells, meta), place(graph, input_buses=['data,sel'], input_bus_gap=0))
                vectors = [{'inputs': {'data': data, 'sel': sel}, 'expect': {'y': (data >> sel) & 1}}
                           for data in range(1 << count) for sel in range(count)]
                vectors += list(reversed(vectors))
                _, report = run_vectors(cells, meta, vectors, folder, 'mux', compressed=True)
                self.assertTrue(report['passed'], report['failures'])
                self.assertEqual(report['checked_samples'], 2 * count * (1 << count))
                # A missing logic element must fail physical equivalence.
                broken = dict(cells)
                p = next(tuple(g['at']) for g in meta['gate_labels'] if g['op'] == 'AND')
                broken[p] = Cell(1, broken[p].rotation)
                from mapdata import map_hash
                broken_meta = dict(meta, map_hash=map_hash(broken))
                _, bad = run_vectors(broken, broken_meta, vectors, folder / 'broken', 'mux', compressed=True)
                self.assertFalse(bad['passed'])

    def test_output_candidates_keep_core_and_remain_exterior(self):
        source=ROOT/'examples/hdl/multiplexer/mux4/mux4.v'
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            cells,meta=compile_file(source,'mux4',folder,input_buses=['data,sel'],input_bus_gap=0)
            search=meta['output_search']
            self.assertTrue(search['core_frozen'])
            self.assertTrue(search['core_connections_verified'])
            self.assertGreater(len({c['side'] for c in search['candidates']}),1)
            core=meta['logic_core']
            for candidate in search['candidates']:
                self.assertEqual(candidate['core']['cells'],core['cells'])
                self.assertEqual(candidate['core']['bounds'],core['bounds'])
                self.assertEqual(candidate['core']['ticks'],core['ticks'])
            best=min(search['candidates'],key=lambda c:(c['bounds']['area'],c['cells'],c['ticks']))
            self.assertEqual(search['selected']['bounds'],best['bounds'])
            from output_layout import exterior_bounds
            self.assertEqual(search['selected']['bounds'],exterior_bounds(cells,meta['inputs'],meta['outputs']))
            self.assert_exterior_ports(cells,meta)
            vectors=[{'inputs':{'data':v,'sel':s},'expect':{'y':(v>>s)&1}} for v in range(16) for s in range(4)]
            _,report=run_vectors(cells,meta,vectors,folder,'mux4',compressed=True)
            self.assertTrue(report['passed'],report['failures'])

    def test_initial_output_anchor_does_not_change_core_or_result(self):
        from output_layout import route_with_outputs
        from arrow_layout import depth_of
        from mapdata import map_hash
        gate={'id':'negate','op':'NOT','inputs':['a'],'output':'inverted'}
        terminal={'id':'port:y','op':'BUF','inputs':['inverted'],'output':'port:y'}
        graph={'top':'anchor','inputs':{'a':[{'index':0,'net':'a'}]},
               'outputs':{'y':[{'index':0,'net':'port:y'}]},'nodes':[gate,terminal]}
        results=[]
        with tempfile.TemporaryDirectory() as d:
            for index,point in enumerate(((2,0),(100,80))):
                vertices=[{'kind':'input','net':'a','fixture':(-1,0),'rotation':1},
                          {'kind':'gate','node':gate,'rotation':1,'pins':[(0,0)]},
                          {'kind':'gate','node':terminal,'rotation':1,'pins':[(point[0]-1,point[1])]}]
                cells,router=route_with_outputs(graph,(vertices,[(0,0),(1,0),point],{}),100000)
                results.append(cells)
                meta={'map_hash':map_hash(cells),'inputs':router.inputs,'outputs':router.outputs,
                      'settle_ticks':depth_of(cells)+2}
                vectors=[{'inputs':{'a':a},'expect':{'y':1-a}} for a in (0,1,0,1)]
                _,report=run_vectors(cells,meta,vectors,Path(d)/str(index),'anchor',compressed=True)
                self.assertTrue(report['passed'],report['failures'])
            self.assertEqual(results[0],results[1])
            source=Path(d)/'constant.v'
            source.write_text("module constant(output y); assign y=1'b0; endmodule",encoding='utf-8')
            cells,meta=compile_file(source,'constant',Path(d)/'constant')
            _,report=run_vectors(cells,meta,[{'inputs':{},'expect':{'y':0}}],Path(d)/'constant','constant',compressed=True)
            self.assertTrue(report['passed'],report['failures'])

    def test_three_by_two_blocks_and_touching_stages(self):
        from input_buses import configure
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            for count in (2, 4):
                graph, _ = synthesize(ROOT / f'examples/hdl/multiplexer/mux{count}/mux{count}.v', f'mux{count}')
                graph, _ = merge_duplicate_logic(graph)
                graph['_input_bus_config'] = configure(graph, ['data,sel'], 0)
                for margin in (3,4,5,6,8):
                    graph['_port_margin']=margin
                    try:
                        cells, meta = tree_candidate(graph, 100000, 3, False, compact_block=True)
                        break
                    except MapError:
                        if margin==8:raise
                if count == 2:
                    self.assertEqual(meta['logic_core']['bounds']['width'], 3)
                    self.assertEqual(meta['logic_core']['bounds']['height'], 2)
                    self.assertEqual(meta['logic_core']['cells'], 5)
                vectors = [{'inputs': {'data': v, 'sel': s}, 'expect': {'y': (v >> s) & 1}}
                           for v in range(1 << count) for s in range(count)]
                _, report = run_vectors(cells, meta, vectors, folder / str(count), 'mux', compressed=True)
                self.assertTrue(report['passed'], report['failures'])
                self.assert_input_bus(meta)

    def assert_input_bus(self, meta):
        entries = [e for es in meta['inputs'].values() for e in es]
        x = entries[0]['fixture'][0]
        self.assertEqual([e['fixture'] for e in entries], [[x, i] for i in range(len(entries))])
        self.assertEqual([e['contact'] for e in entries], [[x + 1, i] for i in range(len(entries))])
        self.assertTrue(all(e['rotation'] == 1 for e in entries))

    def assert_exterior_ports(self,cells,meta):
        for entries in meta['inputs'].values():
            for entry in entries:
                x,y=entry['contact']; rotation=entry['rotation']
                self.assertTrue(all(px>=x if rotation==1 else px<=x if rotation==3 else py>=y if rotation==2 else py<=y
                                    for px,py in cells))
        for entries in meta['outputs'].values():
            for entry in entries:
                x,y=entry['contact']; fx,fy=entry['fixture']
                self.assertTrue(all(px<=x if fx>x else px>=x if fx<x else py<=y if fy>y else py>=y for px,py in cells))

    def test_rotated_candidates_and_optional_two_row_strip(self):
        source = ROOT / 'examples/hdl/multiplexer/mux4/mux4.v'
        graph, _ = synthesize(source, 'mux4')
        graph, _ = merge_duplicate_logic(graph)
        graph['_input_bus_config'] = {'groups': [['data', 'sel']], 'gap': 0}
        vectors = [{'inputs': {'data': v, 'sel': s}, 'expect': {'y': (v >> s) & 1}}
                   for v in range(16) for s in range(4)]
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            for mirrored in (False, True):
                cells, meta = tree_candidate(graph, 100000, 5, mirrored)
                self.assert_input_bus(meta)
                _, report = run_vectors(cells, meta, vectors, folder / str(mirrored), 'mux', compressed=True)
                self.assertTrue(report['passed'], report['failures'])
            graph.pop('_input_bus_config')
            small,_=synthesize(ROOT/'examples/hdl/multiplexer/mux2/mux2.v','mux2')
            small,_=merge_duplicate_logic(small)
            cells, meta = mux_candidate(small, 100000, 2, False, 'left')
            self.assertEqual(meta['logic_core']['bounds']['height'], 2)
            small_vectors=[{'inputs':{'data':v,'sel':s},'expect':{'y':(v>>s)&1}} for v in range(4) for s in range(2)]
            _, report = run_vectors(cells, meta, small_vectors, folder / 'strip', 'mux', compressed=True)
            self.assertTrue(report['passed'], report['failures'])

    def test_explicit_groups_gap_validation_and_free_inputs(self):
        source = ROOT / 'examples/hdl/multiplexer/mux4/mux4.v'
        vectors = [{'inputs': {'data': v, 'sel': s}, 'expect': {'y': (v >> s) & 1}}
                   for v in range(16) for s in range(4)]
        with tempfile.TemporaryDirectory() as d:
            for i, (groups, gap) in enumerate((([], 0), (['data'], 0), (['data', 'sel'], 0), (['data,sel'], 2))):
                folder = Path(d) / str(i)
                cells, meta = compile_file(source, 'mux4', folder, input_buses=groups, input_bus_gap=gap)
                self.assert_exterior_ports(cells,meta)
                self.assertEqual(len(meta['input_buses']), len(groups))
                for bus in meta['input_buses']:
                    points = bus['fixtures']
                    step=(gap+1,0) if bus['rotation'] in (0,2) else (0,gap+1)
                    self.assertTrue(all((b[0]-a[0],b[1]-a[1])==step for a,b in zip(points,points[1:])))
                _, report = run_vectors(cells, meta, vectors, folder, 'mux4', compressed=True)
                self.assertTrue(report['passed'], report['failures'])
            graph, _ = synthesize(source, 'mux4')
            for groups, gap in ((['missing'], 0), (['data', 'data'], 0), ([''], 0), (['data'], -1)):
                with self.assertRaises(MapError):
                    place(graph, input_buses=groups, input_bus_gap=gap)

    def test_cli_and_generic_graph_grouping(self):
        import json
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            source = folder / 'generic.v'
            source.write_text('module generic(input [1:0] data,input enable,output y); assign y=data[0]^data[1]^enable; endmodule', encoding='utf-8')
            result = subprocess.run([sys.executable, str(ROOT / 'src/verilog_compile.py'), str(source),
                                     '--out', str(folder), '--input-bus', 'data,enable', '--input-bus-gap', '0'],
                                    capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            meta = json.loads((folder / 'generic.build.json').read_text(encoding='utf-8'))
            self.assert_input_bus(meta)
            from mapdata import read_map
            vectors = [{'inputs': {'data': v, 'enable': e}, 'expect': {'y': (v & 1) ^ (v >> 1) ^ e}}
                       for v in range(4) for e in range(2)]
            _, report = run_vectors(read_map(folder / 'generic.save.txt'), meta, vectors, folder, 'generic', compressed=True)
            self.assertTrue(report['passed'], report['failures'])

    def test_auto_bus_spacing_preserves_order_and_exterior(self):
        source=ROOT/'examples/hdl/multiplexer/mux8/mux8.v'
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            cells,meta=compile_file(source,'mux8',folder,input_buses=['data,sel'],input_bus_gap='auto')
            self.assertLess(len(cells),178)
            self.assertLess(meta['settle_ticks'],47)
            self.assertTrue(meta['optimization']['automatic_input_buses'])
            self.assertTrue(meta['io_boundary_verified'])
            search=meta['output_search']
            right=min(c['bounds']['area'] for c in search['candidates'] if c['side']=='right')
            self.assertIn(search['selected']['side'],('top','bottom'))
            self.assertEqual(search['selected']['offset'],0)
            self.assertLess(search['selected']['bounds']['area'],right)
            bus=meta['input_buses'][0]
            self.assertEqual(bus['requested_gap'],'auto')
            self.assertGreater(bus['gap'],0)
            steps=[(b[0]-a[0],b[1]-a[1]) for a,b in zip(bus['fixtures'],bus['fixtures'][1:])]
            self.assertEqual(len(set(steps)),1)
            self.assert_exterior_ports(cells,meta)
            from input_buses import verify_exterior
            broken=dict(cells)
            x,y=bus['fixtures'][0]
            rotation=bus['rotation']
            behind=(x-1,y) if rotation==1 else (x+1,y) if rotation==3 else (x,y-1) if rotation==2 else (x,y+1)
            broken[behind]=Cell(1,1)
            with self.assertRaises(MapError):verify_exterior(broken,meta)
            vectors=[{'inputs':{'data':v,'sel':s},'expect':{'y':(v>>s)&1}}
                     for v in range(256) for s in range(8)]
            _,report=run_vectors(cells,meta,vectors,folder,'mux8',compressed=True)
            self.assertTrue(report['passed'],report['failures'])

    def test_auto_separate_buses_and_generic_spacing(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            source=ROOT/'examples/hdl/multiplexer/mux4/mux4.v'
            cells,meta=compile_file(source,'mux4',folder,input_buses=['data','sel'],input_bus_gap='auto')
            self.assertEqual([bus['ports'] for bus in meta['input_buses']],[['data'],['sel']])
            self.assert_exterior_ports(cells,meta)
            vectors=[{'inputs':{'data':v,'sel':s},'expect':{'y':(v>>s)&1}} for v in range(16) for s in range(4)]
            _,report=run_vectors(cells,meta,vectors,folder,'mux4',compressed=True)
            self.assertTrue(report['passed'],report['failures'])
            generic=folder/'generic.v'
            generic.write_text('module generic(input [1:0] data,input enable,output y); assign y=data[0]^data[1]^enable; endmodule',encoding='utf-8')
            cells,meta=compile_file(generic,'generic',folder,input_buses=['data,enable'],input_bus_gap='auto')
            self.assertTrue(meta['optimization']['automatic_input_buses'])
            self.assertGreater(len({c['gap'] for c in meta['optimization']['bus_candidates']}),1)
            self.assert_exterior_ports(cells,meta)
            vectors=[{'inputs':{'data':v,'enable':e},'expect':{'y':(v&1)^(v>>1)^e}} for v in range(4) for e in range(2)]
            _,report=run_vectors(cells,meta,vectors,folder,'generic',compressed=True)
            self.assertTrue(report['passed'],report['failures'])

    def test_names_and_reversed_data_indices_are_not_templates(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            source = folder / 'renamed.v'
            source.write_text('module renamed(input [0:3] payload, input [1:0] address, output result); assign result=payload[address]; endmodule', encoding='utf-8')
            cells, meta = compile_file(source, 'renamed', folder)
            self.assertEqual(meta['mux_inputs'], 4)
            self.assertEqual([e['index'] for e in meta['inputs']['payload']], [3, 2, 1, 0])
            vectors = [{'inputs': {'payload': value, 'address': s}, 'expect': {'result': (value >> (3 - s)) & 1}}
                       for value in range(16) for s in range(4)]
            _, report = run_vectors(cells, meta, vectors, folder, 'renamed', compressed=True)
            self.assertTrue(report['passed'], report['failures'])

    def test_non_mux_and_observed_internal_nodes_are_rejected(self):
        source = ROOT / 'examples/hdl/multiplexer/mux4/mux4.v'
        graph, _ = synthesize(source, 'mux4')
        graph, _ = merge_duplicate_logic(graph)
        self.assertIsNotNone(recognize_mux(graph))
        extra = deepcopy(graph)
        internal = next(n['output'] for n in extra['nodes'] if n['op'] == 'AND')
        extra['outputs']['observer'] = [{'index': 0, 'net': internal}]
        self.assertIsNone(recognize_mux(extra))
        wrong = deepcopy(graph)
        next(n for n in wrong['nodes'] if n['op'] == 'OR')['op'] = 'XOR'
        self.assertIsNone(recognize_mux(wrong))
        with self.assertRaises(MapError):
            place(graph, max_cells=5)


if __name__ == '__main__':
    unittest.main()
