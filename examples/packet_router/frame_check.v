// Frame: destination[5], even parity[4], four-bit payload[3:0].
module frame_check(input [5:0] frame,input valid,output good,error);
    assign error=valid & (^frame[4:0]);
    assign good=valid & ~(^frame[4:0]);
endmodule
