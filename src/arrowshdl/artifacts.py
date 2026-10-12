"""A public build writes one file containing a game save or a reusable scheme."""
import json
from pathlib import Path

from arrowshdl.arrowasm import MapError, encode
from arrowshdl.mapdata import from_document, to_document, write_json

FORMAT = 'arrowshdl-compiled-scheme'


def document(cells, metadata):
    return dict(format=FORMAT, version=1, map=to_document(cells), metadata=metadata)


def unpack(data):
    if not isinstance(data,dict) or data.get('format') != FORMAT or data.get('version') != 1:
        raise MapError('Unsupported compiled scheme format or version')
    if not isinstance(data.get('metadata'),dict) or not {'top','inputs','outputs','map_hash','settle_ticks'}<=data['metadata'].keys() or 'map' not in data:
        raise MapError('Compiled scheme requires map and metadata with top, inputs, outputs, map_hash and settle_ticks')
    return from_document(data['map']), data['metadata']


def validate_output(path):
    path = Path(path)
    if path.is_dir():
        raise MapError(f'Output must be a file, not a directory: {path}. Use {path / "scheme.json"}')
    if path.suffix.lower() not in ('.json', '.txt'):
        raise MapError('Output filename must end in .json (scheme with metadata) or .txt (game save)')
    return path


def export(path, cells, metadata):
    path = validate_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == '.json':
        write_json(path, document(cells, metadata))
    else:
        path.write_text(encode(cells) + '\n', encoding='ascii')
    return path.resolve()


def read_metadata(path):
    path = Path(path)
    if path.suffix.lower() != '.json':
        return None
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    return unpack(data)[1] if isinstance(data,dict) and data.get('format') == FORMAT else None
