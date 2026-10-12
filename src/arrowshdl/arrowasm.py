"""Readable maps and strict encoding of the public Logic Arrows save format v0."""
from __future__ import annotations

import argparse
import base64
import binascii
from dataclasses import dataclass
from pathlib import Path
import struct
import sys


# IDs derived from the public BrainfuckArrows enum (enum value minus one).
NAMES = {
    1: "arrow", 2: "source", 3: "blocker", 4: "delay", 5: "detector",
    6: "splitter_up_down", 7: "splitter_up_right", 8: "splitter_up_right_left",
    9: "pulse", 10: "blue_arrow", 11: "diagonal", 12: "blue_splitter_up_up",
    13: "blue_splitter_right_up", 14: "blue_splitter_up_diagonal",
    15: "not", 16: "and", 17: "xor", 18: "latch", 19: "flipflop",
    20: "random", 21: "button", 22: "level_source", 23: "level_target",
    24: "directional_button", 25: "wall",
}
IDS = {name: number for number, name in NAMES.items()}
DIRECTIONS = ("up", "right", "down", "left")


class MapError(ValueError):
    pass


@dataclass(frozen=True)
class Cell:
    type: int
    rotation: int
    mirrored: bool = False


@dataclass(frozen=True)
class Place:
    x: int
    y: int
    cell: Cell
    line: int


@dataclass(frozen=True)
class Program:
    version: int
    instructions: tuple[Place, ...]


