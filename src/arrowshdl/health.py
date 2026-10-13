"""Operational self-test using temporary files and installed package resources."""
from pathlib import Path
import sys
import tempfile

from arrowshdl import __version__


class _HealthError(Exception):
    """English diagnostic for a failed self-test assertion."""


def health():
    from arrowshdl.progress import report as progress, phase
    progress(5, 'Checking installed runtimes')
    print(f'ArrowsHDL {__version__} health', flush=True)
    stage = 'Node.js runtime'
    try:
        from nodejs_wheel import node
        result = node(['--version'], return_completed_process=True,
                      capture_output=True, text=True, timeout=5)
        if result.returncode:
            raise _HealthError('Runtime could not start.')
        print(f'[OK] {stage}: {result.stdout.strip()}', flush=True)

        stage = 'Rust simulator'
        from arrowshdl.simulation import runner_binary
        if not runner_binary().is_file():
            raise _HealthError('Simulator executable is missing.')

        with tempfile.TemporaryDirectory(prefix='arrowshdl-health-') as directory:
            root = Path(directory)
            source = root/'health.sv'
            source.write_text('module health_test(input logic a,b,output logic y); '
                              'always_comb y=a^b; endmodule', encoding='utf-8')

            stage = 'HDL compiler'
            from arrowshdl.api import compile
            with phase(10,40,'Checking HDL compiler'):
                built = compile(source, top='health_test', out=root/'scheme.save.txt', timeout=30)
            print(f'[OK] {stage}: built-in circuit compiled', flush=True)

            stage = 'Save codec'
            progress(45, 'Checking save codec')
            from arrowshdl.mapdata import read_map
            from arrowshdl.arrowasm import encode, decode
            saved = read_map(built.artifacts['output'])
            if saved != built.cells or decode(encode(saved)) != saved:
                raise _HealthError('Exported files do not match the compiled circuit.')
            print(f'[OK] {stage}: exported circuit round-trip verified', flush=True)

            stage = 'Physical simulator'
            from arrowshdl.test_harness import add_fixture, make_scenario
            from arrowshdl.simulation import simulate
            vectors = [dict(inputs=dict(a=a,b=b), expect=dict(y=a^b))
                       for a,b in ((0,0),(1,0),(1,1),(0,1))]
            with phase(50,85,'Checking physical simulator'):
                report = simulate(add_fixture(saved,built.metadata),
                                  make_scenario(built.metadata,vectors),
                                  optimize_cycles=False, timeout=20)
            if not report['passed'] or report['checked_samples'] != len(vectors):
                raise _HealthError('Built-in circuit produced incorrect outputs.')
            print(f'[OK] {stage}: all 4 input combinations passed', flush=True)

            stage = 'Preview renderer'
            progress(90, 'Checking preview renderer')
            from arrowshdl.map_preview import render_cells
            from PIL import Image
            picture = root/'preview.png'
            render_cells(saved,picture,built.metadata)
            with Image.open(picture) as preview:
                preview.verify()
            print(f'[OK] {stage}: PNG generated and validated', flush=True)

    except Exception as error:
        detail = str(error) if isinstance(error,_HealthError) else f'Check failed ({type(error).__name__}).'
        print(f'[FAIL] {stage}: {detail}', file=sys.stderr)
        print('Health status: FAILED', file=sys.stderr)
        return 1
    print('Health status: OK')
    progress(100, 'Operational health verified')
    return 0
