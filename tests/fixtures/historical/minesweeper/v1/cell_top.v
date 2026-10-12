module tile(input [8:0] tile_controls, output alive);
wire [51:0] unused;
minesweeper_cell_v1 tile(.controls(tile_controls),.incoming({ 52{1'b0} }),.outgoing(unused));
assign alive=1'b0;
endmodule
