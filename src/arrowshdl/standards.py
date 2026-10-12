"""Compiler, project schema and language evolve independently."""
from arrowshdl.arrowasm import MapError

PROJECT_VERSIONS = (3,)
OBJECT_VERSION = 1
DEFAULT_STANDARD = "1800-2023"
SUPPORTED_STANDARDS = ("1364-2005", "1800-2023")


def check_standard(value):
    if value not in SUPPORTED_STANDARDS:
        raise MapError(f"HDL standard {value!r} is unsupported; available: {', '.join(SUPPORTED_STANDARDS)}")
    return value


def check_project_version(value):
    if type(value) is not int or value not in PROJECT_VERSIONS:
        raise MapError(f"TOML version {value!r} is unsupported; available: {PROJECT_VERSIONS}. Update the compiler or use a compatible project")
    return value
