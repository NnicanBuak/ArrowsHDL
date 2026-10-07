// Eight full-adder stages using the same equations as the one-bit example.
// https://nandland.com/full-adder/
module adder8 (
    input [7:0] a,
    input [7:0] b,
    input cin,
    output [7:0] sum,
    output cout
);
    wire [8:0] carry;
    assign carry[0] = cin;
    assign cout = carry[8];
    genvar i;
    generate
        for (i = 0; i < 8; i = i + 1) begin: stage
            wire propagate;
            assign propagate = a[i] ^ b[i];
            assign sum[i] = propagate ^ carry[i];
            assign carry[i+1] = (a[i] & b[i]) | (propagate & carry[i]);
        end
    endgenerate
endmodule
