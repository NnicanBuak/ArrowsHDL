"""Compare the actual GraphDLC engine to a simple synchronous grid oracle."""
from pathlib import Path
import importlib.util
import json
import random
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("arrowasm_simtests", ROOT / "src/arrowasm.py")
asm = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = asm
spec.loader.exec_module(asm)


def oracle(cells, scenario):
    # Deliberately walks coordinates each tick, independently of the optimized graph.
    states = {key: 0 for key in cells}
    ports = {tuple(p["at"]): p["values"] for p in scenario.get("inputs", [])}
    outputs = {tuple(p["at"]): [] for p in scenario["expect"]}
    paths = {6: [(0,-1),(0,1)], 7: [(0,-1),(1,0)], 8: [(0,-1),(1,0),(-1,0)], 10: [(0,-2)], 11: [(1,-1)], 12: [(0,-1),(0,-2)], 13: [(0,-2),(1,0)], 14: [(0,-1),(1,-1)]}

    def offset(key, cell, vector):
        dx, dy = vector
        if cell.mirrored:
            dx = -dx
        for _ in range(cell.rotation):
            dx, dy = -dy, dx
        return key[0] + dx, key[1] + dy

    for tick in range(scenario["ticks"]):
        counts = dict.fromkeys(cells, 0)
        blocked = set()
        for key, cell in cells.items():
            if states[key] != 1:
                continue
            if cell.type == 3:
                blocked.add(offset(key, cell, (0,-1)))
                continue
            if cell.type in (23,25):
                continue
            vectors = [(0,-1),(1,0),(0,1),(-1,0)] if cell.type in (2,9,21) else paths.get(cell.type, [(0,-1)])
            for vector in vectors:
                target = offset(key, cell, vector)
                if target in counts:
                    counts[target] += 1
        next_states = {}
        for key, cell in cells.items():
            count, old, type_id = counts[key], states[key], cell.type
            if key in blocked or type_id == 25:
                value = 0
            elif type_id == 2:
                value = 1
            elif type_id == 4:
                value = 1 if old == 2 or (old == 1 and count) else (2 if count else 0)
            elif type_id == 5:
                value = int(states.get(offset(key, cell, (0,1)), 0) != 0)
            elif type_id == 9:
                value = 1 if old == 0 else 2
            elif type_id == 15:
                value = int(count == 0)
            elif type_id == 16:
                value = int(count >= 2)
            elif type_id == 17:
                value = count % 2
            elif type_id == 18:
                value = int(count >= 2) if count else old
            elif type_id == 19:
                value = 1 - old if count else old
            elif type_id == 20:
                raise ValueError("Random is checked separately for seeded reproducibility")
            elif type_id == 21:
                value = 0
            elif type_id == 22:
                value = int(count > 0 or ports.get(key, [0] * scenario["ticks"])[tick])
            else:
                value = int(count > 0)
            next_states[key] = value
        states = next_states
        for key in outputs:
            outputs[key].append(int(states[key] == 1))
    return outputs


def execute(cells, scenario, optimized=True):
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        (root / "map.txt").write_text(asm.encode(cells), encoding="utf-8")
        (root / "case.json").write_text(json.dumps(scenario), encoding="utf-8")
        cmd = [sys.executable, str(ROOT / "src/logicarrows.py"), "--save", str(root / "map.txt"), "--test", str(root / "case.json")]
        if not optimized:
            cmd.append("--no-cycles")
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=30)
        return result, json.loads(result.stdout) if result.stdout else None


