"""Two historical generations, checked by independent flood/count models."""
from pathlib import Path
import subprocess
import sys
import unittest
from tempfile import TemporaryDirectory

ROOT=Path(__file__).resolve().parents[3]
PROJECT=ROOT/'tests/fixtures/historical/minesweeper'


class MinesweeperRegressionTests(unittest.TestCase):
    def test_v1_historical_112_maps(self):
        with TemporaryDirectory(prefix='arrowshdl-mines-v1-') as directory:
            subprocess.run([sys.executable,'-m','tests.projects.minesweeper.run','--project',str(PROJECT),
                            '--out',directory,'--version','v1','--sizes','3','10','--reuse'],check=True,cwd=ROOT)

    def test_v2_compact_maps_and_preparation_arbitration(self):
        with TemporaryDirectory(prefix='arrowshdl-mines-v2-') as directory:
            subprocess.run([sys.executable,'-m','tests.projects.minesweeper.run','--project',str(PROJECT),
                            '--out',directory,'--version','v2','--matrix','--reuse'],check=True,cwd=ROOT)
