
module spec_check_mul4(input [3:0] a,b,output ok);
    wire [7:0] product;
    mul4 dut(a,b,product);
    wire [7:0] expected = a*b;
    assign ok = product==expected;
endmodule
