"""Health diagnostics exercise the installed program and identify broken components."""
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from arrowshdl.arrowasm import MapError
from arrowshdl.health import health


class HealthTests(unittest.TestCase):
    def test_operational_health_from_external_directory_without_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable,'-m','arrowshdl','health'],
                                    cwd=directory,capture_output=True,text=True,
                                    encoding='utf-8',timeout=60)
            self.assertEqual(result.returncode,0,result.stderr)
            for component in ('Node.js runtime','HDL compiler','Save codec',
                              'Physical simulator','Preview renderer'):
                self.assertIn('[OK] '+component,result.stdout)
            self.assertIn('all 4 input combinations passed',result.stdout)
            self.assertIn('Health status: OK',result.stdout)
            self.assertTrue(result.stdout.isascii())
            self.assertIn('[100.0%]',result.stderr)
            self.assertEqual(list(Path(directory).iterdir()),[])

    def test_missing_runtime_reports_failure_in_english(self):
        output,error = StringIO(),StringIO()
        with patch('nodejs_wheel.node',side_effect=FileNotFoundError('runtime missing')):
            with redirect_stdout(output),redirect_stderr(error):
                code = health()
        self.assertEqual(code,1)
        self.assertIn('[FAIL] Node.js runtime:',error.getvalue())
        self.assertIn('FileNotFoundError',error.getvalue())
        self.assertIn('Health status: FAILED',error.getvalue())
        self.assertNotIn('Health status: OK',output.getvalue())

    def test_missing_simulator_does_not_attempt_a_build(self):
        output,error = StringIO(),StringIO()
        with tempfile.TemporaryDirectory() as directory:
            with patch('arrowshdl.simulation.runner_binary',return_value=Path(directory)/'missing'), \
                 patch('arrowshdl.simulation.build_runner') as build:
                with redirect_stdout(output),redirect_stderr(error):
                    code = health()
                build.assert_not_called()
        self.assertEqual(code,1)
        self.assertIn('[FAIL] Rust simulator: Simulator executable is missing.',error.getvalue())

    def test_compiler_failure_has_english_diagnostic_and_no_false_success(self):
        output,error = StringIO(),StringIO()
        with patch('arrowshdl.api.compile',side_effect=MapError('Ошибка компилятора')):
            with redirect_stdout(output),redirect_stderr(error):
                code = health()
        self.assertEqual(code,1)
        self.assertIn('[FAIL] HDL compiler:',error.getvalue())
        self.assertTrue(error.getvalue().isascii())
        self.assertNotIn('Health status: OK',output.getvalue())

    def test_health_replaces_check_and_does_not_run_regression_suites(self):
        for arguments in (['check'],['health','--suite','tests']):
            result = subprocess.run([sys.executable,'-m','arrowshdl',*arguments],
                                    capture_output=True,text=True,encoding='utf-8',timeout=10)
            self.assertEqual(result.returncode,2)
            self.assertNotIn('Health status: OK',result.stdout)


if __name__=='__main__':unittest.main()
