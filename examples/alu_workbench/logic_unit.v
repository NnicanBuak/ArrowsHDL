module logic_unit #(parameter WIDTH=4)(
    input [WIDTH-1:0] a,b,input [1:0] mode,output [WIDTH-1:0] result
);
    assign result=mode==0 ? a&b : mode==1 ? a|b : mode==2 ? a^b : ~a;
endmodule
