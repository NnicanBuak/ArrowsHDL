"""Build one platform wheel containing the simulator; source installs need Cargo."""
from pathlib import Path
import os
import shutil
import subprocess

from setuptools import Distribution,setup
from setuptools.command.build_py import build_py
from setuptools.command.bdist_wheel import bdist_wheel

ROOT=Path(__file__).resolve().parent


class BuildWithEngine(build_py):
    def run(self):
        environment=dict(os.environ)
        if os.name=='nt':
            environment['RUSTFLAGS']=environment.get('RUSTFLAGS','')+' -C target-feature=+crt-static'
        subprocess.run(['cargo','build','--release','--locked','--manifest-path',str(ROOT/'native/Cargo.toml')],
                       check=True,env=environment)
        super().run()
        suffix='.exe' if os.name=='nt' else ''
        target=Path(self.build_lib)/'arrowshdl/data/native'
        target.mkdir(parents=True,exist_ok=True)
        cargo_target=os.environ.get('CARGO_BUILD_TARGET')
        release=ROOT/'native/target'
        if cargo_target:
            release=release/cargo_target
        shutil.copy2(release/f'release/logic-arrows-cli{suffix}',target/f'arrowshdl-engine{suffix}')


class PlatformDistribution(Distribution):
    def has_ext_modules(self):return True


class PlatformWheel(bdist_wheel):
    def get_tag(self):
        _,_,platform=super().get_tag()
        return 'py3','none',platform


setup(cmdclass={'build_py':BuildWithEngine,'bdist_wheel':PlatformWheel},distclass=PlatformDistribution)
