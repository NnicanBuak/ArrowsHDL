// Ingress 0 has priority; a stalled valid word stays on the output bus.
module output_lane(input request0,request1,input [3:0] data0,data1,
    input ready,output valid,output [3:0] data,output grant0,grant1);
    assign valid=request0|request1;
    assign data=request0 ? data0 : request1 ? data1 : 4'b0;
    assign grant0=ready & request0;
    assign grant1=ready & request1 & ~request0;
endmodule
