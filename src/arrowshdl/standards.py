"""Compiler, project schema and language evolve independently."""
from arrowshdl.arrowasm import MapError

PROJECT_VERSIONS = (1,)
OBJECT_VERSION = 1
DEFAULT_STANDARD = "1800-2023"
SUPPORTED_STANDARDS = ("1364-2005", "1800-2023")


def check_standard(value):
    if value not in SUPPORTED_STANDARDS:
        raise MapError(f"Стандарт HDL {value!r} не поддерживается; доступны: {', '.join(SUPPORTED_STANDARDS)}")
    return value


def check_project_version(value):
    if type(value) is not int or value not in PROJECT_VERSIONS:
        raise MapError(f"Версия TOML {value!r} не поддерживается; доступны: {PROJECT_VERSIONS}. Обновите компилятор или используйте совместимый проект")
    return value
