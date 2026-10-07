"""Named-port testbench: Source/Target are added to a copy of the production map."""
from itertools import islice
from pathlib import Path

from arrowasm import Cell, MapError
from arrow_layout import destinations, depth_of, edges
from mapdata import map_hash, read_map, write_json, write_map
from simulation import simulate


def add_fixture(cells, manifest):
    if map_hash(cells) != manifest["map_hash"]:
        raise MapError("Описание портов относится к другой карте")
    test_cells = dict(cells)
    for direction, kind in (("inputs", 22), ("outputs", 23)):
        for entries in manifest[direction].values():
            for entry in entries:
                position, contact = tuple(entry["fixture"]), tuple(entry["contact"])
                if position in test_cells or contact not in cells:
                    raise MapError(f"Нет свободного места для тестового порта {position}")
                fixture = Cell(kind, entry["rotation"])
                if kind == 22:
                    if list(destinations(position, fixture)) != [contact]:
                        raise MapError("Источник теста должен быть направлен на контакт")
                    if any(position in destinations(key, cell) for key, cell in cells.items()):
                        raise MapError("Схема подаёт сигнал обратно на тестовый источник")
                elif position not in destinations(contact, cells[contact]):
                    raise MapError("Выходной контакт не направлен на приёмник")
                test_cells[position] = fixture
    links = edges(test_cells)
    for entries in manifest["inputs"].values():
        for entry in entries:
            if links[tuple(entry["fixture"])] != [tuple(entry["contact"])]:
                raise MapError("Тестовый источник соединён с посторонними клетками")
    for entries in manifest["outputs"].values():
        for entry in entries:
            sources = [key for key, targets in links.items() if tuple(entry["fixture"]) in targets]
            if sources != [tuple(entry["contact"])]:
                raise MapError("Посторонний сигнал на тестовом приёмнике")
    return test_cells


def make_scenario(manifest, vectors, settle_ticks=None, compressed=False):
    hold = manifest["settle_ticks"] if settle_ticks is None else settle_ticks
    if type(hold) is not int or hold < manifest["settle_ticks"]:
        raise MapError("Время удержания входов меньше рассчитанной задержки")
    ticks = hold * len(vectors)
    if not 0 < ticks <= 1_000_000:
        raise MapError("Сценарий должен содержать от 1 до 1000000 тактов")
    for vector in vectors:
        if set(vector) != {"inputs", "expect"}:
            raise MapError("Тестовый вектор: inputs и expect")
        for category, key in (("inputs", "inputs"), ("outputs", "expect")):
            if set(vector[key]) != set(manifest[category]):
                raise MapError("Тестовый вектор должен задать все входы и выходы")
            for name, entries in manifest[category].items():
                value = vector[key][name]
                if type(value) is not int or not 0 <= value < 2 ** len(entries):
                    raise MapError(f"Значение порта {name} не помещается в {len(entries)} бит")
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


def run_vectors(cells, manifest, vectors, folder: Path, stem: str, compressed=False):
    test_cells = add_fixture(cells, manifest)
    if depth_of(test_cells) > manifest["settle_ticks"]:
        raise MapError("Тестовая обвязка превышает рассчитанный срок установления")
    scenario = make_scenario(manifest, vectors, compressed=compressed)
    write_map(folder, stem + ".test", test_cells)
    write_json(folder / f"{stem}.scenario.json", scenario)
    # Execute the exported/imported cells, rather than the Boolean synthesis graph.
    imported = read_map(folder / f"{stem}.test.save.txt")
    if imported != test_cells or read_map(folder / f"{stem}.test.map.json") != test_cells:
        raise MapError("Экспорт изменил тестовую карту")
    report = simulate(imported, scenario, optimize_cycles=False)
    hold = manifest["settle_ticks"]
    measured = {tuple(trace["at"]): trace["values"] for trace in report["outputs"]}
    rows = []
    for i, vector in enumerate(vectors):
        sample = i if compressed else (i + 1) * hold - 1
        actual = {name: sum(measured[tuple(entry["fixture"])][sample] << bit for bit, entry in enumerate(entries)) for name, entries in manifest["outputs"].items()}
        rows.append({"inputs": vector["inputs"], "expected": vector["expect"], "actual": actual, "passed": actual == vector["expect"]})
    report.update({"vectors": len(vectors), "settle_ticks": hold, "truth_table": rows, "production_cells": len(cells), "fixture_cells": len(test_cells) - len(cells)})
    write_json(folder / f"{stem}.report.json", report)
    return test_cells, report


def run_vector_batches(cells, manifest, vectors, folder: Path, stem: str, batch_size=4096, progress=None):
    """Exhaustive physical simulation without materializing per-tick JSON arrays.

Each batch starts from reset, then keeps state across its successive vectors.
The same exported/imported fixture map is executed for every batch.
    """
    test_cells = add_fixture(cells, manifest)
    if depth_of(test_cells) > manifest["settle_ticks"]:
        raise MapError("Тестовая обвязка превышает рассчитанный срок установления")
    write_map(folder, stem + ".test", test_cells)
    imported = read_map(folder / f"{stem}.test.save.txt")
    if imported != test_cells or read_map(folder / f"{stem}.test.map.json") != test_cells:
        raise MapError("Экспорт изменил тестовую карту")
    hold = manifest["settle_ticks"]
    if type(batch_size) is not int or batch_size < 1:
        raise MapError("Размер пакета должен быть положительным")
    batch_size = min(batch_size, 1_000_000 // hold)
    if batch_size == 0:
        raise MapError("Слишком большая задержка для пакетного теста")
    summary = {"passed": True, "vectors": 0, "checked_samples": 0, "ticks": 0,
               "batches": 0, "failure_count": 0, "failures": [], "settle_ticks": hold,
               "production_cells": len(cells), "fixture_cells": len(test_cells) - len(cells),
               "profile": manifest["profile"], "map_hash": manifest["map_hash"],
               "verified_against_current_game": False}
    iterator = iter(vectors)
    while batch := list(islice(iterator, batch_size)):
        report = simulate(imported, make_scenario(manifest, batch, compressed=True), optimize_cycles=False)
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
        raise MapError("Нет тестовых векторов")
    write_json(folder / f"{stem}.exhaustive.report.json", summary)
    return summary
