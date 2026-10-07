import base64
import importlib.util
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("arrowasm", ROOT / "src" / "arrowasm.py")
asm = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = asm
spec.loader.exec_module(asm)


class CodecTests(unittest.TestCase):
    def test_source_target_external_encoding(self):
        # Produced by chubrik/arrows-compiler and checked against game 1.4 save/load.
        save = "AAABAAAAAAABFgAAABcAAQU="
        expected = {(0, 0): asm.Cell(22, 0), (1, 0): asm.Cell(23, 1, True)}
        source = "FORMAT 0\nPLACE level_source 0 0 up\nPLACE level_target 1 0 right mirrored\n"
        self.assertEqual(asm.decode(save), expected)
        self.assertEqual(asm.lower(asm.parse(source)), expected)
        self.assertEqual(asm.encode(expected), save)
        self.assertEqual(asm.lower(asm.parse(asm.disassemble(expected))), expected)

    def test_identity_uses_source_target(self):
        source = (ROOT / "examples" / "identity.l.asm").read_text(encoding="utf-8")
        save = (ROOT / "examples" / "identity.save.txt").read_text(encoding="utf-8")
        expected = {(0, 0): asm.Cell(22, 1), (1, 0): asm.Cell(1, 1), (2, 0): asm.Cell(23, 0)}
        self.assertEqual(asm.lower(asm.parse(source)), expected)
        self.assertEqual(asm.decode(save), expected)
        self.assertEqual(asm.decode(asm.encode(expected)), expected)

    def test_user_TEST_sample(self):
        save = (ROOT / "examples" / "test.save.txt").read_text(encoding="utf-8")
        cells = asm.decode(save)
        expected_rows = ["###.###.###.###", ".#..#...#....#.", ".#..###.###..#.", ".#..#.....#..#.", ".#..###.###..#."]
        expected = {(x, y): asm.Cell(2, 0) for y, row in enumerate(expected_rows) for x, char in enumerate(row) if char == "#"}
        self.assertEqual(cells, expected)
        rebuilt = asm.encode(asm.lower(asm.parse(asm.disassemble(cells))))
        self.assertEqual(asm.decode(rebuilt), expected)

    def test_all_types_rotations_and_reflections_roundtrip(self):
        cells = {}
        for type_id in range(1, 256):
            for rotation in range(4):
                for mirrored in (False, True):
                    cells[(type_id - 128, rotation * 2 + mirrored - 4)] = asm.Cell(type_id, rotation, mirrored)
        text = asm.disassemble(asm.decode(asm.encode(cells)))
        self.assertEqual(asm.lower(asm.parse(text)), cells)

    def test_known_external_save(self):
        # Public chubrik builder-config line fragment, not produced by this codec.
        save = "AAADAAAAAAAGCQEAABAABgACABMAEgEMAAMAEAATAQoLBAMFAgYCBwIIAgkCCgILAgwCDQIOAg8CBwAUAQEAAAAACg8AAgECAgIDAgQCBQIGAgcCCAIJAgoCCwIMAg0CDgIPAgIAAAABCgQAAgECAgIDAgQCCQEGABYA"
        cells = asm.decode(save)
        self.assertGreater(len(cells), 30)
        self.assertEqual(asm.decode(asm.encode(asm.lower(asm.parse(asm.disassemble(cells))))), cells)

    def test_negative_coordinate_encoding(self):
        cells = {(-1, -17): asm.Cell(1, 1, True)}
        expected = struct.pack("<HHHHBBBBB", 0, 1, 0x8001, 0x8002, 0, 1, 0, 255, 5)
        self.assertEqual(base64.b64decode(asm.encode(cells)), expected)
        self.assertEqual(asm.decode(asm.encode(cells)), cells)

    def test_full_chunk(self):
        cells = {(x, y): asm.Cell(1, 0) for y in range(16) for x in range(16)}
        self.assertEqual(asm.decode(asm.encode(cells)), cells)

    def test_empty_map(self):
        self.assertEqual(asm.encode({}), "AAAAAA==")
        self.assertEqual(asm.decode("AAAAAA=="), {})

    def test_invalid_inputs(self):
        for source in ("PLACE arrow 0 0 sideways", "PLACE unknown 0 0 up", "PLACE type_256 0 0 up", "PLACE arrow 524288 0 up", "FORMAT 1", "PLACE arrow 0 0 up extra", "PLACE arrow 0 0 up\nFORMAT 0"):
            with self.subTest(source=source), self.assertRaises(asm.MapError):
                asm.parse(source)
        with self.assertRaises(asm.MapError):
            asm.lower(asm.parse("PLACE arrow 0 0 up\nPLACE not 0 0 down"))

    def test_bad_saves(self):
        bad = [b"", b"\x00\x00", struct.pack("<HH", 1, 0), struct.pack("<HH", 0, 0) + b"x", struct.pack("<HH", 0, 1)]
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises(asm.MapError):
                asm.decode(base64.b64encode(raw).decode())
        with self.assertRaises(asm.MapError):
            asm.decode("not-base64!")


if __name__ == "__main__":
    unittest.main()
