// Sort four unsigned eight-bit words in three compare/exchange stages.
module sort4x8_compare (
    input [7:0] a, b,
    output swap
);
    assign swap = a > b;
endmodule

module sort4x8_mux (
    input [7:0] a, b,
    input select_b,
    output [7:0] result
);
    assign result = select_b ? b : a;
endmodule

module sort4x8_compare_swap (
    input [7:0] a, b,
    output [7:0] low, high
);
    wire swap;
    sort4x8_compare u_compare(a, b, swap);
    sort4x8_mux u_low(a, b, swap, low);
    sort4x8_mux u_high(b, a, swap, high);
endmodule

module sort4x8 (
    input [7:0] x0, x1, x2, x3,
    output [7:0] y0, y1, y2, y3
);
    wire [7:0] a0, a1, a2, a3, b1, b2;
    sort4x8_compare_swap u_pair01(x0, x1, a0, a1);
    sort4x8_compare_swap u_pair23(x2, x3, a2, a3);
    sort4x8_compare_swap u_outer_low(a0, a2, y0, b2);
    sort4x8_compare_swap u_outer_high(a1, a3, b1, y3);
    sort4x8_compare_swap u_middle(b1, b2, y1, y2);
endmodule
