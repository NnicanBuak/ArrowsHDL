"""Example regressions write diagnostics only to an explicitly selected folder."""
import os
from pathlib import Path

from arrowshdl.mapdata import write_json


def save_artifact(project, filename, data):
    directory = os.environ.get('ARROWSHDL_TEST_OUTPUT')
    if not directory:
        return None
    output = Path(directory).expanduser().resolve() / project / filename
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, data)
    return output
