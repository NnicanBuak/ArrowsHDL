// One-bit inputs, binary selection, one output.
module mux2(input [1:0] data, input [0:0] sel, output y);
    assign y = data[sel];
endmodule

