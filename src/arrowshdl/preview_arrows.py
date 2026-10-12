"""Render the compiler's own Cell model without third-party adapters."""
from dataclasses import dataclass


@dataclass(frozen=True)
class DisplayArrow:
    type: int
    direction: int
    flipped: bool


def display_arrow(cell):
    return DisplayArrow(cell.type, cell.rotation, cell.mirrored)
