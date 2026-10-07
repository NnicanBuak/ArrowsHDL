"""Compile a composed HDL example and check exported arrow maps independently."""
import hashlib
import json
from pathlib import Path
import sys
import time

PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT / "src"))
from arrowasm import MapError
from arrow_layout import bounds_of, depth_of, edges
from mapdata import map_hash, read_map, write_json
from map_preview import render
from test_harness import run_vector_batches, run_vectors
from verilog_compile import compile_file


def render_core(cells, manifest, path):
    """Visual extraction only: retain exact positions and internal connections."""
    gates = {tuple(gate["at"]) for gate in manifest["gate_labels"] if not gate["id"].startswith("port:")}
    links, reverse = edges(cells), {key: [] for key in cells}
    for source, targets in links.items():
        for target in targets:
            reverse[target].append(source)

    def reached(starts, graph):
        seen, pending = set(starts), list(starts)
        while pending:
            for target in graph[pending.pop()]:
                if target not in seen:
                    seen.add(target)
                    pending.append(target)
        return seen

    constants = {key for key, cell in cells.items() if cell.type == 2}
    selected = reached(gates | constants, links) & reached(gates, reverse)
    core = {key: cells[key] for key in selected}
    metrics = manifest["logic_core"]
    if len(core) != metrics["cells"] or bounds_of(core) != metrics["bounds"] or depth_of(core) != metrics["ticks"]:
        raise MapError("Изображение ядра не соответствует метрикам компилятора")
    view = dict(manifest, top=f"{manifest['top']} · ядро, внешние трассы скрыты",
                cells=len(core), settle_ticks=metrics["ticks"], inputs={}, outputs={},
                gate_labels=[gate for gate in manifest["gate_labels"] if tuple(gate["at"]) in selected])
    render(core, view, path)


def run_example(here, stem, vectors, examples, coverage, reuse=False):
    source, folder = here / f"{stem}.v", here / "build"
    started = time.perf_counter()
    if reuse:
        manifest = json.loads((folder / f"{stem}.build.json").read_text(encoding="utf-8"))
        cells = read_map(folder / f"{stem}.save.txt")
        if manifest["source_sha256"] != hashlib.sha256(source.read_bytes()).hexdigest():
            raise MapError("Сохранение скомпилировано из другого исходника")
        if manifest["logic_sha256"] != hashlib.sha256((folder / f"{stem}.logic.json").read_bytes()).hexdigest():
            raise MapError("Граф логики изменился после компиляции")
        if map_hash(cells) != manifest["map_hash"]:
            raise MapError("Сохранение не соответствует описанию портов")
    else:
        cells, manifest = compile_file(source, stem, folder)
    if read_map(folder / f"{stem}.map.json") != cells:
        raise MapError("JSON и Base64 описывают разные карты")
    if any(cell.type in (22, 23) for cell in cells.values()):
        raise MapError("Тестовые источники/приёмники попали в обычную карту")
    print(f"{stem}: compiled {len(cells)} arrows; core={manifest['logic_core']['cells']}; hold={manifest['settle_ticks']}", flush=True)
    write_json(folder / f"{stem}.examples.json", {"vectors": examples, "coverage": coverage})
    _, report = run_vectors(cells, manifest, examples, folder, stem, compressed=True)
    exhaustive = run_vector_batches(
        cells, manifest, vectors, folder, stem,
        progress=lambda summary: print(f"{stem}: {summary['vectors']} vectors, failures={summary['failure_count']}", flush=True),
    )
    report["coverage"] = coverage
    report["physical_checks"] = exhaustive
    report["passed"] &= exhaustive["passed"]
    report["test_run_seconds"] = round(time.perf_counter() - started, 3)
    report["source_sha256"] = manifest["source_sha256"]
    write_json(folder / f"{stem}.report.json", report)
    render(read_map(folder / f"{stem}.save.txt"), manifest, folder / f"{stem}.preview.png")
    render(read_map(folder / f"{stem}.test.save.txt"), manifest, folder / f"{stem}.test.preview.png", report, report["truth_table"])
    render_core(read_map(folder / f"{stem}.save.txt"), manifest, folder / f"{stem}.core.preview.png")
    print(json.dumps({"top": stem, "passed": report["passed"], "production_cells": len(cells),
                      "logic_core": manifest["logic_core"], "settle_ticks": manifest["settle_ticks"],
                      "vectors": exhaustive["vectors"], "bit_checks": exhaustive["checked_samples"],
                      "fixture_cells": report["fixture_cells"]}, ensure_ascii=False), flush=True)
    return report
