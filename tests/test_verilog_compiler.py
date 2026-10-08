"""End-to-end tests: real Yosys, physical cells, native GraphDLC, independent expectations."""
from itertools import product
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from arrowasm import Cell, MapError, decode, encode
from arrow_layout import place
from mapdata import from_document, map_hash, read_map, to_document
from simulation import simulate
from test_harness import add_fixture, make_scenario, run_vectors
from verilog_compile import compile_file
from verilog_frontend import synthesize


class CompilerTests(unittest.TestCase):
    def test_half_adder_source_production_and_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            cells, manifest = compile_file(ROOT / "examples/hdl/half_adder/half_adder.v", "half_adder", folder)
            self.assertFalse(any(cell.type in (22, 23) for cell in cells.values()))
            self.assertEqual(read_map(folder / "half_adder.map.json"), cells)
            self.assertEqual(read_map(folder / "half_adder.save.txt"), cells)
            vectors = [{"inputs": {"i_bit1": a, "i_bit2": b}, "expect": {"o_sum": (a+b) % 2, "o_carry": (a+b) // 2}} for a, b in product((0, 1), repeat=2)]
            transitions = [v for before in vectors for after in vectors for v in (before, after)]
            original = dict(cells)
            test_cells, report = run_vectors(cells, manifest, vectors + transitions, folder, "half_adder")
            self.assertTrue(report["passed"], report["failures"])
            self.assertEqual(report["checked_samples"], 72)
            self.assertEqual(cells, original)
            self.assertEqual({key: cell for key, cell in test_cells.items() if cell.type not in (22, 23)}, cells)
            self.assertEqual(len(test_cells) - len(cells), 4)
            self.assertTrue(all(row["actual"] == row["expected"] for row in report["truth_table"]))
            # Wrong expectation must fail even though intermediate ticks are masked.
            wrong = [{"inputs": {"i_bit1": 0, "i_bit2": 0}, "expect": {"o_sum": 1, "o_carry": 0}}]
            failed = simulate(test_cells, make_scenario(manifest, wrong))
            self.assertFalse(failed["passed"])
            self.assertEqual(failed["failure_count"], 1)
            # A faulty physical AND -> OR must also be caught independently of Yosys.
            modified = dict(cells)
            key = next(key for key, cell in cells.items() if cell.type == 16)
            modified[key] = Cell(1, 1)
            changed = dict(manifest, map_hash=map_hash(modified))
            failed = simulate(add_fixture(modified, changed), make_scenario(changed, vectors))
            self.assertFalse(failed["passed"])
            with self.assertRaises(MapError):
                add_fixture(modified, manifest)
            with self.assertRaises(MapError):
                make_scenario(manifest, vectors, 1)

    def test_full_adder_table_and_every_transition(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            cells, manifest = compile_file(ROOT / "examples/hdl/full_adder/full_adder.v", "full_adder", folder)
            vectors = [{"inputs": {"i_bit1": a, "i_bit2": b, "i_carry": c}, "expect": {"o_sum": (a+b+c) % 2, "o_carry": (a+b+c) // 2}} for a, b, c in product((0, 1), repeat=3)]
            transitions = [v for before in vectors for after in vectors for v in (before, after)]
            _, report = run_vectors(cells, manifest, vectors + transitions, folder, "full_adder")
            self.assertTrue(report["passed"], report["failures"])
            self.assertEqual(report["checked_samples"], 272)
            self.assertFalse(report["verified_against_current_game"])

    def test_mux_bus_inversion_and_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "mixed.v"
            source.write_text("module mixed(input [1:0] a,b, input sel, output [1:0] y, output z,alias_z); assign y = sel ? a : b; assign z = ~a[0]; assign alias_z = z; endmodule", encoding="utf-8")
            cells, manifest = compile_file(source, "mixed", folder)
            vectors = [{"inputs": {"a": a, "b": b, "sel": s}, "expect": {"y": a if s else b, "z": 1-(a&1), "alias_z": 1-(a&1)}} for a,b,s in product(range(4), range(4), range(2))]
            _, report = run_vectors(cells, manifest, vectors, folder, "mixed")
            self.assertTrue(report["passed"], report["failures"])
            self.assertEqual(report["checked_samples"], 32 * 4)
            contacts = [tuple(entry["contact"]) for entries in manifest["outputs"].values() for entry in entries]
            self.assertEqual(len(contacts), len(set(contacts)))

    def test_constants_and_parameterized_vector(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "constants.v"
            source.write_text("module constants #(parameter W=2)(input [W-1:0] a, output [W-1:0] y, output zero,one); assign y = a; assign zero = 1'b0; assign one = 1'b1; endmodule", encoding="utf-8")
            cells, manifest = compile_file(source, "constants", folder)
            vectors = [{"inputs": {"a": a}, "expect": {"y": a, "zero": 0, "one": 1}} for a in range(4)]
            _, report = run_vectors(cells, manifest, vectors, folder, "constants")
            self.assertTrue(report["passed"], report["failures"])

    def test_reject_unsupported_and_undriven_verilog(self):
        cases = [
            "module bad(input clk,d, output reg y); always @(posedge clk) y<=d; endmodule",
            "module bad(input a, output y); assign y = 1'bx; endmodule",
            "module bad(input a, output y); assign #2 y=a; endmodule",
            "module bad(input a, output y); buf #(1) gate_delay(y,a); endmodule",
            "module bad #(parameter W=(1+1))(input a, output y); assign #(W) y=a; endmodule",
            "module bad(input a, output y); wire missing; assign y=missing; endmodule",
            "module bad(input a, output y); assign y=~y; endmodule",
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bad.v"
            for code in cases:
                source.write_text(code, encoding="utf-8")
                with self.subTest(code=code), self.assertRaises(MapError):
                    synthesize(source, "bad")

    def test_parameter_overrides_with_nested_expressions(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / 'configured.v'
            source.write_text('''module invert #(parameter W=(1+1))(input [W-1:0] a, output [W-1:0] y);
                assign y=~a; endmodule
                module configured(input [3:0] a, output [3:0] y);
                invert #(.W((2+2))) unit(a,y); endmodule''', encoding='utf-8')
            cells, manifest = compile_file(source, 'configured', folder)
            self.assertEqual(len(manifest['inputs']['a']), 4)
            vectors = [{'inputs': {'a': a}, 'expect': {'y': a ^ 15}} for a in range(16)]
            _, report = run_vectors(cells, manifest, vectors, folder, 'configured')
            self.assertTrue(report['passed'], report['failures'])

    def test_json_model_roundtrip_and_invalid_data(self):
        cells = {(-2, 3): Cell(255, 3, True), (0, 0): Cell(22, 1), (1, 0): Cell(23, 0)}
        self.assertEqual(from_document(to_document(cells)), cells)
        self.assertEqual(decode(encode(from_document(to_document(cells)))), cells)
        invalid = [
            {"schema": 2, "cells": []}, {"schema": 1, "cells": [], "typo": 1},
            {"schema": 1, "cells": [{"type": "arrow", "at": [[0,0],[0,0]]}]},
            {"schema": 1, "cells": [{"type": "arrow", "mirrored": 1, "at": [[0,0]]}]},
            {"schema": 1, "cells": [{"type": True, "at": [[0,0]]}]},
        ]
        for doc in invalid:
            with self.subTest(doc=doc), self.assertRaises(MapError):
                from_document(doc)

    def test_masks_must_include_a_real_check_and_cannot_mask_inputs(self):
        cells = {(0,0): Cell(22,1), (1,0): Cell(23,0)}
        valid = {"ticks": 2, "inputs": [{"at": [0,0], "values": [1,1]}], "expect": [{"at": [1,0], "values": [None,1]}]}
        report = simulate(cells, valid)
        self.assertTrue(report["passed"])
        self.assertEqual(report["checked_samples"], 1)
        for scenario in [dict(valid, expect=[{"at": [1,0], "values": [None,None]}]), dict(valid, inputs=[{"at": [0,0], "values": [None,1]}])]:
            with self.assertRaises(MapError):
                simulate(cells, scenario)

    def test_determinism_and_explicit_cell_limit(self):
        source = ROOT / "examples/hdl/half_adder/half_adder.v"
        first, _ = synthesize(source, "half_adder")
        second, _ = synthesize(source, "half_adder")
        self.assertEqual(first, second)
        self.assertEqual(place(first), place(second))
        with self.assertRaises(MapError):
            place(first, max_cells=3)


if __name__ == "__main__":
    unittest.main()
