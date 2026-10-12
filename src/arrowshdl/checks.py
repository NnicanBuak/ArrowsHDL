"""Integration checks available through the same installed arrowshdl program."""
from pathlib import Path
import tempfile
import unittest

from arrowshdl.arrowasm import MapError


def check_installation():
    from arrowshdl.verilog_compile import compile_file
    from arrowshdl.test_harness import add_fixture,make_scenario
    from arrowshdl.simulation import simulate
    with tempfile.TemporaryDirectory(prefix='arrowshdl-check-') as directory:
        root=Path(directory);source=root/'check.sv'
        source.write_text('module smoke(input logic a,b,output logic y); always_comb y=a^b; endmodule',encoding='utf-8')
        cells,meta=compile_file(source,'smoke',root/'build')
        vectors=[dict(inputs=dict(a=a,b=b),expect=dict(y=a^b)) for a,b in ((0,0),(1,0),(1,1),(0,1),(0,0))]
        report=simulate(add_fixture(cells,meta),make_scenario(meta,vectors),optimize_cycles=False)
        if not report['passed']:raise MapError('Физическая проверка установленного компилятора не прошла')
    print('PASS: HDL → схема → сохранение → физическая симуляция')
    return 0


def check_suite(path,out=None):
    path=Path(path).resolve()
    if not path.is_dir():raise MapError('Папка тестов не найдена')
    base=path
    while (base/'__init__.py').is_file():
        base=base.parent
    suite=unittest.defaultTestLoader.discover(str(path),top_level_dir=str(base))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if out:
        from arrowshdl.mapdata import write_json
        out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
        write_json(out,dict(passed=result.wasSuccessful(),tests=result.testsRun,
            failures=[dict(test=str(t),traceback=s) for t,s in result.failures],
            errors=[dict(test=str(t),traceback=s) for t,s in result.errors],skipped=len(result.skipped)))
    return 0 if result.wasSuccessful() else 1
