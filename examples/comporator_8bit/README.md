# 8-bit comparator with a physical button interface

This example stores two 8-bit operands in the circuit, compares them on demand,
and holds the three result indicators until the next comparison.

## Using the circuit

- Press a button in `press_a` or `press_b` to toggle that bit. Press it again to
  toggle it off. The `a_value` and `b_value` binary displays show the stored
  operands.
- After changing bits, press `compare_button`. The `less`, `equal`, and `more`
  indicators show the captured comparison result.
- `valid` is on when the result matches the current operands. It turns off when
  either operand changes and turns on again when Compare is pressed.

The comparator is combinational: it does not need a clock. ArrowsHDL signals
still take game ticks to propagate. This example's computed settling time is
164 ticks, so allow the operands to settle before comparing them.

## Build and exercise the I/O

From the repository root:

```powershell
arrowshdl build examples/comporator_8bit/project.toml --layout compact -o build/comparator.txt
arrowshdl test examples/comporator_8bit/project.toml examples/comporator_8bit/vectors.json --vectors -o build/comparator-report.json
```

`auto` places 2,807 arrows in an 85 × 68 area. `compact` places 2,351 arrows
in a 64 × 80 area for this example. Compact saves arrows and total area, while
the placement remains a routed grid rather than a schematic-style packing.
