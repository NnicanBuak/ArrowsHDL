"""Data model of placed cells and the game-save representation."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path

from arrowshdl.arrowasm import Cell, DIRECTIONS, IDS, NAMES, MapError, decode, encode, validate_cell

ArrowMap = dict[tuple[int, int], Cell]


def to_document(cells: ArrowMap) -> dict:
    groups = defaultdict(list)
    for (x, y), cell in sorted(cells.items(), key=lambda item: (item[0][1], item[0][0])):
        validate_cell(x, y, cell)
        groups[(cell.type, cell.rotation, cell.mirrored)].append([x, y])
    result = []
    for (type_id, rotation, mirrored), positions in sorted(groups.items()):
        group = {"type": NAMES.get(type_id, type_id), "dir": DIRECTIONS[rotation], "at": positions}
        if mirrored:
            group["mirrored"] = True
        result.append(group)
    return {"schema": 1, "cells": result}


def from_document(document: dict) -> ArrowMap:
    if not isinstance(document, dict) or set(document) != {"schema", "cells"} or type(document["schema"]) is not int or document["schema"] != 1:
        raise MapError("Expected a schema=1 map model with cells")
    if not isinstance(document["cells"], list):
        raise MapError("cells must be a list of groups")
    cells = {}
    for group in document["cells"]:
        if not isinstance(group, dict) or not {"type", "at"} <= set(group) or set(group) - {"type", "dir", "mirrored", "at"}:
            raise MapError("Map group: type, at, optional dir and mirrored")
        type_id = IDS.get(group["type"]) if isinstance(group["type"], str) else group["type"]
        direction = group.get("dir", "up")
        mirrored = group.get("mirrored", False)
        if type(type_id) is not int or direction not in DIRECTIONS or type(mirrored) is not bool or not isinstance(group["at"], list):
            raise MapError("Invalid group type, direction, mirroring or coordinates")
        cell = Cell(type_id, DIRECTIONS.index(direction), mirrored)
        for position in group["at"]:
            if not isinstance(position, list) or len(position) != 2 or any(type(v) is not int for v in position):
                raise MapError("Coordinate must be a pair of integers")
            key = tuple(position)
            validate_cell(*key, cell)
            if key in cells:
                raise MapError(f"Duplicate cell {key}")
            cells[key] = cell
    return cells


def write_json(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_map(path: Path) -> ArrowMap:
    if path.name.endswith(".json"):
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data,dict) and data.get('format') == 'arrowshdl-compiled-scheme':
            from arrowshdl.artifacts import unpack
            return unpack(data)[0]
        return from_document(data)
    return decode(path.read_text(encoding="utf-8-sig"))


def map_hash(cells: ArrowMap) -> str:
    return hashlib.sha256(encode(cells).encode("ascii")).hexdigest()


def write_map(folder: Path, stem: str, cells: ArrowMap) -> None:
    path = folder / f"{stem}.save.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encode(cells) + "\n", encoding="ascii")


def save_sha256(path):
    """Hash the exact bytes checked, including the stored line ending."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
