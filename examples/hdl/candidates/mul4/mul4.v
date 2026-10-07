// Unsigned 4x4 multiplication: partial products and a balanced adder tree.
module mul4_partial_products (
    input [3:0] a, b,
    output [7:0] p0, p1, p2, p3
);
    assign p0 = {4'b0, a & {4{b[0]}}};
    assign p1 = {3'b0, a & {4{b[1]}}, 1'b0};
    assign p2 = {2'b0, a & {4{b[2]}}, 2'b0};
    assign p3 = {1'b0, a & {4{b[3]}}, 3'b0};
endmodule

module mul4_add8 (
    input [7:0] a, b,
    output [7:0] sum
);
    wire [8:0] carry;
    assign carry[0] = 1'b0;
    genvar i;
    generate
        for (i = 0; i < 8; i = i + 1) begin: bit_slice
            wire propagate;
            assign propagate = a[i] ^ b[i];
            assign sum[i] = propagate ^ carry[i];
            assign carry[i+1] = (a[i] & b[i]) | (propagate & carry[i]);
        end
    endgenerate
endmodule

module mul4 (
    input [3:0] a, b,
    output [7:0] product
);
    wire [7:0] p0, p1, p2, p3, sum01, sum23;
    mul4_partial_products u_partial(a, b, p0, p1, p2, p3);
    mul4_add8 u_left(p0, p1, sum01);
    mul4_add8 u_right(p2, p3, sum23);
    mul4_add8 u_final(sum01, sum23, product);
endmodule
