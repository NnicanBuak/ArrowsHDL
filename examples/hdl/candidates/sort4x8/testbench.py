"""Physical 8-bit sorting checks against Python sorted(), including duplicates."""
import argparse
from itertools import permutations, product
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from physical_check import run_example

BOUNDARIES = (0, 1, 2, 127, 128, 129, 254, 255)


def vector(values):
    expected = sorted(values)  # Independent algorithm, including exact multiplicities.
    return {"inputs": {f"x{i}": value for i, value in enumerate(values)},
            "expect": {f"y{i}": value for i, value in enumerate(expected)}}


def vectors():
    # All pairs in both first-stage comparators; other words exercise their complements.
    for a, b in product(range(256), repeat=2):
        yield vector((a, b, 255 - a, 255 - b))
    for values in product(BOUNDARIES, repeat=4):
        yield vector(values)
    for values in ((0, 1, 128, 255), (1, 127, 128, 254), (2, 127, 129, 255)):
        for reordered in permutations(values):
            yield vector(reordered)
    for value in range(256):
        yield vector((value,) * 4)
        yield vector((value, 0, value, 255))
    for values in ((0, 0, 0, 0), (255, 255, 255, 255), (127, 128, 127, 128), (85, 170, 85, 170)):
        for word in range(4):
            for bit in range(8):
                changed = list(values)
                changed[word] ^= 1 << bit
                for case in (values, changed, values):
                    yield vector(case)
    rng = random.Random(408)
    for _ in range(8192):
        values = tuple(rng.randrange(256) for _ in range(4))
        yield vector(values)
        yield vector(tuple(255 - value for value in values))


def run(reuse=False):
    examples = [vector(values) for values in (
        (255, 2, 128, 7), (0, 255, 1, 254), (128, 127, 255, 0),
        (4, 4, 1, 4), (200, 200, 200, 200), (255, 128, 64, 0), (0, 64, 128, 255),
    )]
    coverage = {"oracle": "Python sorted() of unsigned bytes; exact values and multiplicities",
                "all_65536_value_pairs_in_first_stage": True,
                "boundary_cartesian_cases": len(BOUNDARIES) ** 4,
                "distinct_boundary_permutations": 72,
                "all_equal_and_repeated_values": 512,
                "single_bit_transition_vectors": 384,
                "random_and_complement_vectors": 16384,
                "all_2_pow_32_physical_inputs_exhausted": False}
    return run_example(HERE, "sort4x8", vectors(), examples, coverage, reuse)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--reuse", action="store_true", help="Проверить уже собранную карту с проверкой хешей")
    report = run(parser.parse_args().reuse)
    raise SystemExit(0 if report["passed"] else 1)
