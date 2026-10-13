"""Named-port testbench: Source/Target are added to a copy of the production map."""
from itertools import islice

from arrowshdl.arrowasm import Cell, MapError
from arrowshdl.arrow_layout import destinations, depth_of, edges
from arrowshdl.mapdata import map_hash
from arrowshdl.simulation import simulate


def add_fixture(cells, manifest):
    if map_hash(cells) != manifest["map_hash"]:
        raise MapError("Port metadata belongs to another map")
    test_cells = dict(cells)
    devices = {(d['direction'], tuple(d['at'])): d for d in manifest.get('io_devices', [])}
    for direction, kind in (("inputs", 22), ("outputs", 23)):
        for entries in manifest[direction].values():
            for entry in entries:
                if not {'fixture','contact','rotation'} <= entry.keys():
                    raise MapError('Physical port has no test fixture; bindings metadata is required')
                position, contact = tuple(entry["fixture"]), tuple(entry["contact"])
                device = devices.get((direction, position))
                if (position in test_cells and not device) or contact not in cells:
                    raise MapError(f"No free space for test port {position}")
                fixture = Cell(kind, entry["rotation"])
                if direction == 'outputs' and entry.get('sensor'):
                    sensor=entry['sensor']
                    at=tuple(sensor['at']);detector=Cell(5,sensor['rotation'])
                    front=next(destinations(at,detector))
                    behind=(2*at[0]-front[0],2*at[1]-front[1])
                    if (at in test_cells and not (device and test_cells[at]==detector)) or behind!=contact or front!=position:
                        raise MapError('Invalid independent output probe')
                    test_cells[at]=detector
                    test_cells[position]=fixture
                    continue
                if kind == 22:
                    if list(destinations(position, fixture)) != [contact]:
                        raise MapError("Test source must point toward the contact")
                    if any(position in destinations(key, cell) for key, cell in cells.items() if key != position):
                        raise MapError("Scheme feeds a signal back into the test source")
                elif position not in destinations(contact, cells[contact]):
                    raise MapError("Output contact does not point toward the receiver")
                test_cells[position] = fixture
    links = edges(test_cells)
    for entries in manifest["inputs"].values():
        for entry in entries:
            if links[tuple(entry["fixture"])] != [tuple(entry["contact"])]:
                raise MapError("Test source is connected to unexpected cells")
    for entries in manifest["outputs"].values():
        for entry in entries:
            sources = [key for key, targets in links.items() if tuple(entry["fixture"]) in targets]
            expected=tuple(entry['sensor']['at']) if entry.get('sensor') else tuple(entry['contact'])
            if sources != [expected]:
                raise MapError("Unexpected signal at test receiver")
    return test_cells


def make_scenario(manifest, vectors, settle_ticks=None, compressed=False):
    hold = manifest["settle_ticks"] if settle_ticks is None else settle_ticks
    if type(hold) is not int or hold < manifest["settle_ticks"]:
        raise MapError("Input hold time is shorter than the computed delay")
    ticks = hold * len(vectors)
    if not 0 < ticks <= 1_000_000:
        raise MapError("Scenario must contain between 1 and 1000000 ticks")
    for vector in vectors:
        if set(vector) != {"inputs", "expect"}:
            raise MapError("Test vector: expected inputs and expect")
        for category, key in (("inputs", "inputs"), ("outputs", "expect")):
            if set(vector[key]) != set(manifest[category]):
                raise MapError("Test vector must specify all inputs and outputs")
            for name, entries in manifest[category].items():
                value = vector[key][name]
                if type(value) is not int or not 0 <= value < 2 ** len(entries):
                    raise MapError(f"Port value {name} does not fit in {len(entries)} bits")
    inputs, expect = [], []
    for category, key, destination in (("inputs", "inputs", inputs), ("outputs", "expect", expect)):
        for name, entries in manifest[category].items():
            for bit_index, entry in enumerate(entries):
                values = []
                for vector in vectors:
                    bit = (vector[key][name] >> bit_index) & 1
                    if compressed:
                        values.append(bit)
                    else:
                        values.extend([bit] * hold if category == "inputs" else [None] * (hold - 1) + [bit])
                destination.append({"at": entry["fixture"], "values": values})
    scenario = {"ticks": ticks, "inputs": inputs, "expect": expect}
    if compressed:
        scenario["hold_ticks"] = hold
    return scenario


def run_vectors(cells, manifest, vectors, folder=None, stem=None, compressed=False):
    test_cells = add_fixture(cells, manifest)
    if depth_of(test_cells) > manifest["settle_ticks"]:
        raise MapError("Test fixture exceeds the computed settling time")
    scenario = make_scenario(manifest, vectors, compressed=compressed)
    report = simulate(test_cells, scenario, optimize_cycles=False)
    hold = manifest["settle_ticks"]
    measured = {tuple(trace["at"]): trace["values"] for trace in report["outputs"]}
    rows = []
    for i, vector in enumerate(vectors):
        sample = i if compressed else (i + 1) * hold - 1
        actual = {name: sum(measured[tuple(entry["fixture"])][sample] << bit for bit, entry in enumerate(entries)) for name, entries in manifest["outputs"].items()}
        rows.append({"inputs": vector["inputs"], "expected": vector["expect"], "actual": actual, "passed": actual == vector["expect"]})
    report.update({"vectors": len(vectors), "settle_ticks": hold, "truth_table": rows, "production_cells": len(cells), "fixture_cells": len(test_cells) - len(cells),
                   "production_map_hash":map_hash(cells)})
    return test_cells, report


def run_vector_batches(cells, manifest, vectors, folder=None, stem=None, batch_size=4096, progress=None):
    """Exhaustive physical simulation without materializing per-tick JSON arrays.

Each batch starts from reset, then keeps state across its successive vectors.
    The same in-memory fixture map is executed for every batch.
    """
    test_cells = add_fixture(cells, manifest)
    if depth_of(test_cells) > manifest["settle_ticks"]:
        raise MapError("Test fixture exceeds the computed settling time")
    hold = manifest["settle_ticks"]
    if type(batch_size) is not int or batch_size < 1:
        raise MapError("Batch size must be positive")
    batch_size = min(batch_size, 1_000_000 // hold)
    if batch_size == 0:
        raise MapError("Delay is too large for batch testing")
    summary = {"passed": True, "vectors": 0, "checked_samples": 0, "ticks": 0,
               "batches": 0, "failure_count": 0, "failures": [], "settle_ticks": hold,
               "production_cells": len(cells), "fixture_cells": len(test_cells) - len(cells),
               "profile": manifest["profile"], "map_hash": manifest["map_hash"],
               "verified_against_current_game": False}
    iterator = iter(vectors)
    while batch := list(islice(iterator, batch_size)):
        report = simulate(test_cells, make_scenario(manifest, batch, compressed=True), optimize_cycles=False)
        summary["passed"] &= report["passed"]
        summary["vectors"] += len(batch)
        summary["checked_samples"] += report["checked_samples"]
        summary["failure_count"] += report["failure_count"]
        for failure in report["failures"]:
            if len(summary["failures"]) < 100:
                summary["failures"].append(dict(failure, tick=summary["ticks"] + failure["tick"]))
        summary["ticks"] += report["ticks"]
        summary["batches"] += 1
        if progress:
            progress(summary)
    if not summary["vectors"]:
        raise MapError("No test vectors")
    return summary
