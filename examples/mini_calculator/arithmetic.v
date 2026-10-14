// Four-bit addition and subtraction, with carry/no-borrow in carry_out.
module arithmetic(
    input [3:0] a,
    input [3:0] b,
    input [2:0] operation,
    output [3:0] result,
    output carry_out
);
    wire subtract = operation == 1;
    wire [3:0] operand_b = b ^ {4{subtract}};
    wire [4:0] sum = {1'b0, a} + {1'b0, operand_b} + subtract;

    assign result = sum[3:0];
    assign carry_out = sum[4];
endmodule
