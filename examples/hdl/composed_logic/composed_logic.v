module transform(input a, b, c, output y);
    wire p = (~a) ^ b;
    wire q = a | c;
    assign y = p & q;
endmodule

module composed_logic(input a, b, c, d, output y, p);
    transform first(a, b, c, p);
    transform second(p, c, d, y);
endmodule
