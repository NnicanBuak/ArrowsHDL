// One-bit inputs, binary selection, one output.
module mux4(input [3:0] data, input [1:0] sel, output y);
    assign y = data[sel];
endmodule

