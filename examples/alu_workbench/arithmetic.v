// WIDTH-bit arithmetic slice; carry/borrow are visible in the high bit.
module arithmetic #(parameter WIDTH=4)(
    input [WIDTH-1:0] a,b, input [2:0] operation,
    output [WIDTH-1:0] result, output carry
);
    wire [WIDTH:0] c;
    wire subtract=operation==1;
    wire [WIDTH-1:0] operand=b^{WIDTH{subtract}};
    assign c[0]=subtract;
    genvar i;
    generate for(i=0;i<WIDTH;i=i+1) begin: bit_slice
        wire p=a[i]^operand[i];
        assign result[i]=p^c[i];
        assign c[i+1]=(a[i]&operand[i])|(p&c[i]);
    end endgenerate
    assign carry=c[WIDTH];
endmodule
