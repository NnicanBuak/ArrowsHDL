"""ArrowsHDL: compiler, map codec and physical simulation."""
__version__ = "0.1.0"

from arrowshdl.api import BuildResult, build, compile, compile_object, link, simulate
from arrowshdl.arrowasm import Cell, MapError, decode, encode

__all__ = ['BuildResult', 'Cell', 'MapError', 'build', 'compile', 'compile_object',
           'link', 'simulate', 'decode', 'encode', '__version__']
