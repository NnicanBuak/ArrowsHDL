"""Logical graph composition validates interfaces before physical placement."""
from pathlib import Path
import tempfile
import unittest

import arrowshdl
from arrowshdl.test_harness import add_fixture,make_scenario
from arrowshdl.manifest import load_project


class ProjectGraphTests(unittest.TestCase):
    def test_compiled_component_build_needs_no_source_and_repeated_modules_compile_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'invert.v'
            source.write_text('module invert(input [1:0] a,output [1:0] y); assign y=~a; endmodule')
            arrowshdl.compile(source,top='invert',out=root/'unit.json',compact=True)
            path=root/'map.toml'
            path.write_text('''version=2
top="reused"
[[components]]
name="unit"
file="unit.json"
[[inputs]]
name="a"
width=2
[[connections]]
from="a"
to="unit.a"
[[outputs]]
name="y"
from="unit.y"
''')
            source.unlink()
            result=arrowshdl.build(path,out=root/'assembled.json')
            self.assertFalse(result.metadata['compiled_modules'])
            report=arrowshdl.simulate(add_fixture(result.cells,result.metadata),make_scenario(result.metadata,
                [dict(inputs={'a':i},expect={'y':3^i}) for i in range(4)]))
            self.assertTrue(report['passed'],report['failures'])
            source.write_text('module invert(input [1:0] a,output [1:0] y); assign y=~a; endmodule')
            path.write_text('''version=2
top="chain"
sources=["invert.v"]
[[modules]]
name="first"
hdl="invert"
[[modules]]
name="second"
hdl="invert"
[[inputs]]
name="a"
width=2
[[connections]]
from="a"
to="first.a"
[[connections]]
from="first.y"
to="second.a"
[[outputs]]
name="y"
from="second.y"
''')
            result=arrowshdl.build(path,out=root/'chain.json')
            self.assertEqual(len(result.metadata['compiled_modules']),1)
            self.assertEqual(result.metadata['optimization']['instances'],2)
            warm=arrowshdl.build(path,out=root/'chain.json')
            self.assertTrue(warm.metadata['compiled_modules'][0]['reused'])
            self.assertEqual(result.cells,warm.cells)
            source.write_text(source.read_text().replace('~a','a'))
            changed=arrowshdl.build(path,out=root/'chain.json')
            self.assertFalse(changed.metadata['compiled_modules'][0]['reused'])
            self.assertNotEqual(result.metadata['compiled_modules'][0]['key'],changed.metadata['compiled_modules'][0]['key'])

    def test_native_register_and_latch_retain_state_after_control_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'state.v'
            source.write_text('''module state(input load,set,clear,input [2:0] data,output [2:0] q,output state);
                arrows_register #(.WIDTH(3)) register(load,data,q); arrows_latch latch(set,clear,state); endmodule''')
            result=arrowshdl.compile(source,top='state',out=root/'out.json')
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
                module parity(input [1:0] a,output y); assign y=^a; endmodule''')
            path=root/'project.toml'
            path.write_text('''version=2
top="demo"
sources=["logic.v"]
[[modules]]
name="inverter"
hdl="invert"
parameters={N=4}
[[modules]]
name="check"
hdl="parity"
[[inputs]]
name="data"
width=4
[[connections]]
from="data"
to="inverter.a"
[[connections]]
from="inverter.y[3:2]"
to="check.a"
[[outputs]]
name="word"
from="inverter.y"
[[outputs]]
name="parity"
from="check.y"
''')
            result=arrowshdl.build(path,out=root/'out.json',timeout=30)
            self.assertEqual(result.metadata['project_version'],2)
            self.assertEqual(result.metadata['optimization']['mode'],'default')
            vectors=[dict(inputs={'data':i},expect={'word':15^i,'parity':((15^i)>>2).bit_count()%2}) for i in range(16)]
            report=arrowshdl.simulate(add_fixture(result.cells,result.metadata),make_scenario(result.metadata,vectors))
            self.assertTrue(report['passed'],report['failures'])
            self.assertTrue((root/'out.json').is_file())
            self.assertIn('connections', result.metadata['project_graph'])
            self.assertEqual(len(result.metadata['compiled_modules']),2)
            warm=arrowshdl.build(path,out=root/'out.json',timeout=30)
            self.assertTrue(all(row['reused'] for row in warm.metadata['compiled_modules']))
            self.assertEqual(warm.cells,result.cells)
            text=path.read_text()
            for altered in (text.replace('to="check.a"','to="inverter.a"'),
                            text.replace('from="inverter.y[3:2]"','from="inverter.y[5:4]"'),
                            text.replace('from="inverter.y[3:2]"','from="inverter.y"'),
                            text.replace('from="data"','from="inverter.a"'),
                            text.replace('hdl="parity"','hdl="parity"\nat=[0,0]')):
                path.write_text(altered)
                with self.assertRaises(arrowshdl.MapError): arrowshdl.build(path,out=root/'invalid.json',timeout=30)

    def test_default_has_no_circuit_templates_and_compact_never_grows_complete_map(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/'unnamed.v'
            source.write_text('''module unnamed(input [3:0] a,b,input select,output [3:0] y);
                assign y=select ? a+b : a^b; endmodule''')
            ordinary=arrowshdl.compile(source,top='unnamed',out=root/'normal.json',timeout=30)
            compact=arrowshdl.compile(source,top='unnamed',out=root/'small.json',timeout=30,compact=True)
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
            self.assertEqual(len(list(folder.glob('*.toml'))),1,folder.name)
            for path in folder.iterdir():
                self.assertTrue((path.is_dir() and path.name in ('build','visuals')) or
                                (path.is_file() and (path.name=='README.md' or path.suffix in ('.v','.sv','.toml'))),str(path))


if __name__=='__main__':unittest.main()
