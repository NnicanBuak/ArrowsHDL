module tile(input [24:0] tile_controls, output alive);
wire [22:0] unused;
minesweeper_cell_v2 tile(.controls(tile_controls),.incoming({ 23{1'b0} }),.outgoing(unused));
assign alive=1'b0;
endmodule
