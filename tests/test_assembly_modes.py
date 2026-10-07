import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("arrowasm_modes", ROOT / "src/arrowasm.py")
asm = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = asm
spec.loader.exec_module(asm)


class AssemblyModeTests(unittest.TestCase):
    def test_test_and_production_builds(self):
        source = "FORMAT 0\nPLACE level_source -1 0 right\nPLACE arrow 0 0 right mirrored\nPLACE level_target 1 0 up\nPLACE source 4 4 down\nPLACE type_255 8 8 left\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "circuit.l.asm"
            input_path.write_text(source, encoding="utf-8")
            maps = []
            for flags in ([], ["--strip-test-ports"]):
                output = root / ("production.txt" if flags else "test.txt")
                result = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "src/arrowasm.py"), "assemble", str(input_path), "-o", str(output), *flags], capture_output=True, text=True, encoding="utf-8", timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                maps.append(asm.decode(output.read_text(encoding="utf-8")))
            self.assertEqual(maps[0], asm.lower(asm.parse(source)))
            self.assertEqual(maps[1], {(0,0): asm.Cell(1,1,True), (4,4): asm.Cell(2,2), (8,8): asm.Cell(255,3)})

    def test_strip_flag_does_not_silently_change_disassembly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "map.txt"
            input_path.write_text("AAAAAA==", encoding="utf-8")
            output = root / "map.l.asm"
            result = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "src/arrowasm.py"), "disassemble", str(input_path), "-o", str(output), "--strip-test-ports"], capture_output=True, text=True, encoding="utf-8", timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
