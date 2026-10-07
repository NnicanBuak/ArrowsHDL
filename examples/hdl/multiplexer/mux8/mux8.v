// One-bit inputs, binary selection, one output.
module mux8(input [7:0] data, input [2:0] sel, output y);
    assign y = data[sel];
endmodule

