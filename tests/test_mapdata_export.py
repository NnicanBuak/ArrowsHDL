import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from arrowasm import Cell
from mapdata import read_map,write_map


class ExportTests(unittest.TestCase):
    def test_new_nested_export_is_readable_in_both_formats(self):
        cells={(0,0):Cell(1,1),(1,0):Cell(11,2)}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'new-build'
            write_map(root,'release/nested/cell',cells)
            for suffix in ('.map.json','.save.txt'):
                self.assertEqual(read_map(root/('release/nested/cell'+suffix)),cells)


if __name__=='__main__':unittest.main()
