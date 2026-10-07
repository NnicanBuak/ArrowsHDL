"""Adapt placed cells to the borrowed kala-telo/arrows.py display model."""
import importlib.util
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "vendor/kala-telo-arrows/arrows.py"
spec = importlib.util.spec_from_file_location("kala_telo_arrows", SOURCE)
upstream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upstream)
Arrow = upstream.Arrow
ArrowType = upstream.ArrowType
Direction = upstream.Direction


def display_arrow(cell):
    # Preserve numeric extension types accepted by our map format.
    try:
        kind = ArrowType(cell.type)
    except ValueError:
        kind = cell.type
    return Arrow(kind, Direction(cell.rotation), cell.mirrored)
