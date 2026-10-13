import sys
import tempfile
import unittest
from pathlib import Path

from arrowshdl.arrowasm import Cell
from arrowshdl.mapdata import read_map,write_map


class ExportTests(unittest.TestCase):
    def test_new_nested_export_writes_only_the_encoded_save(self):
        cells={(0,0):Cell(1,1),(1,0):Cell(11,2)}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'new-build'
            write_map(root,'release/nested/cell',cells)
            saved=root/'release/nested/cell.save.txt'
            self.assertEqual(read_map(saved),cells)
            self.assertEqual(list(saved.parent.iterdir()),[saved])


if __name__=='__main__':unittest.main()