def validate_cell(x: int, y: int, cell: Cell) -> None:
    if not 1 <= cell.type <= 255:
        raise MapError("Тип элемента должен быть от 1 до 255")
    if not 0 <= cell.rotation <= 3:
        raise MapError("Поворот должен быть от 0 до 3")
    if any(not -32767 <= value // 16 <= 32767 for value in (x, y)):
        raise MapError("Координаты выходят за пределы формата v0")


def parse(text: str) -> Program:
    instructions = []
    version = None
    for line, raw in enumerate(text.lstrip("\ufeff").splitlines(), 1):
        words = raw.split(";", 1)[0].split()
        if not words:
            continue
        try:
            if words[0].upper() == "FORMAT":
                if len(words) != 2 or version is not None or instructions:
                    raise MapError("FORMAT 0 должен быть первой и единственной директивой формата")
                version = int(words[1])
                if version != 0:
                    raise MapError("Поддерживается только FORMAT 0")
                continue
            if words[0].upper() != "PLACE" or len(words) not in (5, 6):
                raise MapError("Ожидается PLACE тип x y направление [mirrored]")
            if len(words) == 6 and words[5] != "mirrored":
                raise MapError("Неизвестный флаг: ожидается mirrored")
            name = words[1]
            if name in IDS:
                type_id = IDS[name]
            elif name.startswith("type_"):
                type_id = int(name[5:])
            else:
                raise MapError(f"Неизвестный тип: {name}; числовой тип записывается как type_N")
            x, y = int(words[2]), int(words[3])
            if words[4] not in DIRECTIONS:
                raise MapError("Направление: up, right, down или left")
            cell = Cell(type_id, DIRECTIONS.index(words[4]), len(words) == 6)
            validate_cell(x, y, cell)
            instructions.append(Place(x, y, cell, line))
        except ValueError as error:
            message = str(error) if isinstance(error, MapError) else "Неверное целое число"
            raise MapError(f"Строка {line}: {message}") from error
    return Program(version if version is not None else 0, tuple(instructions))


def lower(program: Program) -> dict[tuple[int, int], Cell]:
    cells = {}
    for instruction in program.instructions:
        key = instruction.x, instruction.y
        if key in cells:
            raise MapError(f"Строка {instruction.line}: клетка {key} уже занята")
        cells[key] = instruction.cell
    return cells


def encode(cells: dict[tuple[int, int], Cell]) -> str:
    chunks = {}
    for (x, y), cell in sorted(cells.items()):
        validate_cell(x, y, cell)
        groups = chunks.setdefault((x // 16, y // 16), {})
        groups.setdefault(cell.type, []).append(((x % 16) | ((y % 16) << 4), cell))
    if len(chunks) > 65535:
        raise MapError("В формате v0 допускается не более 65535 чанков")
    data = bytearray(struct.pack("<HH", 0, len(chunks)))
    for (cx, cy), groups in sorted(chunks.items()):
        sx = abs(cx) | (0x8000 if cx < 0 else 0)
        sy = abs(cy) | (0x8000 if cy < 0 else 0)
        data.extend(struct.pack("<HHB", sx, sy, len(groups) - 1))
        for type_id, arrows in sorted(groups.items()):
            data.extend((type_id, len(arrows) - 1))
            for position, cell in sorted(arrows, key=lambda item: item[0]):
                data.extend((position, cell.rotation | (int(cell.mirrored) << 2)))
    return base64.b64encode(data).decode("ascii")


def decode(save: str) -> dict[tuple[int, int], Cell]:
    try:
        data = base64.b64decode("".join(save.lstrip("\ufeff").split()), validate=True)
    except (binascii.Error, ValueError) as error:
        raise MapError("Сохранение должно быть строкой Base64 формата v0") from error
    offset = 0

    def take(count: int) -> bytes:
        nonlocal offset
        if offset + count > len(data):
            raise MapError(f"Сохранение обрезано на байте {offset}")
        result = data[offset:offset + count]
        offset += count
        return result

    version, count = struct.unpack("<HH", take(4))
    if version != 0:
        raise MapError(f"Версия сохранения {version} не поддерживается; ожидается 0")
    cells, seen_chunks = {}, set()
    for _ in range(count):
        cx, cy, groups = struct.unpack("<HHB", take(5))
        cx = -(cx & 0x7FFF) if cx & 0x8000 else cx
        cy = -(cy & 0x7FFF) if cy & 0x8000 else cy
        if (cx, cy) in seen_chunks:
            raise MapError("Повторный чанк в сохранении")
        seen_chunks.add((cx, cy))
        seen_types = set()
        for _ in range(groups + 1):
            type_id, size = take(2)
            if type_id == 0 or type_id in seen_types:
                raise MapError("Пустой или повторный тип элемента в чанке")
            seen_types.add(type_id)
            for _ in range(size + 1):
                position, flags = take(2)
                if flags & ~7:
                    raise MapError("Неизвестные биты поворота/отражения")
                key = cx * 16 + (position & 15), cy * 16 + (position >> 4)
                if key in cells:
                    raise MapError("Повторная клетка в сохранении")
                cells[key] = Cell(type_id, flags & 3, bool(flags & 4))
    if offset != len(data):
        raise MapError("Лишние байты в конце сохранения")
    return cells


def disassemble(cells: dict[tuple[int, int], Cell]) -> str:
    lines = ["FORMAT 0", "; PLACE тип x y направление [mirrored]"]
    for (x, y), cell in sorted(cells.items(), key=lambda item: (item[0][1], item[0][0])):
        name = NAMES.get(cell.type, f"type_{cell.type}")
        flags = " mirrored" if cell.mirrored else ""
        lines.append(f"PLACE {name} {x} {y} {DIRECTIONS[cell.rotation]}{flags}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Ассемблер и дизассемблер карт Стрелочек (формат v0)")
    parser.add_argument("operation", choices=("assemble", "disassemble"))
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", required=True, type=Path)
    parser.add_argument("--strip-test-ports", action="store_true",
                        help="Исключить LevelSource/LevelTarget из собираемой карты")
    args = parser.parse_args()
    if args.strip_test_ports and args.operation != "assemble":
        parser.error("--strip-test-ports применяется только к assemble")
    try:
        source = args.input.read_text(encoding="utf-8-sig")
        if args.operation == "assemble":
            cells = lower(parse(source))
            if args.strip_test_ports:
                cells = {key: cell for key, cell in cells.items() if cell.type not in (22, 23)}
            result = encode(cells) + "\n"
        else:
            result = disassemble(decode(source))
        args.output.write_text(result, encoding="utf-8")
    except (OSError, MapError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
