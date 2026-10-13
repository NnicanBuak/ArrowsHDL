"""Public CLI exports exactly one file and streams progress during work."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from PIL import Image

from arrowshdl.mapdata import read_map


class CliArtifactTests(unittest.TestCase):
    def test_compile_writes_one_encoded_save_and_source_preview_needs_no_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/'xor.v'
            source.write_text('module xor_unit(input a,b,output y); assign y=a^b; endmodule')
            output=root/'out'/'unit.save.txt'
            def cli(*args):
                result=subprocess.run([sys.executable,'-m','arrowshdl',*map(str,args)],
                    capture_output=True,text=True,encoding='utf-8',timeout=30)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn('[100.0%]',result.stderr)
                return result
            result=cli('compile',source,'--top','xor_unit','-o',output)
            self.assertIn('Synthesizing',result.stderr)
            self.assertEqual(list(output.parent.iterdir()),[output])
            cli('preview',source,'--top','xor_unit','-o',root/'preview.png')
            cli('preview',source,'--top','xor_unit','--style','logical','-o',root/'logical.png')
            with Image.open(root/'logical.png') as preview:preview.verify()
            cli('compile',source,'--top','xor_unit','-o',root/'save'/'xor.save.txt')
            self.assertEqual(read_map(output),read_map(root/'save'/'xor.save.txt'))
            self.assertEqual(len(list((root/'save').iterdir())),1)
            rejected=subprocess.run([sys.executable,'-m','arrowshdl','compile',str(source),
                '--top','xor_unit','-o',str(output.parent)],capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(rejected.returncode,2)
            self.assertIn('Output must be a file',rejected.stderr)
            self.assertEqual(list(output.parent.iterdir()),[output])

    def test_progress_is_visible_before_process_finishes(self):
        process=subprocess.Popen([sys.executable,'-m','arrowshdl','health'],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
        try:
            first=process.stderr.readline()
            self.assertIn('[  0.0%]',first)
            self.assertIsNone(process.poll())
            _,logs=process.communicate(timeout=30)
            self.assertEqual(process.returncode,0,logs)
            self.assertIn('Synthesizing',logs)
            self.assertIn('[100.0%]',logs)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

    def test_missing_component_reports_resolved_filename(self):
        from arrowshdl.manifest import load_project
        from arrowshdl.arrowasm import MapError
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            path=root/'project.toml'
            (root/'demo.v').write_text('module demo(input a,output y); assign y=a; endmodule')
            path.write_text('version=3\ntop="demo"\nsources=["demo.v"]\ndesign="design.toml"\n')
            (root/'design.toml').write_text('version=1\n[[components]]\nname="display"\nfile="build/display.json"\n')
            with self.assertRaisesRegex(MapError,'display.json'):
                load_project(path)

    def test_help_and_runtime_failures_are_in_english(self):
        def cli(*args):
            return subprocess.run([sys.executable,'-m','arrowshdl',*args],
                capture_output=True,text=True,encoding='utf-8',timeout=30)
        for command in ('compile','build','link','simulate','test','encode','decode','graph','preview','health'):
            result=cli(command,'--help')
            self.assertEqual(result.returncode,0)
            self.assertFalse(any('\u0400'<=c<='\u04ff' for c in result.stdout+result.stderr))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            project=root/'bad.toml'
            (root/'source.v').write_text('module bad(input a,output y); assign y=a; endmodule')
            project.write_text('version=3\ntop="bad"\nsources=["source.v"]\ndesign="design.toml"\n')
            (root/'design.toml').write_text('version=1\n[[components]]\nname="screen"\nfile="missing.json"\n')
            result=cli('build',str(project),'-o',str(root/'result.save.txt'))
            self.assertEqual(result.returncode,2)
            self.assertIn('Error: Component file not found:',result.stderr)
            self.assertFalse(any('\u0400'<=c<='\u04ff' for c in result.stderr))
            source=root/'source.v'
            source.write_text('module demo(input a,output y); assign y=a; endmodule')
            cli('compile',str(source),'--top','demo','-o',str(root/'demo.save.txt'))
            scenario=root/'bad-scenario.json'
            scenario.write_text('{"ticks":0,"inputs":[],"expect":[],"observe":[[0,0]]}')
            result=cli('simulate',str(root/'demo.save.txt'),str(scenario),'-o',str(root/'trace.json'))
            self.assertEqual(result.returncode,2)
            self.assertFalse(any('\u0400'<=c<='\u04ff' for c in result.stderr))

    def test_malformed_object_has_a_cli_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            obj=root/'malformed.aho.json'
            obj.write_text(json.dumps({
                'format':'arrowshdl-object','version':1,'standard':'1800-2023','top':'demo',
            }))
            result=subprocess.run([sys.executable,'-m','arrowshdl','link',str(obj),
                '--top','demo','-o',str(root/'result.save.txt')],
                capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,2)
            self.assertIn('malformed ArrowsHDL object: rtlil must be an object',result.stderr)
            self.assertNotIn('Traceback',result.stderr)
