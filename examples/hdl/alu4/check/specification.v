module spec(input [3:0] a,b,input [2:0] op,output ok);
    wire [3:0] result;
    wire carry_borrow,zero;
    alu4 dut(a,b,op,result,carry_borrow,zero);
    wire [4:0] added = {1'b0,a}+{1'b0,b};
    wire [3:0] expected = op==0 ? a+b : op==1 ? a-b :
        op==2 ? a&b : op==3 ? a^b : op==4 ? a|b :
        op==5 ? a<<1 : op==6 ? a>>1 : ~a;
    wire flag = op==0 ? added[4] : op==1 ? a<b : 1'b0;
    assign ok = (result==expected) && (carry_borrow==flag) &&
                (zero==(expected==0));
endmodule