// Ingress 0 has priority; a stalled valid word stays on the output bus.
module output_lane #(parameter DESTINATION=0)(input good0,good1,input [5:0] frame0,frame1,
    input ready,output valid,output [3:0] data,output grant0,grant1);
    wire request0=good0 & (frame0[5]==DESTINATION);
    wire request1=good1 & (frame1[5]==DESTINATION);
    assign valid=request0|request1;
    assign data=request0 ? frame0[3:0] : request1 ? frame1[3:0] : 4'b0;
    assign grant0=ready & request0;
    assign grant1=ready & request1 & ~request0;
endmodule
