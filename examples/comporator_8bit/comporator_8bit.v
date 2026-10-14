// Click a bit button to toggle that bit in the stored operand.
// Compare captures the current comparison until an operand is changed again.
module comporator_8bit(
    input [7:0] press_a,
    input [7:0] press_b,
    input compare_button,
    output [7:0] a_value,
    output [7:0] b_value,
    output less,
    output equal,
    output more,
    output valid
);
    wire [7:0] a_state;
    wire [7:0] b_state;
    wire [7:0] a_pressed;
    wire [7:0] b_pressed;
    wire compare_event;
    wire capture_event;
    wire inputs_changed;
    wire less_now;
    wire equal_now;
    wire more_now;

    arrows_rise compare_edge(compare_button, compare_event);
    assign capture_event = compare_event;

    genvar bit_index;
    generate for (bit_index = 0; bit_index < 8; bit_index = bit_index + 1) begin: operand_bit
        arrows_rise press_a_edge(press_a[bit_index], a_pressed[bit_index]);
        arrows_rise press_b_edge(press_b[bit_index], b_pressed[bit_index]);

        // Rising-edge detection turns a held UI button into one T-flip-flop click.
        arrows_toggle a_memory(a_pressed[bit_index], a_state[bit_index]);
        arrows_toggle b_memory(b_pressed[bit_index], b_state[bit_index]);
    end endgenerate

    assign inputs_changed = (|a_pressed) | (|b_pressed);
    // Binary output widgets expose the current stored operands for inspection.
    assign a_value = a_state;
    assign b_value = b_state;
    assign less_now = a_state < b_state;
    assign equal_now = a_state == b_state;
    // Derive greater-than from the other two outcomes; this also keeps the
    // three result signals mutually exclusive in the physical network.
    assign more_now = !(less_now | equal_now);

    // Result bits hold their last sampled values until the next Compare.
    arrows_register less_result(capture_event, less_now, less);
    arrows_register equal_result(capture_event, equal_now, equal);
    arrows_register more_result(capture_event, more_now, more);

    // valid marks whether the displayed result still matches the current operands.
    arrows_latch valid_result(compare_event, inputs_changed, valid);
endmodule
