"""Create starter ArrowsHDL projects from CLI options."""
import json
import re
from pathlib import Path

from arrowshdl.arrowasm import MapError
from arrowshdl.standards import DEFAULT_STANDARD


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_INTEGER = re.compile(r"^-?(?:0|[1-9][0-9]*)$")
_WIDGETS = ("button", "indicator", "binary")
_DESIGNS = ("none", "empty", "ports", "grid")


def _toml_string(value):
    return json.dumps(str(value), ensure_ascii=False)


def _toml_array(values):
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def _parameter_value(value):
    return int(value) if _INTEGER.fullmatch(value) else _toml_string(value)


def _parse_parameters(values):
    result = []
    for value in values:
        if "=" not in value:
            raise MapError("--parameter: expected NAME=VALUE")
        name, parameter = value.split("=", 1)
        if not _IDENTIFIER.fullmatch(name):
            raise MapError(f"--parameter: invalid HDL parameter name {name!r}")
        if not parameter:
            raise MapError("--parameter: VALUE must not be empty")
        result.append((name, _parameter_value(parameter), parameter))
    return result


def _parse_ports(values):
    result = []
    seen = set()
    for value in values:
        if "=" not in value:
            raise MapError("--port: expected NAME=WIDGET")
        name, widget = value.split("=", 1)
        if not _IDENTIFIER.fullmatch(name):
            raise MapError(f"--port: invalid HDL port name {name!r}")
        if widget not in _WIDGETS:
            raise MapError(f"--port: WIDGET must be one of {', '.join(_WIDGETS)}")
        if name in seen:
            raise MapError(f"--port: duplicate port {name!r}")
        seen.add(name)
        result.append((name, widget))
    return result


def _design_text(kind, ports, input_bus_gap, project_name):
    if kind == "none":
        return None
    if kind == "empty":
        return "version = 1\n"

    lines = ["version = 1", ""]
    for port_name, widget in ports:
        lines.extend(("[[ports]]", f"path = {_toml_string(port_name)}", f"widget = {_toml_string(widget)}", ""))
    if kind == "grid":
        lines.extend(("[placement]", f"input_bus_gap = {_toml_string(input_bus_gap)}", "", "[[placement.placements]]",
                      f"instance = {_toml_string(project_name)}", "at = [0, 0]", ""))
    return "\n".join(lines)


def create_project(path, name, *, standard=DEFAULT_STANDARD, design="none", defines=(), includes=(),
                   parameters=(), ports=(), input_bus_gap="auto", force=False):
    """Create a starter project directory and return its generated paths."""
    if not _IDENTIFIER.fullmatch(name):
        raise MapError(f"Project name must be a valid HDL identifier: {name!r}")
    if design not in _DESIGNS:
        raise MapError(f"--design must be one of {', '.join(_DESIGNS)}")
    if input_bus_gap != "auto":
        try:
            input_bus_gap = int(input_bus_gap)
        except (TypeError, ValueError) as exc:
            raise MapError("--input-bus-gap must be auto or a nonnegative integer") from exc
        if input_bus_gap < 0:
            raise MapError("--input-bus-gap must be auto or a nonnegative integer")
    parsed_parameters = _parse_parameters(parameters)
    parsed_ports = _parse_ports(ports)
    if parsed_ports and design not in ("ports", "grid"):
        raise MapError("--port requires --design ports or --design grid")
    if design in ("ports", "grid") and not parsed_ports:
        parsed_ports = [("input_signal", "button"), ("output_signal", "indicator")]

    root = Path(path).expanduser().resolve() / name
    root.mkdir(parents=True, exist_ok=True)
    source = root / f"{name}.v"
    project = root / "project.toml"
    design_path = root / "design.toml"
    generated = [project, source]
    design_text = _design_text(design, parsed_ports, input_bus_gap, name)
    if design_text is not None:
        generated.append(design_path)
    existing = [file for file in generated if file.exists()]
    if existing and not force:
        names = ", ".join(str(file) for file in existing)
        raise MapError(f"Refusing to overwrite existing files: {names}; use --force to replace them")

    project_lines = ["version = 3", f"top = {_toml_string(name)}", f"sources = [{_toml_string(source.name)}]"]
    if design_text is not None:
        project_lines.append('design = "design.toml"')
    if includes:
        project_lines.append(f"include_dirs = {_toml_array(includes)}")
    if defines:
        project_lines.append(f"defines = {_toml_array(defines)}")
    if parsed_parameters:
        values = ", ".join(f"{key} = {value}" for key, value, _ in parsed_parameters)
        project_lines.append(f"parameters = {{ {values} }}")
    project_lines.extend(("", "[language]", f"standard = {_toml_string(standard)}", ""))

    parameter_block = ""
    if parsed_parameters:
        declarations = ",\n    ".join(f"parameter {key} = {raw}" for key, _, raw in parsed_parameters)
        parameter_block = f" #(\n    {declarations}\n)"
    source_text = f'''// Starter module generated by ArrowsHDL.
// Replace this starter logic with your circuit logic.
module {name}{parameter_block}(
    input input_signal,
    output output_signal
);
    assign output_signal = ~input_signal;
endmodule
'''
    project.write_text("\n".join(project_lines), encoding="utf-8", newline="\n")
    source.write_text(source_text, encoding="utf-8", newline="\n")
    if design_text is not None:
        design_path.write_text(design_text, encoding="utf-8", newline="\n")
    return tuple(generated)


__all__ = ["create_project"]
