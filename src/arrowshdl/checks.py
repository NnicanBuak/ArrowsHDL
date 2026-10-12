"""Regression test suite runner for the installed arrowshdl program."""
from pathlib import Path
import unittest

from arrowshdl.arrowasm import MapError


def check_suite(path,out=None):
    path=Path(path).resolve()
    if not path.is_dir():raise MapError('Test directory not found')
    base=path
    while (base/'__init__.py').is_file():
        base=base.parent
    suite=unittest.defaultTestLoader.discover(str(path),top_level_dir=str(base))
    from arrowshdl.progress import report
    total=suite.countTestCases()
    class ProgressResult(unittest.TextTestResult):
        def stopTest(self,test):
            super().stopTest(test)
            report(95*self.testsRun/max(1,total), f'Tests completed: {self.testsRun}/{total}')
    result=unittest.TextTestRunner(verbosity=2,resultclass=ProgressResult).run(suite)
    if out:
        from arrowshdl.mapdata import write_json
        out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
        write_json(out,dict(passed=result.wasSuccessful(),tests=result.testsRun,
            failures=[dict(test=str(t),traceback=s) for t,s in result.failures],
            errors=[dict(test=str(t),traceback=s) for t,s in result.errors],skipped=len(result.skipped)))
    if result.wasSuccessful(): report(100,'Regression suite passed')
    return 0 if result.wasSuccessful() else 1
