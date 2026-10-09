"""Eight autonomous logic oscillators -> encoder-selected MUX8 -> 64-bit display."""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from arrowasm import Cell, disassemble
from arrow_layout import bounds_of, destinations, edges
from mapdata import map_hash, read_map, write_json, write_map

STEM = "loop_mux8"
MUX = PROJECT / "examples/hdl/multiplexer/mux8/build"
REQUESTS = [(-32, 24 + 4 * i) for i in range(8)]
LATCHES = [(-27, 25 + 4 * i) for i in range(8)]
CODE = [(-17, 23), (-13, 23), (-9, 23)]
DISPLAY = [(x, 18) for x in range(14, 78)]
OUTPUT = DISPLAY[0]
WIDTHS = (2, 3, 4, 6, 8, 10, 14, 18)


def build():
    mux_meta = json.loads((MUX / "mux8.build.json").read_text(encoding="utf-8"))
    cells = read_map(MUX / "mux8.save.txt")
    if map_hash(cells) != mux_meta["map_hash"]:
        raise ValueError("MUX8 save and manifest differ")
    expected_inputs = [(4, y) for y in (5, 6, 8, 9, 11, 12, 14, 15)]
    if [tuple(p["contact"]) for p in mux_meta["inputs"]["data"]] != expected_inputs:
        raise ValueError("MUX8 data contact layout changed")
    if [tuple(p["contact"]) for p in mux_meta["inputs"]["sel"]] != [(5, 15), (8, 15), (11, 15)]:
        raise ValueError("MUX8 select contact layout changed")
    if tuple(mux_meta["outputs"]["y"][0]["contact"]) != (13, 15):
        raise ValueError("MUX8 output contact layout changed")

    original = dict(cells)
    regions = {"mux8": set(cells), "oscillators": set(), "channels": set(),
               "display": set(), "encoder": set(), "controls": set()}

    def add(position, kind, rotation, region, mirrored=False):
        if position in cells:
            raise ValueError(f"Collision at {position}")
        cells[position] = Cell(kind, rotation, mirrored)
        regions[region].add(position)

    # Each rectangular ring has one inversion and starts from zero by itself.
    # Its exact period is twice its perimeter: 4*width+8 simulation ticks.
    channel_columns = [-26 + 3 * i for i in range(8)]
    generator_outputs = []
    for i, width in enumerate(WIDTHS):
        right, top = -30, -64 + 8 * i
        left, bottom = right - width, top + 2
        add((left, top), 15, 1, "oscillators")
        for x in range(left + 1, right):
            add((x, top), 1, 1, "oscillators")
        add((right, top), 7, 1, "oscillators")
        add((right, top + 1), 1, 2, "oscillators")
        add((right, bottom), 1, 3, "oscillators")
        for x in range(right - 1, left, -1):
            add((x, bottom), 1, 3, "oscillators")
        add((left, bottom), 1, 0, "oscillators")
        add((left, top + 1), 1, 0, "oscillators")
        generator_outputs.append((right, top))
        col, dest_y = channel_columns[i], expected_inputs[i][1]
        add((col, top), 1, 2, "channels")
        for y in range(top + 1, dest_y):
            add((col, y), 1, 2, "channels")
        add((col, dest_y), 1, 1, "channels")
    # The eight downward wires remain isolated at horizontal crossings.
    def horizontal(start, stop, y, omit_start=False):
        x = start + int(omit_start)
        while x < stop:
            if (x, y) in cells:
                raise ValueError(f"Horizontal routing conflict at {(x,y)}")
            jump = x + 1 < stop and (x + 1, y) in cells
            if jump and cells[x + 1, y].rotation != 2:
                raise ValueError(f"Cannot cross cell {(x+1,y)}")
            add((x, y), 10 if jump else 1, 1, "channels")
            x += 2 if jump else 1
        if x != stop:
            raise ValueError("Jump overshot the destination")
    for i, (_, y) in enumerate(generator_outputs):
        horizontal(-29, channel_columns[i], y)
        horizontal(channel_columns[i], 4, expected_inputs[i][1], omit_start=True)

    # The MUX produces one bit. Each successive arrow holds its previous tick.
    # Splitting down exposes the 64 most recent bits as a physical pixel strip.
    reference = read_map(HERE / 'reference/zero_gate.original.save.txt')
    for (x,y), cell in reference.items():
        add((x+5,y+16),cell.type,cell.rotation,'display',cell.mirrored)

    # Crosspoint encoder: request i branches into code bits set in i.
    # Collectors jump over the horizontal rows and merge below the branch.
    columns = (-16, -12, -8)
    for i, fixture in enumerate(REQUESTS):
        y = fixture[1]
        add(fixture, 24, 1, "controls")
        # Raw and one-tick-old inverted raw form a rising-edge pulse.
        add((-31,y),14,2,'controls',True)
        add((-31,y+1),15,1,'controls')
        add((-30,y+1),16,1,'controls')
        add((-29,y+1),19,1,'controls')
        add((-28,y+1),7,0,'controls')
        add((-28,y),1,1,'controls')
        add((-27,y),1,1,'controls')
        add((-26,y),7,1,'encoder')
        if i<7:
            add((-26,y+1),1,2,'encoder')
            add((-26,y+2),1,2,'encoder')
            add((-26,y+3),7,1,'encoder')
        # Earlier active rows block every later row before it reaches code bits.
        if i:
            for x in range(-25,-19):
                add((x,y-1),1,1,'encoder')
        add((-19,y-1),3,2,'encoder')
        for x in range(-25, -6):
            branch = x in columns and bool(i & (1 << columns.index(x)))
            add((x, y), 7 if branch else 1, 0 if branch else 1, "encoder")
    for bit, col in enumerate(columns):
        for y in range(23, 52):
            if y >= 24 and (y - 24) % 4 == 0:
                continue
            if y == 23:
                add((col, y), 7, 0, "encoder", mirrored=True)
            else:
                add((col, y), 10 if (y - 25) % 4 == 0 else 1, 0, "encoder")
        add(CODE[bit], 1, 3, "encoder")
        bend_y, target_x = 18 + 2 * bit, 5 + 3 * bit
        for y in range(22, bend_y - 1, -1):
            add((col, y), 1, 1 if y == bend_y else 0, "encoder")
        for x in range(col + 1, target_x + 1):
            add((x, bend_y), 1, 0 if x == target_x else 1, "encoder")
        for y in range(bend_y - 1, 15, -1):
            if (target_x,y) not in cells:
                add((target_x, y), 1, 0, "encoder")

    # Preserve every connection within the imported MUX8.
    before, after = edges(original), edges(cells)
    for position, targets in before.items():
        if [q for q in after[position] if q in original] != targets:
            raise ValueError(f"Changed internal MUX connection at {position}")
    reverse = {p: [] for p in cells}
    for p, targets in after.items():
        for q in targets:
            if cells[p].type != 3:
                reverse[q].append(p)
    for p in regions["encoder"] | regions["channels"]:
        if cells[p].type in (1, 10) and len(reverse[p]) > 1:
            # Only the encoder collectors deliberately merge signals.
            if not (p[0] in columns and p[1] in range(23, 52) and (p[1] - 23) % 4 == 0):
                raise ValueError(f"Unexpected signal merge at {p}: {reverse[p]}")
    for fixture in REQUESTS:
        if reverse[fixture]:
            raise ValueError(f"Feedback reaches a request source at {fixture}")

    folder = HERE / "build"
    write_map(folder, STEM, cells)
    (HERE / f"{STEM}.l.asm").write_text(disassemble(cells), encoding="utf-8")
    for mode in range(8):
        preset = dict(cells)
        # A toggle cell at zero input retains its old state; a latch with a
        # permanent enable gives reproducible fixed presets without repeated toggles.
        preset[(-29,25+4*mode)] = Cell(1,1)
        preset[(-30,25+4*mode)] = Cell(1,1)
        preset[REQUESTS[mode]] = Cell(2, 0)
        write_map(folder / "presets", f"mode{mode}", preset)
    test_cells = dict(cells)
    for fixture in REQUESTS:
        test_cells[fixture] = Cell(22, 1)
    for probe in CODE:
        test_cells[probe] = Cell(23, 0)
    for probe in DISPLAY:
        test_cells[probe] = Cell(23, 0)
    for probe in LATCHES:
        test_cells[probe] = Cell(23,0)
    write_map(folder, STEM + ".test", test_cells)
    manifest = {"schema": 1, "top": STEM, "map_hash": map_hash(cells),
        "cells": len(cells), "bounds": bounds_of(cells), "sequential": True,
        "generator_outputs": [list(p) for p in generator_outputs],
        "periods_ticks": [4 * w + 8 for w in WIDTHS],
        "request_sources": [list(p) for p in REQUESTS],
        "latch_probes": [list(p) for p in LATCHES],
        "priority": "lowest_index_nearest_mux", "zero_disables_output": True,
        "logical_output": [13,16], "reference_gate_hash":map_hash(reference),
        "code_probes": [list(p) for p in CODE], "display_targets": [list(p) for p in DISPLAY],
        "output_target": list(OUTPUT),
        "mux_map_hash": mux_meta["map_hash"], "test_map_hash": map_hash(test_cells),
        "profile": "GraphDLC-01232bd", "verified_against_current_game": False,
        "regions": {name: [list(p) for p in sorted(points)] for name, points in regions.items()}}
    write_json(folder / f"{STEM}.build.json", manifest)
    if read_map(folder / f"{STEM}.save.txt") != cells or read_map(folder / f"{STEM}.test.save.txt") != test_cells:
        raise ValueError("Save round-trip changed the circuit")
    print(f"Built {len(cells)} cells, {manifest['bounds']['width']}x{manifest['bounds']['height']}")
    return cells, test_cells, manifest


if __name__ == "__main__":
    build()
