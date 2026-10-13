"""A public compilation exports only the native Logic Arrows game save."""
import os
from pathlib import Path

from arrowshdl.arrowasm import MapError, encode


def validate_output(path):
    path = Path(path)
    if path.is_dir():
        raise MapError(f'Output must be a file, not a directory: {path}. Use {path / "scheme.save.txt"}')
    if path.suffix.lower() != '.txt':
        raise MapError('Output filename must end in .txt (game save)')
    return path


def export(path, cells):
    path = validate_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encode(cells) + '\n', encoding='ascii')
    return path.resolve()


def validate_preview(path,output):
    if path is None: return None
    if output is None:
        raise MapError('A preview requires an output game save path')
    path=Path(path)
    if path.is_dir() or path.suffix.lower()!='.png':
        raise MapError('Preview filename must end in .png and must not be a directory')
    for parent in path.parents:
        if parent.exists() and not parent.is_dir():
            raise MapError(f'Preview parent must be a directory: {parent}')
    if os.path.normcase(str(path.resolve()))==os.path.normcase(str(Path(output).resolve())):
        raise MapError('Preview and game save must have different output paths')
    return path
