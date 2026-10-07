"""Render the user's TEST source-block sample from its save, not from a screenshot."""
from pathlib import Path
import sys

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from arrowasm import decode


def main():
    cells = decode((ROOT / "examples" / "test.save.txt").read_text(encoding="utf-8"))
    if not cells or any(cell.type != 2 for cell in cells.values()):
        raise ValueError("Эта демонстрация рисует только образец из источников сигнала")
    size, padding, scale = 24, 1, 3
    min_x, max_x = min(x for x, y in cells), max(x for x, y in cells)
    min_y, max_y = min(y for x, y in cells), max(y for x, y in cells)
    width = (max_x - min_x + 1 + padding * 2) * size
    height = (max_y - min_y + 1 + padding * 2) * size
    image = Image.new("RGB", (width * scale, height * scale), "white")
    draw = ImageDraw.Draw(image)
    for value in range(0, width + 1, size):
        draw.line((value * scale, 0, value * scale, height * scale), fill="#dddddd", width=scale)
    for value in range(0, height + 1, size):
        draw.line((0, value * scale, width * scale, value * scale), fill="#dddddd", width=scale)
    for x, y in cells:
        left, top = (x - min_x + padding) * size, (y - min_y + padding) * size
        # Signal backgrounds cover the entire cell, including the grid below.
        draw.rectangle((left * scale, top * scale, (left + size) * scale - 1, (top + size) * scale - 1), fill="#e00000")
    # Draw symbols only after every signal background has been filled.
    for x, y in cells:
        left, top = (x - min_x + padding) * size, (y - min_y + padding) * size
        cx, cy, r = left + size / 2, top + size / 2, size / 3
        draw.polygon([(cx * scale, (cy - r) * scale), ((cx + r) * scale, cy * scale), (cx * scale, (cy + r) * scale), ((cx - r) * scale, cy * scale)], fill="#181818", outline="#ff9d9d", width=scale)
    image.resize((width, height), Image.Resampling.LANCZOS).save(ROOT / "examples" / "test.preview.png")


if __name__ == "__main__":
    main()
