"""Public CLI exports exactly one file and streams progress during work."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from arrowshdl.mapdata import read_map
from arrowshdl.test_harness import add_fixture, make_scenario
import arrowshdl


class CliArtifactTests(unittest.TestCase):
    def test_build_clipboard_option_and_output_requirement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'logic.v'
            source.write_text('module logic(input a, output y); assign y = ~a; endmodule')
            missing = subprocess.run([sys.executable, '-m', 'arrowshdl', 'build', source],
                capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(missing.returncode, 2)
            self.assertIn('build requires -o/--out or --clipboard', missing.stderr)
            from arrowshdl.clipboard import copy_text
            with patch('arrowshdl.clipboard.subprocess.run') as run:
                copy_text('save text\n')
            run.assert_called_once()
            self.assertEqual(run.call_args.kwargs['input'], 'save text\n')

    def test_init_creates_project_source_and_design_presets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = subprocess.run([sys.executable, '-m', 'arrowshdl', 'init', root, 'demo',
                '--standard', '1364-2005', '--design', 'ports', '--port', 'input_signal=button',
                '--port', 'output_signal=binary', '--define', 'TRACE', '--parameter', 'WIDTH=4'],
                capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            project = root / 'demo' / 'project.toml'
            source = root / 'demo' / 'demo.v'
            design = root / 'demo' / 'design.toml'
            self.assertTrue(project.is_file())
            self.assertTrue(source.is_file())
            self.assertTrue(design.is_file())
            from arrowshdl.manifest import load_project
            loaded = load_project(project)
            self.assertEqual(loaded.top, 'demo')
            self.assertEqual(loaded.standard, '1364-2005')
            self.assertEqual([row['path'] for row in loaded.design['ports']],
                             ['input_signal', 'output_signal'])
            built = root / 'demo.save.txt'
            build = subprocess.run([sys.executable, '-m', 'arrowshdl', 'build', project, '-o', built],
                capture_output=True, text=True, encoding='utf-8', timeout=60)
            self.assertEqual(build.returncode, 0, build.stderr)

    def test_init_refuses_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = subprocess.run([sys.executable, '-m', 'arrowshdl', 'init', root, 'demo'],
                capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(first.returncode, 0, first.stderr)
            source = root / 'demo' / 'demo.v'
            source.write_text('keep', encoding='utf-8')
            second = subprocess.run([sys.executable, '-m', 'arrowshdl', 'init', root, 'demo'],
                capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(second.returncode, 2)
            self.assertIn('--force', second.stderr)
            self.assertEqual(source.read_text(encoding='utf-8'), 'keep')

    def test_init_grid_design_preset_builds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = subprocess.run([sys.executable, '-m', 'arrowshdl', 'init', root, 'grid_demo',
                '--design', 'grid'], capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            project = root / 'grid_demo' / 'project.toml'
            built = root / 'grid_demo.save.txt'
            result = subprocess.run([sys.executable, '-m', 'arrowshdl', 'build', project, '-o', built],
                capture_output=True, text=True, encoding='utf-8', timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_compact_compile_build_and_link_preserve_native_memory_and_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/'memory.v'
            source.write_text('''module stored_bit(input load,d,output q);
                arrows_register memory(.load(load),.D(d),.Q(q)); endmodule
                module memory_top(input load,d,output q);
                stored_bit bit0(load,d,q); endmodule''')
            project=root/'project.toml'
            project.write_text('version=3\ntop="memory_top"\nsources=["memory.v"]\n')
            environment=dict(os.environ)
            def cli(*args):
                result=subprocess.run([sys.executable,'-m','arrowshdl',*map(str,args)],
                    env=environment,capture_output=True,text=True,encoding='utf-8',timeout=60)
                self.assertEqual(result.returncode,0,result.stderr)
                return result
            obj=root/'memory.aho.json'
            cli('compile',source,'--top','memory_top','-c','-o',obj)
            outputs=[]
            for command,arguments in (('compile',(source,)),('build',(project,)),('link',(obj,))):
                output=root/f'{command}.save.txt'
                top=() if command=='build' else ('--top','memory_top')
                cli(command,*arguments,*top,'--layout','compact','-o',output)
                if command=='compile': compiled=arrowshdl.compile(source,top='memory_top',layout='compact')
                elif command=='build': compiled=arrowshdl.build(project,layout='compact')
                else: compiled=arrowshdl.link([obj],top='memory_top',layout='compact')
                self.assertEqual(read_map(output),compiled.cells)
                metadata=compiled.metadata
                self.assertEqual(metadata['optimization']['mode'],'compact')
                self.assertTrue(metadata['timing']['state_boundaries'])
                outputs.append(metadata)
                help_result=cli(command,'--help')
                self.assertNotIn('--compact',help_result.stdout)
                rejected=subprocess.run([sys.executable,'-m','arrowshdl',command,*map(str,arguments),
                    *top,'--compact','-o',str(root/'rejected.save.txt')],env=environment,
                    capture_output=True,text=True,encoding='utf-8',timeout=30)
                self.assertEqual(rejected.returncode,2)
                self.assertIn('unrecognized arguments: --compact',rejected.stderr)
                vectors=[dict(inputs={'load':load,'d':data},expect={'q':q})
                         for load,data,q in ((0,0,0),(1,1,1),(0,1,1),(0,0,1),(1,0,0))]
                report=arrowshdl.simulate(add_fixture(read_map(output),metadata),
                    make_scenario(metadata,vectors,settle_ticks=100))
                self.assertTrue(report['passed'],report['failures'])
            cli('build',project,'--layout','compact','-o',root/'warm.save.txt')
            warm=arrowshdl.build(project,layout='compact').metadata
            self.assertTrue(all(row['reused'] for row in warm['compiled_modules']))
            cli('build',project,'-o',root/'auto.save.txt')
            ordinary=arrowshdl.build(project).metadata
            self.assertNotEqual({row['key'] for row in warm['compiled_modules']},
                                {row['key'] for row in ordinary['compiled_modules']})

    def test_one_file_metadata_vectors_preview_and_save(self):
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
            png=root/'images'/'preview.png'
            result=cli('compile',source,'--top','xor_unit','-o',output,'--preview',png)
            self.assertIn('Synthesizing',result.stderr)
            self.assertEqual(list(output.parent.iterdir()),[output])
            self.assertEqual(read_map(output),arrowshdl.compile(source,top='xor_unit').cells)
            from PIL import Image
            with Image.open(png) as picture: picture.verify()
            blocked_parent=root/'blocked-parent'
            blocked_parent.write_text('file, not a directory')
            failed_save=root/'failed-preview.save.txt'
            for bad_preview in (blocked_parent/'preview.png', blocked_parent/'nested'/'preview.png'):
                failed=subprocess.run([sys.executable,'-m','arrowshdl','compile',str(source),
                    '--top','xor_unit','-o',str(failed_save),'--preview',str(bad_preview)],
                    capture_output=True,text=True,encoding='utf-8')
                self.assertEqual(failed.returncode,2)
                self.assertIn('Preview parent must be a directory',failed.stderr)
                self.assertFalse(failed_save.exists())
            vectors=root/'vectors.json'
            vectors.write_text(json.dumps([dict(inputs={'a':a,'b':b},expect={'y':a^b})
                for a in (0,1) for b in (0,1)]))
            cli('test',source,vectors,'--top','xor_unit','--vectors','-o',root/'report.json')
            self.assertTrue(json.loads((root/'report.json').read_text())['passed'])
            cli('preview',output,'-o',root/'preview.png')
            cli('compile',source,'--top','xor_unit','-o',root/'save'/'xor.save.txt')
            self.assertEqual(read_map(output),read_map(root/'save'/'xor.save.txt'))
            self.assertEqual(len(list((root/'save').iterdir())),1)
            single_build = root/'single-build.save.txt'
            cli('build', source, '--top', 'xor_unit', '-o', single_build, '--preview', root/'single-build.png')
            self.assertEqual(read_map(output), read_map(single_build))
            auto_build = root/'auto-source.save.txt'
            auto_source_dir = root/'auto-source'
            auto_source_dir.mkdir()
            auto_source = auto_source_dir/'auto_source.v'
            auto_source.write_text('module auto_source(input a, output y); assign y = a; endmodule')
            auto = subprocess.run([sys.executable, '-m', 'arrowshdl', 'build', '-o', auto_build],
                cwd=auto_source_dir, capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(auto.returncode, 0, auto.stderr)
            rejected=subprocess.run([sys.executable,'-m','arrowshdl','compile',str(source),
                '--top','xor_unit','-o',str(output.parent)],capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(rejected.returncode,2)
            self.assertIn('Output must be a file',rejected.stderr)
            self.assertEqual(list(output.parent.iterdir()),[output])
            project=root/'project.toml'
            project.write_text('version=3\ntop="xor_unit"\nsources=["xor.v"]\n')
            built=root/'project.save.txt'
            cli('build',project,'-o',built,'--preview',root/'project.png')
            project_auto = root/'auto-project.save.txt'
            project_run = subprocess.run([sys.executable, '-m', 'arrowshdl', 'build', '-o', project_auto],
                cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(project_run.returncode, 0, project_run.stderr)
            cli('test',project,vectors,'--vectors','-o',root/'project.report.json')
            self.assertTrue(json.loads((root/'project.report.json').read_text())['passed'])
            invalid=subprocess.run([sys.executable,'-m','arrowshdl','compile',str(source),
                '--top','xor_unit','-o',str(root/'forbidden.json')],capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(invalid.returncode,2)
            self.assertFalse((root/'forbidden.json').exists())

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
