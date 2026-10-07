"""Size regression and physical arithmetic checks for the generic optimizer."""
from itertools import product
from pathlib import Path
import random
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from arrowasm import Cell, MapError
from arrow_layout import place
from mapdata import read_map
from simulation import simulate
from test_harness import add_fixture, make_scenario, run_vectors, run_vector_batches
from verilog_compile import compile_file
from verilog_frontend import synthesize


def adder_vector(a, b, ci):
    total = a + b + ci
    return {"inputs": {"a": a, "b": b, "cin": ci}, "expect": {"sum": total & 255, "cout": total >> 8}}


class CompactTests(unittest.TestCase):
    def test_unchanged_graph_size_and_exhaustive_adder8(self):
        graph, _ = synthesize(ROOT / "examples/hdl/adder8/adder8.v", "adder8")
        original = repr(graph)
        cells, compact = place(graph)
        sparse, baseline = place(graph, layout="sparse")
        self.assertEqual(repr(graph), original)
        self.assertLessEqual(len(cells), 100)
        self.assertLess(compact["bounds"]["area"], 200)
        self.assertLess(compact["settle_ticks"], 40)
        for category in ("inputs","outputs"):
            for entries in compact[category].values():
                if len(entries)<2:
                    continue
                coords=[e["contact"] for e in entries]
                steps=[(b[0]-a[0],b[1]-a[1]) for a,b in zip(coords,coords[1:])]
                self.assertEqual(len(set(steps)),1)
                dx,dy=steps[0]
                self.assertTrue((dx==0) != (dy==0))
                self.assertLessEqual(abs(dx)+abs(dy),2)
        self.assertLess(len(cells), len(sparse) / 20)
        self.assertLess(compact["bounds"]["area"], baseline["bounds"]["area"] / 50)
        self.assertEqual(compact["logic_nodes"], baseline["logic_nodes"])
        self.assertFalse(any(c.type in (22,23) for c in cells.values()))
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            vectors = (adder_vector(a,b,ci) for a,b,ci in product(range(256),range(256),range(2)))
            report = run_vector_batches(cells, compact, vectors, folder, "adder8")
            self.assertTrue(report["passed"], report["failures"])
            self.assertEqual(report["vectors"], 131072)
            self.assertEqual(report["checked_samples"], 131072 * 9)
            self.assertEqual(len(read_map(folder / "adder8.test.save.txt")) - len(cells), 26)
            # The baseline is also a physical circuit, not just a count estimate.
            _, report = run_vectors(sparse, baseline, [adder_vector(255,0,1),adder_vector(0,0,0)], folder / "baseline", "adder8", compressed=True)
            self.assertTrue(report["passed"], report["failures"])

    def test_hdl_plus_and_rapid_carry_transitions(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "arithmetic.v"
            source.write_text("module arithmetic(input [7:0] a,b,input cin,output [7:0] sum,output cout); assign {cout,sum}={1'b0,a}+{1'b0,b}+cin; endmodule", encoding="utf-8")
            cells, manifest = compile_file(source, "arithmetic", folder)
            rng = random.Random(414)
            vectors = [adder_vector(255,0,ci) for ci in (0,1,0,1,0)]
            vectors += [adder_vector(rng.randrange(256),rng.randrange(256),rng.randrange(2)) for _ in range(300)]
            _, report = run_vectors(cells, manifest, vectors, folder, "arithmetic", compressed=True)
            self.assertTrue(report["passed"], report["failures"])
            self.assertEqual(report["checked_samples"], len(vectors) * 9)

    def test_fanout_and_output_aliases_through_crossings(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "fanout.v"
            source.write_text("module fanout(input [3:0] a,b,input sel,output [3:0] p,q,r,output [7:0] alias_bus); assign p=a^b; assign q=a&{4{sel}}; assign r=b|{4{sel}}; assign alias_bus={p,p}; endmodule", encoding="utf-8")
            cells, manifest = compile_file(source, "fanout", folder)
            vectors = [{"inputs":{"a":a,"b":b,"sel":s},"expect":{"p":a^b,"q":a if s else 0,"r":15 if s else b,"alias_bus":(a^b)*17}} for a,b,s in product(range(16),range(16),range(2))]
            _, report = run_vectors(cells, manifest, vectors, folder, "fanout", compressed=True)
            self.assertTrue(report["passed"], report["failures"])
            self.assertEqual(report["checked_samples"], len(vectors) * 20)

    def test_compressed_scenario_matches_tick_trace_and_rejects_bad_hold(self):
        cells = {(0,0):Cell(22,1),(1,0):Cell(1,1),(2,0):Cell(23,0)}
        samples = [1,0,1,1,0,0]
        compressed = {"ticks":24,"hold_ticks":4,"inputs":[{"at":[0,0],"values":samples}],"expect":[{"at":[2,0],"values":samples}]}
        full = {"ticks":24,"inputs":[{"at":[0,0],"values":[b for b in samples for _ in range(4)]}],"expect":[{"at":[2,0],"values":[v for b in samples for v in (None,None,None,b)]}]}
        a, b = simulate(cells, compressed), simulate(cells, full)
        self.assertTrue(a["passed"] and b["passed"])
        self.assertEqual(a["checked_samples"], b["checked_samples"])
        self.assertEqual(a["outputs"][0]["values"], b["outputs"][0]["values"][3::4])
        for hold in (0,5,25):
            with self.subTest(hold=hold), self.assertRaises(MapError):
                simulate(cells, dict(compressed,hold_ticks=hold))
        wrong = dict(compressed,expect=[{"at":[2,0],"values":[0]*6}])
        self.assertFalse(simulate(cells, wrong)["passed"])

    def test_deterministic_generic_layout_and_validated_options(self):
        graph, _ = synthesize(ROOT / "examples/hdl/adder8/adder8.v", "adder8")
        first = place(graph)
        self.assertEqual(first, place(graph))
        add_fixture(*first)
        with self.assertRaises(MapError):
            place(graph,layout="typo")
        with self.assertRaises(MapError):
            place(graph,max_cells=50)


if __name__ == "__main__":
    unittest.main()
