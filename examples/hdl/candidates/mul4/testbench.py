"""All 256 products plus reverse/random order on a continuously running map."""
import argparse
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from physical_check import run_example


def vector(a, b):
    return {"inputs": {"a": a, "b": b}, "expect": {"product": a * b}}


def vectors():
    pairs = [(a, b) for a in range(16) for b in range(16)]
    for a, b in pairs + list(reversed(pairs)):
        yield vector(a, b)
    random.Random(404).shuffle(pairs)
    for a, b in pairs:
        yield vector(a, b)
    # Toggle each input bit at backgrounds that exercise carry propagation.
    for a, b in ((0, 0), (15, 0), (0, 15), (15, 15), (5, 10)):
        for bit in range(4):
            for changed in ((a, b), (a ^ (1 << bit), b), (a, b), (a, b ^ (1 << bit)), (a, b)):
                yield vector(*changed)


def run(reuse=False):
    examples = [vector(a, b) for a, b in ((0, 15), (1, 15), (2, 7), (5, 10), (13, 11), (15, 15), (15, 0))]
    return run_example(HERE, "mul4", vectors(), examples,
                       {"oracle": "Python integer a * b", "all_256_input_pairs": True,
                        "orders": ["ascending", "descending", "seeded_random"], "single_bit_transitions": True}, reuse)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--reuse", action="store_true", help="Проверить уже собранную карту с проверкой хешей")
    report = run(parser.parse_args().reuse)
    raise SystemExit(0 if report["passed"] else 1)
