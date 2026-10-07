// Four operations with independent arithmetic, logic and selection modules.
// op: 00 ADD, 01 SUB, 10 AND, 11 XOR. Inputs are unsigned eight-bit words.
module alu8_add (
    input [7:0] a, b,
    input cin,
    output [7:0] sum,
    output cout
);
    wire [8:0] carry;
    assign carry[0] = cin;
    assign cout = carry[8];
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

module alu8_arithmetic (
    input [7:0] a, b,
    input subtract,
    output [7:0] result,
    output carry_borrow
);
    wire [7:0] operand_b;
    wire carry;
    assign operand_b = b ^ {8{subtract}};
    alu8_add u_add(a, operand_b, subtract, result, carry);
    assign carry_borrow = carry ^ subtract;
endmodule

module alu8_logic (
    input [7:0] a, b,
    output [7:0] bit_and, bit_xor
);
    assign bit_and = a & b;
    assign bit_xor = a ^ b;
endmodule

module alu8_select (
    input [7:0] arithmetic, bit_and, bit_xor,
    input [1:0] op,
    output [7:0] result
);
    assign result = op[1] ? (op[0] ? bit_xor : bit_and) : arithmetic;
endmodule

module alu8 (
    input [7:0] a, b,
    input [1:0] op,
    output [7:0] result,
    output carry_borrow, zero
);
    wire [7:0] arithmetic, bit_and, bit_xor;
    wire arithmetic_flag;
    alu8_arithmetic u_arithmetic(a, b, op[0], arithmetic, arithmetic_flag);
    alu8_logic u_logic(a, b, bit_and, bit_xor);
    alu8_select u_select(arithmetic, bit_and, bit_xor, op, result);
    assign carry_borrow = op[1] ? 1'b0 : arithmetic_flag;
    assign zero = ~|result;
endmodule
