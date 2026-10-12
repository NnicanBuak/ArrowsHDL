module logic_unit #(parameter WIDTH=4)(
    input [WIDTH-1:0] a,b,input [2:0] operation,output [WIDTH-1:0] result
);
    assign result=operation==2 ? a&b : operation==3 ? a|b : operation==4 ? a^b : ~a;
endmodule
