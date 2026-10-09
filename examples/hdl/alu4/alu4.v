// Eight unsigned operations. All arithmetic wraps to four bits.
module alu4_add(input [3:0] a,b, input cin,
                output [3:0] sum, output cout);
    wire [4:0] carry;
    assign carry[0] = cin;
    assign cout = carry[4];
    genvar i;
    generate for (i=0; i<4; i=i+1) begin: bit_slice
        wire propagate = a[i] ^ b[i];
        assign sum[i] = propagate ^ carry[i];
        assign carry[i+1] = (a[i] & b[i]) | (propagate & carry[i]);
    end endgenerate
endmodule

module alu4_arithmetic(input [3:0] a,b, input subtract,
                       output [3:0] result, output carry_borrow);
    wire [3:0] operand_b = b ^ {4{subtract}};
    wire carry;
    alu4_add u_add(a,operand_b,subtract,result,carry);
    assign carry_borrow = carry ^ subtract;
endmodule

module alu4_logic(input [3:0] a,b,
                  output [3:0] bit_and,bit_xor,bit_or,bit_not);
    assign bit_and = a & b;
    assign bit_xor = a ^ b;
    assign bit_or = a | b;
    assign bit_not = ~a;
endmodule

module alu4_shift(input [3:0] a, output [3:0] left,right);
    assign left = {a[2:0],1'b0};
    assign right = {1'b0,a[3:1]};
endmodule

module alu4_decode(input [2:0] op, output arithmetic,
                   output [5:0] enable);
    assign arithmetic = ~op[2] & ~op[1];
    assign enable[0] = ~op[2] & op[1] & ~op[0];
    assign enable[1] = ~op[2] & op[1] & op[0];
    assign enable[2] = op[2] & ~op[1] & ~op[0];
    assign enable[3] = op[2] & ~op[1] & op[0];
    assign enable[4] = op[2] & op[1] & ~op[0];
    assign enable[5] = op[2] & op[1] & op[0];
endmodule

module alu4_select(input [3:0] arithmetic,bit_and,bit_xor,bit_or,
                   shift_left,shift_right,bit_not,
                   input arithmetic_enable, input [5:0] enable,
                   output [3:0] result);
    assign result = (arithmetic & {4{arithmetic_enable}})
                  | (bit_and & {4{enable[0]}})
                  | (bit_xor & {4{enable[1]}})
                  | (bit_or & {4{enable[2]}})
                  | (shift_left & {4{enable[3]}})
                  | (shift_right & {4{enable[4]}})
                  | (bit_not & {4{enable[5]}});
endmodule

module alu4(input [3:0] a,b, input [2:0] op,
             output [3:0] result, output carry_borrow,zero);
    wire [3:0] arithmetic,bit_and,bit_xor,bit_or,bit_not,left,right;
    wire arithmetic_flag,arithmetic_enable;
    wire [5:0] enable;
    alu4_arithmetic u_arithmetic(a,b,op[0],arithmetic,arithmetic_flag);
    alu4_logic u_logic(a,b,bit_and,bit_xor,bit_or,bit_not);
    alu4_shift u_shift(a,left,right);
    alu4_decode u_decode(op,arithmetic_enable,enable);
    alu4_select u_select(arithmetic,bit_and,bit_xor,bit_or,left,right,
                         bit_not,arithmetic_enable,enable,result);
    assign carry_borrow = arithmetic_enable & arithmetic_flag;
    assign zero = ~|result;
endmodule
