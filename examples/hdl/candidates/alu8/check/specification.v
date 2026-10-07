
module spec_check_alu8(input [7:0] a,b,input [1:0] op,output ok);
    wire [7:0] result;
    wire carry_borrow,zero;
    alu8 dut(a,b,op,result,carry_borrow,zero);
    wire [8:0] added = {1'b0,a}+{1'b0,b};
    wire [7:0] expected = op[1] ? (op[0] ? (a^b) : (a&b)) : (op[0] ? (a-b) : (a+b));
    wire expected_flag = op[1] ? 1'b0 : (op[0] ? (a<b) : added[8]);
    assign ok = (result==expected) && (carry_borrow==expected_flag) && (zero==(expected==8'b0));
endmodule
