// Native technology library: standard Verilog-2005 declarations.
// I: normal inputs, B: blocking inputs, S: state behind a detector, O: state.
// All cells read the previous tick. Coordinates never replace connections.
(* blackbox *)
module arrows_cell #(
    parameter integer TYPE = 1,
    parameter integer X = 0,
    parameter integer Y = 0,
    parameter integer ROTATION = 0,
    parameter integer MIRRORED = 0
)(input [10:0] I, input [10:0] B, input S, output O);
endmodule

// Tick-level computation. OP is logical behavior; placement comes from TOML.
// 1 OR, 2 constant source, 3 blocker, 4 delay, 5 detector, 9 pulse,
// 15 NOT, 16 threshold >=2, 17 XOR, 18 SET, 19 TOGGLE, 20 RANDOM.
(* blackbox *) module arrows_logic #(parameter integer OP = 1)
    (input [10:0] I, input [10:0] B, input S, output O);
endmodule

module arrows_set(input [1:0] I, output O);
    (* keep *) arrows_logic #(.OP(18)) impl(.I({9'b0,I}), .B(11'b0), .S(1'b0), .O(O));
endmodule
module arrows_toggle(input I, output O);
    (* keep *) arrows_logic #(.OP(19)) impl(.I({10'b0,I}), .B(11'b0), .S(1'b0), .O(O));
endmodule
module arrows_random(input I, output O);
    (* keep *) arrows_logic #(.OP(20)) impl(.I({10'b0,I}), .B(11'b0), .S(1'b0), .O(O));
endmodule
module arrows_delay(input I, output O);
    (* keep *) arrows_logic #(.OP(4)) impl(.I({10'b0,I}), .B(11'b0), .S(1'b0), .O(O));
endmodule
module arrows_button(input I, output O);
    (* keep *) arrows_logic #(.OP(24)) impl(.I({10'b0,I}), .B(11'b0), .S(1'b0), .O(O));
endmodule
module arrows_indicator(input I, output O);
    (* keep *) arrows_logic #(.OP(1)) impl(.I({10'b0,I}), .B(11'b0), .S(1'b0), .O(O));
endmodule
// Atomic physical macros: timing inside each macro is preserved by placement.
(* blackbox, keep *) module arrows_detector(input I, output O); endmodule
(* blackbox, keep *) module arrows_edge(input I, output O); endmodule
(* blackbox, keep *) module arrows_rise(input I, output O); endmodule
(* blackbox, keep *) module arrows_timer #(parameter integer TICKS=1)(input I, output O); endmodule
(* blackbox, keep *) module arrows_impulse(output O); endmodule
