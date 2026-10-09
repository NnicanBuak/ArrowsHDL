"""Data model of placed cells, with JSON and game-save representations."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path

from arrowasm import Cell, DIRECTIONS, IDS, NAMES, MapError, decode, encode, validate_cell

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
        raise MapError("Ожидается модель карты schema=1 с полем cells")
    if not isinstance(document["cells"], list):
        raise MapError("cells должен быть списком групп")
    cells = {}
    for group in document["cells"]:
        if not isinstance(group, dict) or not {"type", "at"} <= set(group) or set(group) - {"type", "dir", "mirrored", "at"}:
            raise MapError("Группа карты: type, at, необязательные dir и mirrored")
        type_id = IDS.get(group["type"]) if isinstance(group["type"], str) else group["type"]
        direction = group.get("dir", "up")
        mirrored = group.get("mirrored", False)
        if type(type_id) is not int or direction not in DIRECTIONS or type(mirrored) is not bool or not isinstance(group["at"], list):
            raise MapError("Неверный тип, направление, отражение или координаты группы")
        cell = Cell(type_id, DIRECTIONS.index(direction), mirrored)
        for position in group["at"]:
            if not isinstance(position, list) or len(position) != 2 or any(type(v) is not int for v in position):
                raise MapError("Координата должна быть парой целых чисел")
            key = tuple(position)
            validate_cell(*key, cell)
            if key in cells:
                raise MapError(f"Повторная клетка {key}")
            cells[key] = cell
    return cells


def write_json(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_map(path: Path) -> ArrowMap:
    if path.name.endswith(".json"):
        return from_document(json.loads(path.read_text(encoding="utf-8-sig")))
    return decode(path.read_text(encoding="utf-8-sig"))


def map_hash(cells: ArrowMap) -> str:
    return hashlib.sha256(encode(cells).encode("ascii")).hexdigest()


def write_map(folder: Path, stem: str, cells: ArrowMap) -> None:
    (folder / f"{stem}.map.json").parent.mkdir(parents=True, exist_ok=True)
    groups = to_document(cells)["cells"]
    lines = ['{', '  "schema": 1,', '  "cells": [']
    for index, group in enumerate(groups):
        header = json.dumps({key: value for key, value in group.items() if key != "at"}, ensure_ascii=False)
        lines.append("    " + header[:-1] + ', "at": [')
        row = "      "
        for i, position in enumerate(group["at"]):
            item = json.dumps(position) + ("," if i + 1 < len(group["at"]) else "")
            if len(row) + len(item) > 105:
                lines.append(row.rstrip())
                row = "      "
            row += item + " "
        if row.strip():
            lines.append(row.rstrip())
        lines.append("    ]}" + ("," if index + 1 < len(groups) else ""))
    lines += ["  ]", "}"]
    (folder / f"{stem}.map.json").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (folder / f"{stem}.save.txt").write_text(encode(cells) + "\n", encoding="ascii")
