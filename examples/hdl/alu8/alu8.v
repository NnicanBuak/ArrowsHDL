// Eight unsigned operations. All arithmetic wraps to eight bits.
module alu8_add(input [7:0] a,b, input cin,
                output [7:0] sum, output cout);
    wire [8:0] carry;
    assign carry[0] = cin;
    assign cout = carry[8];
    genvar i;
    generate for (i=0; i<8; i=i+1) begin: bit_slice
        wire propagate = a[i] ^ b[i];
        assign sum[i] = propagate ^ carry[i];
        assign carry[i+1] = (a[i] & b[i]) | (propagate & carry[i]);
    end endgenerate
endmodule

module alu8_arithmetic(input [7:0] a,b, input subtract,
                       output [7:0] result, output carry_borrow);
    wire [7:0] operand_b = b ^ {8{subtract}};
    wire carry;
    alu8_add u_add(a,operand_b,subtract,result,carry);
    assign carry_borrow = carry ^ subtract;
endmodule

module alu8_logic(input [7:0] a,b,
                  output [7:0] bit_and,bit_xor,bit_or,bit_not);
    assign bit_and = a & b;
    assign bit_xor = a ^ b;
    assign bit_or = a | b;
    assign bit_not = ~a;
endmodule

module alu8_shift(input [7:0] a, output [7:0] left,right);
    assign left = {a[6:0],1'b0};
    assign right = {1'b0,a[7:1]};
endmodule

module alu8_decode(input [2:0] op, output arithmetic,
                   output [5:0] enable);
    assign arithmetic = ~op[2] & ~op[1];
    assign enable[0] = ~op[2] & op[1] & ~op[0];
    assign enable[1] = ~op[2] & op[1] & op[0];
    assign enable[2] = op[2] & ~op[1] & ~op[0];
    assign enable[3] = op[2] & ~op[1] & op[0];
    assign enable[4] = op[2] & op[1] & ~op[0];
    assign enable[5] = op[2] & op[1] & op[0];
endmodule

module alu8_select(input [7:0] arithmetic,bit_and,bit_xor,bit_or,
                   shift_left,shift_right,bit_not,
                   input arithmetic_enable, input [5:0] enable,
                   output [7:0] result);
    assign result = (arithmetic & {8{arithmetic_enable}})
                  | (bit_and & {8{enable[0]}})
                  | (bit_xor & {8{enable[1]}})
                  | (bit_or & {8{enable[2]}})
                  | (shift_left & {8{enable[3]}})
                  | (shift_right & {8{enable[4]}})
                  | (bit_not & {8{enable[5]}});
endmodule

module alu8(input [7:0] a,b, input [2:0] op,
             output [7:0] result, output carry_borrow,zero);
    wire [7:0] arithmetic,bit_and,bit_xor,bit_or,bit_not,left,right;
    wire arithmetic_flag,arithmetic_enable;
    wire [5:0] enable;
    alu8_arithmetic u_arithmetic(a,b,op[0],arithmetic,arithmetic_flag);
    alu8_logic u_logic(a,b,bit_and,bit_xor,bit_or,bit_not);
    alu8_shift u_shift(a,left,right);
    alu8_decode u_decode(op,arithmetic_enable,enable);
    alu8_select u_select(arithmetic,bit_and,bit_xor,bit_or,left,right,
                         bit_not,arithmetic_enable,enable,result);
    assign carry_borrow = arithmetic_enable & arithmetic_flag;
    assign zero = ~|result;
endmodule
