`ifndef ARROWSHDL_UNIT_minesweeper_cell_v2
(* blackbox *) module minesweeper_cell_v2(input [24:0] controls, input [22:0] incoming, output [22:0] outgoing);
endmodule
`endif

`ifndef ARROWSHDL_UNIT_tile
(* blackbox *) module tile(input [24:0] tile_controls, output alive);
endmodule
`endif

`ifndef ARROWSHDL_UNIT_minesweeper_10x10
(* blackbox *) module minesweeper_10x10(input [2499:0] tile_controls, output alive);
endmodule
`endif

`ifndef ARROWSHDL_UNIT_minesweeper_3x3
(* blackbox *) module minesweeper_3x3(input [224:0] tile_controls, output alive);
endmodule
`endif

`ifndef ARROWSHDL_UNIT_minesweeper_5x5
(* blackbox *) module minesweeper_5x5(input [624:0] tile_controls, output alive);
endmodule
`endif
