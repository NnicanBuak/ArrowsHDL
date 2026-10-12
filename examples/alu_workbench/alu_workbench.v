// Operation: 0 ADD, 1 SUB, 2 AND, 3 OR, 4 XOR, 5 NOT A, 6 SHL A, 7 PASS B.
module alu_workbench(input [3:0] a,b,input [2:0] operation,
    output [3:0] result,output carry,zero,equal);
    wire [3:0] arithmetic_result,logical_result;
    wire arithmetic_carry;
    arithmetic #(.WIDTH(4)) math(a,b,operation[0],arithmetic_result,arithmetic_carry);
    logic_unit #(.WIDTH(4)) logic_path(a,b,operation[1:0]-2'b10,logical_result);
    assign result=operation<2 ? arithmetic_result : operation<6 ? logical_result :
                  operation==6 ? {a[2:0],1'b0} : b;
    assign carry=operation<2 ? arithmetic_carry : operation==6 ? a[3] : 1'b0;
    assign zero=~|result;
    assign equal=a==b;
endmodule
