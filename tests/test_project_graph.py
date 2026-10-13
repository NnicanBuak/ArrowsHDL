"""Logical graph composition validates interfaces before physical placement."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import arrowshdl
from arrowshdl.test_harness import add_fixture,make_scenario
from arrowshdl.manifest import load_project


class ProjectGraphTests(unittest.TestCase):
    def test_native_placement_anchors_offset_bounds_through_nested_hierarchy(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'native.v').write_text('''module native_bit(output y);
                wire n;
                arrows_cell #(.TYPE(1),.X(3),.Y(4),.ROTATION(1)) first(
                    .I(1'b0),.B(1'b0),.S(1'b0),.O(n));
                arrows_cell #(.TYPE(1),.X(4),.Y(4),.ROTATION(1)) second(
                    .I(n),.B(1'b0),.S(1'b0),.O(y)); endmodule
                module panel(output y);
                (* arrows_origin_x=7, arrows_origin_y=-2 *) native_bit inner(y);
                endmodule
                module native_top(output [1:0] y);
                (* arrows_origin_x=30, arrows_origin_y=40 *) panel u0(y[0]);
                (* arrows_origin_x=-20, arrows_origin_y=50 *) panel u1(y[1]);
                endmodule''')
            project=root/'project.toml'
            project.write_text('version=3\ntop="native_top"\nsources=["native.v"]\ndesign="design.toml"\n')
            design=root/'design.toml'
            design.write_text('version=1\n')
            original=arrowshdl.build(project,timeout=30)
            self.assertEqual(set(original.cells),{(40,42),(41,42),(-10,52),(-9,52)})
            design.write_text('version=1\n[[placement.placements]]\ninstance="u0"\nat=[10,20]\n'
                              '[[placement.placements]]\ninstance="u1"\nat=[-10,40]\n')
            result=arrowshdl.build(project,timeout=30)
            self.assertEqual(set(result.cells),{(10,20),(11,20),(-10,40),(-9,40)})
            self.assertEqual(result.metadata['instances']['u0.inner']['bounds']['min'],[10,20])
            self.assertEqual(result.metadata['instances']['u1.inner']['bounds']['min'],[-10,40])
            self.assertEqual([entry['contact'] for entry in result.ports['outputs']['y']],[[11,20],[-9,40]])
            self.assertEqual(result.cells[(10,20)],original.cells[(40,42)])
            self.assertEqual(result.cells[(11,20)],original.cells[(41,42)])

    def test_native_grid_anchors_nested_offset_cells_and_preserves_size_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'native.v').write_text('''module native_bit(output y);
                wire n;
                arrows_cell #(.TYPE(1),.X(-3),.Y(4),.ROTATION(1)) first(
                    .I(1'b0),.B(1'b0),.S(1'b0),.O(n));
                arrows_cell #(.TYPE(1),.X(-2),.Y(4),.ROTATION(1)) second(
                    .I(n),.B(1'b0),.S(1'b0),.O(y)); endmodule
                module panel(output y);
                (* arrows_origin_x=7, arrows_origin_y=-2 *) native_bit inner(y);
                endmodule
                module native_grid(output [3:0] y);
                genvar row,col;
                generate for(row=0;row<2;row=row+1) begin: rows
                  for(col=0;col<2;col=col+1) begin: cols
                    panel tile(y[row*2+col]);
                  end
                end endgenerate endmodule''')
            project=root/'project.toml'
            project.write_text('version=3\ntop="native_grid"\nsources=["native.v"]\ndesign="design.toml"\n')
            design=root/'design.toml'
            for origin,step in (([-40,100],[20,30]),([10,-20],[30,40])):
                with self.subTest(origin=origin,step=step):
                    design.write_text('version=1\n[[placement.grids]]\n'
                        'instances="rows[*].cols[*].tile"\n'
                        f'origin={origin}\nstep={step}\nmax_cell_size=[2,1]\n')
                    result=arrowshdl.build(project,timeout=30)
                    expected=set()
                    for row in range(2):
                        for col in range(2):
                            x,y=origin[0]+col*step[0],origin[1]+row*step[1]
                            expected.update(((x,y),(x+1,y)))
                            bounds=result.metadata['instances'][f'rows[{row}].cols[{col}].tile.inner']['bounds']
                            self.assertEqual(bounds['min'],[x,y])
                            self.assertEqual((bounds['width'],bounds['height']),(2,1))
                    self.assertEqual(set(result.cells),expected)
            design.write_text('version=1\n[[placement.grids]]\n'
                'instances="rows[*].cols[*].tile"\nstep=[20,30]\nmax_cell_size=[1,1]\n')
            with self.assertRaisesRegex(arrowshdl.MapError,'max_cell_size exceeded'):
                arrowshdl.build(project,timeout=30)

    def test_native_nested_placements_keep_descendant_constraints_absolute(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'native.v').write_text('''module child(output y);
                arrows_cell #(.TYPE(1),.X(1),.Y(4),.ROTATION(1)) c0(
                    .I(1'b0),.B(1'b0),.S(1'b0),.O(y)); endmodule
                module panel(output [1:0] y);
                arrows_cell #(.TYPE(1),.X(3),.Y(4),.ROTATION(1)) c0(
                    .I(1'b0),.B(1'b0),.S(1'b0),.O(y[0]));
                child inner(y[1]); endmodule
                module native_top(output [1:0] y); panel u0(y); endmodule''')
            project=root/'project.toml'
            project.write_text('version=3\ntop="native_top"\nsources=["native.v"]\ndesign="design.toml"\n')
            design=root/'design.toml'
            design.write_text('version=1\n[[placement.placements]]\ninstance="u0"\nat=[10,20]\n'
                              '[[placement.placements]]\ninstance="u0.inner"\nat=[20,20]\n')
            result=arrowshdl.build(project,timeout=30)
            self.assertEqual(set(result.cells),{(10,20),(20,20)})
            self.assertEqual(result.metadata['bounds']['min'],[10,20])
            self.assertEqual(result.metadata['instances']['u0.inner']['bounds']['min'],[20,20])
            self.assertEqual([entry['contact'] for entry in result.ports['outputs']['y']],[[10,20],[20,20]])
            design.write_text('version=1\n[[placement.placements]]\ninstance="u0"\nat=[10,20]\n'
                              '[[placement.placements]]\ninstance="u0.inner"\nat=[0,20]\n')
            with self.assertRaisesRegex(arrowshdl.MapError,'origin .* expected'):
                arrowshdl.build(project,timeout=30)

    def test_design_grid_changes_instance_origins_and_steps_and_checks_size(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'logic.v').write_text('''module bit_cell(input a,output y); assign y=~a; endmodule
                module grid_top(input [3:0] a,output [3:0] y);
                genvar row,col;
                generate for(row=0;row<2;row=row+1) begin: rows
                  for(col=0;col<2;col=col+1) begin: cols
                    bit_cell tile(a[row*2+col],y[row*2+col]);
                  end
                end endgenerate endmodule''')
            path=root/'project.toml'
            path.write_text('version=3\ntop="grid_top"\nsources=["logic.v"]\ndesign="design.toml"\n')
            for origin,step in (([120,148],[56,70]),([200,300],[80,100])):
                (root/'design.toml').write_text('version=1\n[[placement.grids]]\n'
                    'instances="rows[*].cols[*].tile"\n'
                    f'origin={origin}\nstep={step}\nmax_cell_size=[56,64]\n')
                result=arrowshdl.build(path,out=root/'out.save.txt',layout='compact')
                for row in range(2):
                    for col in range(2):
                        bounds=result.metadata['instances'][f'rows[{row}].cols[{col}].tile']['bounds']
                        self.assertEqual(bounds['min'],[origin[0]+col*step[0],origin[1]+row*step[1]])
                vectors=[dict(inputs={'a':value},expect={'y':value^15}) for value in range(16)]
                report=arrowshdl.simulate(add_fixture(result.cells,result.metadata),make_scenario(result.metadata,vectors))
                self.assertTrue(report['passed'],report['failures'])
            (root/'design.toml').write_text('version=1\n[[placement.grids]]\n'
                'instances="rows[*].cols[*].tile"\nstep=[56,70]\nmax_cell_size=[1,1]\n')
            with self.assertRaisesRegex(arrowshdl.MapError,'exceeds max_cell_size'):
                arrowshdl.build(path,out=root/'too-large.save.txt',layout='compact')
            (root/'design.toml').write_text('version=1\n[[placement.grids]]\n'
                'instances="missing[*].cols[*].tile"\nstep=[56,70]\n')
            with self.assertRaisesRegex(arrowshdl.MapError,'no matching HDL instances'):
                arrowshdl.build(path,out=root/'unmatched.save.txt')

    def test_legacy_graph_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'project.toml'
            path.write_text('version=2\ntop="legacy"\n')
            with self.assertRaises(arrowshdl.MapError): arrowshdl.build(path,out=Path(directory)/'out.save.txt')

    def test_native_register_and_latch_retain_state_after_control_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'state.v'
            source.write_text('''module state(input load,set,clear,input [2:0] data,output [2:0] q,output state);
                arrows_register #(.WIDTH(3)) register(load,data,q); arrows_latch latch(set,clear,state); endmodule''')
            result=arrowshdl.compile(source,top='state',out=root/'out.save.txt')
            sequence=[(0,0,1,0,0,0),(1,0,0,3,3,0),(0,0,0,3,3,0),(0,0,0,5,3,0),
                      (1,0,0,5,5,0),(0,0,0,5,5,0),(0,1,0,2,5,1),(0,0,0,7,5,1),(0,0,1,7,5,0)]
            vectors=[dict(inputs=dict(load=l,set=s,clear=c,data=d),expect=dict(q=q,state=t)) for l,s,c,d,q,t in sequence]
            report=arrowshdl.simulate(add_fixture(result.cells,result.metadata),make_scenario(result.metadata,vectors,settle_ticks=100))
            self.assertTrue(report['passed'],report['failures'])

    def test_parameterized_modules_ranges_and_fanout(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'logic.v').write_text('''module invert #(parameter N=2)(input [N-1:0] a,output [N-1:0] y);
                assign y=~a; endmodule
                module parity(input [1:0] a,output y); assign y=^a; endmodule
                module demo(input [3:0] data,output [3:0] word,output parity_bit);
                    wire [3:0] inverse;
                    invert #(.N(4)) inverter(data,inverse);
                    parity check(inverse[3:2],parity_bit);
                    assign word=inverse;
                endmodule''')
            path=root/'project.toml'
            path.write_text('''version=3
top="demo"
sources=["logic.v"]
design="design.toml"
''')
            (root/'design.toml').write_text('version=1\n')
            result=arrowshdl.build(path,out=root/'out.save.txt',timeout=30)
            self.assertEqual(result.metadata['project_version'],3)
            self.assertTrue((root/'out.save.txt').is_file())
            self.assertEqual(result.metadata['optimization']['instances'],2)
            self.assertEqual(len(result.metadata['compiled_modules']),2)
            warm=arrowshdl.build(path,out=root/'out.save.txt',timeout=30)
            self.assertTrue(all(row['reused'] for row in warm.metadata['compiled_modules']))
            self.assertEqual(warm.cells,result.cells)

    def test_single_module_project_connects_root_ports_to_its_logic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'logic.v').write_text(
                'module dut(input a, output y); assign y=~a; endmodule',
                encoding='utf-8',
            )
            project = root / 'project.toml'
            project.write_text('version=3\ntop="dut"\nsources=["logic.v"]\n', encoding='utf-8')

            result = arrowshdl.build(project, out=root / 'out.save.txt', timeout=30)

            vectors = [
                dict(inputs={'a': value}, expect={'y': 1 - value})
                for value in (0, 1)
            ]
            report = arrowshdl.simulate(
                add_fixture(result.cells, result.metadata),
                make_scenario(result.metadata, vectors),
            )
            self.assertTrue(report['passed'], report['failures'])

    def test_include_search_order_is_part_of_compiled_module_cache_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / 'cache'
            source = root / 'logic.v'
            source.write_text(
                'module gate(input a,b, output y);\n'
                '`include "choice.vh"\n'
                'endmodule\n'
                'module top(input a,b, output y); gate unit(a,b,y); endmodule',
                encoding='utf-8',
            )
            for name, operator in (('and', '&'), ('or', '|')):
                folder = root / name
                folder.mkdir()
                (folder / 'choice.vh').write_text(
                    f'assign y=a{operator}b;\n', encoding='utf-8'
                )

            records = []
            with patch.dict(os.environ, {'ARROWSHDL_CACHE_DIR': str(cache)}):
                for directories, expected in ((('and', 'or'), 0), (('or', 'and'), 1)):
                    project = root / 'project.toml'
                    project.write_text(
                        'version=3\ntop="top"\nsources=["logic.v"]\n'
                        f'include_dirs={json.dumps(list(directories))}\n',
                        encoding='utf-8',
                    )
                    result = arrowshdl.build(project, out=root / 'out.save.txt', timeout=30)
                    scenario = make_scenario(
                        result.metadata,
                        [dict(inputs={'a': 0, 'b': 1}, expect={'y': expected})],
                    )
                    report = arrowshdl.simulate(
                        add_fixture(result.cells, result.metadata), scenario
                    )
                    self.assertTrue(report['passed'], report['failures'])
                    records.extend(result.metadata['compiled_modules'])

            self.assertNotEqual(records[0]['key'], records[1]['key'])
            self.assertFalse(records[1]['reused'])

    def test_yosys_upgrade_invalidates_compiled_module_cache(self):
        from arrowshdl.module_cache import compiled_module

        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/'logic.v'
            source.write_text('module dut(input a,output y); assign y=~a; endmodule',encoding='utf-8')
            manifest=root/'project.toml'
            manifest.write_text('version=3\ntop="dut"\nsources=["logic.v"]\n',encoding='utf-8')
            project=load_project(manifest)
            result=arrowshdl.compile(source,top='dut')
            module=dict(hdl='dut')
            with patch.dict(os.environ,{'ARROWSHDL_CACHE_DIR':str(root/'cache')}), \
                 patch('arrowshdl.module_cache.compile_file',return_value=(result.cells,result.metadata)) as compile_file:
                with patch('arrowshdl.module_cache.version',return_value='0.69.0.0.post1233'):
                    cold=compiled_module(project,module,root,30,'auto',1000000)[2]
                    warm=compiled_module(project,module,root,30,'auto',1000000)[2]
                with patch('arrowshdl.module_cache.version',return_value='0.70.0.0.post1259'):
                    upgraded=compiled_module(project,module,root,30,'auto',1000000)[2]
                self.assertEqual(compile_file.call_count,2)
            self.assertFalse(cold['reused'])
            self.assertTrue(warm['reused'])
            self.assertEqual(cold['key'],warm['key'])
            self.assertFalse(upgraded['reused'])
            self.assertNotEqual(cold['key'],upgraded['key'])

    def test_default_has_no_circuit_templates_and_compact_never_grows_complete_map(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/'unnamed.v'
            source.write_text('''module unnamed(input [3:0] a,b,input select,output [3:0] y);
                assign y=select ? a+b : a^b; endmodule''')
            ordinary=arrowshdl.compile(source,top='unnamed',out=root/'normal.save.txt',timeout=30)
            compact=arrowshdl.compile(source,top='unnamed',out=root/'small.save.txt',timeout=30,layout='compact')
            self.assertFalse(ordinary.metadata['optimization']['templates'])
            self.assertEqual(len(ordinary.metadata['optimization']['attempts']),1)
            self.assertGreater(len(compact.metadata['optimization']['attempts']),1)
            self.assertLessEqual(len(compact.cells),len(ordinary.cells))
            self.assertLessEqual(compact.metadata['bounds']['area'],ordinary.metadata['bounds']['area'])
            vectors=[dict(inputs={'a':a,'b':b,'select':s},expect={'y':((a+b)&15) if s else a^b})
                     for a in range(16) for b in range(16) for s in range(2)]
            for result in (ordinary,compact):
                report=arrowshdl.simulate(add_fixture(result.cells,result.metadata),make_scenario(result.metadata,vectors,compressed=True))
                self.assertTrue(report['passed'],report['failures'])

    def test_source_tree_has_only_documentation_logic_and_one_manifest(self):
        root=Path(__file__).resolve().parents[1]/'examples'
        for folder in root.iterdir():
            if not folder.is_dir(): continue
            self.assertTrue((folder/'project.toml').is_file(),folder.name)
            self.assertTrue(set(path.name for path in folder.glob('*.toml')) <= {'project.toml','design.toml'},folder.name)
            for path in folder.iterdir():
                self.assertTrue((path.is_dir() and path.name in ('build','visuals','geometry')) or
                                (path.is_file() and (path.name=='README.md' or path.suffix in ('.v','.sv','.toml'))),str(path))


if __name__=='__main__':unittest.main()
