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
            from arrowshdl.map_preview import render_cells
            preview=root/'logical.png'
            render_cells(result.cells,preview,result.metadata,style='logical')
            self.assertTrue(preview.is_file())
            self.assertEqual([block['id'] for block in result.metadata['module_blocks']],['dut'])

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

    def test_default_has_no_circuit_templates_and_compact_never_grows_complete_map(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/'unnamed.v'
            source.write_text('''module unnamed(input [3:0] a,b,input select,output [3:0] y);
                assign y=select ? a+b : a^b; endmodule''')
            ordinary=arrowshdl.compile(source,top='unnamed',out=root/'normal.save.txt',timeout=30)
            compact=arrowshdl.compile(source,top='unnamed',out=root/'small.save.txt',timeout=30,compact=True)
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
                self.assertTrue((path.is_dir() and path.name in ('build','visuals')) or
                                (path.is_file() and (path.name=='README.md' or path.suffix in ('.v','.sv','.toml'))),str(path))


if __name__=='__main__':unittest.main()
