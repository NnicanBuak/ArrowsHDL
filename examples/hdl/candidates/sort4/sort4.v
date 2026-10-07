// Sort four unsigned four-bit words in ascending order without storage.
module sort4_compare (
    input [3:0] a, b,
    output swap
);
    assign swap = a > b;
endmodule

module sort4_mux (
    input [3:0] a, b,
    input select_b,
    output [3:0] result
);
    assign result = select_b ? b : a;
endmodule

module sort4_compare_swap (
    input [3:0] a, b,
    output [3:0] low, high
);
    wire swap;
    sort4_compare u_compare(a, b, swap);
    sort4_mux u_low(a, b, swap, low);
    sort4_mux u_high(b, a, swap, high);
endmodule

module sort4 (
    input [3:0] x0, x1, x2, x3,
    output [3:0] y0, y1, y2, y3
);
    wire [3:0] a0, a1, a2, a3, b1, b2;
    sort4_compare_swap u_pair01(x0, x1, a0, a1);
    sort4_compare_swap u_pair23(x2, x3, a2, a3);
    sort4_compare_swap u_outer_low(a0, a2, y0, b2);
    sort4_compare_swap u_outer_high(a1, a3, b1, y3);
    sort4_compare_swap u_middle(b1, b2, y1, y2);
endmodule