class SimulatorTests(unittest.TestCase):
    def test_read_only_cell_observations(self):
        cells={(0,0):asm.Cell(22,1),(1,0):asm.Cell(1,1),(2,0):asm.Cell(23,0)}
        signal=[1,1,1,0,0,1,0,0]
        case={'ticks':len(signal),'inputs':[{'at':[0,0],'values':signal}],
              'expect':[], 'observe':[[0,0],[1,0],[2,0]]}
        expected=oracle(cells,dict(case,expect=[{'at':p} for p in case['observe']]))
        result,report=execute(cells,case)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIsNone(report['passed'])
        self.assertEqual(report['checked_samples'],0)
        self.assertEqual({tuple(p['at']):p['values'] for p in report['observations']},expected)
        checked=dict(case,expect=[{'at':[2,0],'values':expected[2,0]}])
        _,with_observation=execute(cells,checked)
        _,without_observation=execute(cells,{k:v for k,v in checked.items() if k!='observe'})
        self.assertEqual(with_observation['outputs'],without_observation['outputs'])
        self.assertEqual(with_observation['checked_samples'],len(signal))
        for bad in ([[99,99]],[[1,0],[1,0]]):
            result,_=execute(cells,dict(case,observe=bad))
            self.assertEqual(result.returncode,2)

    def verify_oracle(self, cells, scenario, optimized=True):
        expected = oracle(cells, scenario)
        scenario = dict(scenario, expect=[{"at": list(key), "values": values} for key, values in expected.items()])
        result, report = execute(cells, scenario, optimized)
        self.assertEqual(result.returncode, 0, (result.stderr, report))
        self.assertTrue(report["passed"])
        return report

    def test_identity_and_failure_exit(self):
        cells = asm.lower(asm.parse((ROOT / "examples/identity.l.asm").read_text(encoding="utf-8")))
        scenario = json.loads((ROOT / "examples/identity.test.json").read_text())
        result, report = execute(cells, scenario)
        self.assertEqual(result.returncode, 0, (result.stderr, report))
        scenario["expect"][0]["values"][2] = 0
        result, report = execute(cells, scenario)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report["failures"], [{"tick": 3, "at": [2,0], "expected": 0, "actual": 1}])

    def test_ring_optimization(self):
        cells = asm.lower(asm.parse((ROOT / "examples/ring.l.asm").read_text(encoding="utf-8")))
        scenario = json.loads((ROOT / "examples/ring.test.json").read_text())
        optimized = self.verify_oracle(cells, scenario)
        plain = self.verify_oracle(cells, scenario, False)
        self.assertEqual(optimized["optimized_cycles"], 1)
        self.assertEqual(plain["optimized_cycles"], 0)
        self.assertEqual(optimized["outputs"], plain["outputs"])

    def test_ring_write_clear_and_xor(self):
        rng = random.Random(845)
        original = asm.lower(asm.parse((ROOT / "examples/ring.l.asm").read_text(encoding="utf-8")))
        for mode in (1, 3, 17):
            cells = dict(original)
            if mode == 3:
                cells[(1,-1)] = asm.Cell(3,2)
            elif mode == 17:
                cells[(1,0)] = asm.Cell(17,1)
            scenario = {"ticks": 80, "inputs": [{"at": [1,-2], "values": [rng.randrange(2) for _ in range(80)]}, {"at": [3,0], "values": [rng.randrange(2) for _ in range(80)]}], "expect": [{"at": [4,1]}]}
            with self.subTest(mode=mode):
                fast = self.verify_oracle(cells, scenario)
                slow = self.verify_oracle(cells, scenario, False)
                self.assertGreaterEqual(fast["optimized_cycles"], 1)
                self.assertEqual(fast["outputs"], slow["outputs"])

    def test_input_port_not_bypassed_by_ring_optimizer(self):
        cells = asm.lower(asm.parse((ROOT / "examples/ring.l.asm").read_text(encoding="utf-8")))
        del cells[(1,-2)]
        cells[(1,-1)] = asm.Cell(22,2)
        scenario = {"ticks": 20, "inputs": [{"at": [1,-1], "values": [1]+[0]*19}, {"at": [3,0], "values": [1]*20}], "expect": [{"at": [4,1]}]}
        report = self.verify_oracle(cells, scenario)
        self.assertEqual(report["optimized_cycles"], 0)

    def test_seeded_randomizer_is_reproducible(self):
        cells = {(0,0): asm.Cell(22,1), (1,0): asm.Cell(20,1), (2,0): asm.Cell(23,0)}
        scenario = {"ticks": 70, "seed": 3451, "inputs": [{"at": [0,0], "values": [1]*70}], "expect": [{"at": [2,0], "values": [0]*70}]}
        first_result, first = execute(cells, scenario)
        second_result, second = execute(cells, scenario)
        self.assertIn(first_result.returncode, (0,1))
        self.assertEqual(first_result.returncode, second_result.returncode)
        self.assertEqual(first["outputs"], second["outputs"])
        self.assertEqual(set(first["outputs"][0]["values"]), {0,1})

    def test_random_grid_against_scalar_simulation(self):
        rng = random.Random(490)
        kinds = [v for v in range(1,26) if v != 20]
        for case in range(4):
            cells = {(x-4,y-4): asm.Cell(rng.choice(kinds), rng.randrange(4), bool(rng.randrange(2))) for y in range(9) for x in range(9)}
            cells[(-4,-4)] = asm.Cell(22,1)
            cells[(4,4)] = asm.Cell(23,0)
            inputs = [{"at": list(key), "values": [rng.randrange(2) for _ in range(40)]} for key,c in cells.items() if c.type == 22]
            outputs = [{"at": list(key)} for key,c in cells.items() if c.type == 23]
            with self.subTest(case=case):
                self.verify_oracle(cells, {"ticks": 40, "inputs": inputs, "expect": outputs})

    def test_delay_detector_and_blocker(self):
        for type_id in (1,3,4,5,9,15,16,17,18,19,24,25):
            cells = {(0,0): asm.Cell(22,1), (1,0): asm.Cell(type_id,1), (2,0): asm.Cell(23,0), (1,-1): asm.Cell(22,2)}
            scenario = {"ticks": 12, "inputs": [{"at": [0,0], "values": [1,0,1,1,1,0,0,1,0,0,0,0]}, {"at": [1,-1], "values": [0,1,1,0,1,0,0,0,0,0,0,0]}], "expect": [{"at": [2,0]}]}
            with self.subTest(type_id=type_id):
                self.verify_oracle(cells, scenario)

    def test_no_silent_unknown_elements_or_invalid_tests(self):
        cells = {(0,0): asm.Cell(22,1), (1,0): asm.Cell(23,0)}
        scenario = {"ticks": 2, "inputs": [{"at": [0,0], "values": [1,0]}], "expect": [{"at": [1,0], "values": [0,1]}]}
        for bad in ({**scenario, "expect": []}, {**scenario, "ticks": 3}, {**scenario, "typo": 1}):
            result, report = execute(cells, bad)
            self.assertEqual(result.returncode, 2)
            self.assertIsNone(report)
            self.assertIn("Ошибка:", result.stderr)
        result, report = execute({**cells, (10,10): asm.Cell(255,0)}, scenario)
        self.assertEqual(result.returncode, 2)
        self.assertIsNone(report)
        self.assertIn("Неподдерживаемый элемент", result.stderr)


if __name__ == "__main__":
    unittest.main()
