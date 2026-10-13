// Aggregate lane status and ingress parity errors.
module router_status(input lane0_grant0,lane0_grant1,lane1_grant0,lane1_grant1,
                     input lane0_valid,lane1_valid,error0,error1,
                     output [1:0] accepted,output_valid,error);
    assign accepted={lane0_grant1|lane1_grant1,lane0_grant0|lane1_grant0};
    assign output_valid={lane1_valid,lane0_valid};
    assign error={error1,error0};
endmodule

module packet_router(input [5:0] frame0,frame1,input [1:0] valid,ready,
    output [3:0] data0,data1,output [1:0] output_valid,accepted,error);
    wire good0,good1,error0,error1;
    wire valid0,valid1,grant00,grant01,grant10,grant11;
    frame_check ingress0(frame0,valid[0],good0,error0);
    frame_check ingress1(frame1,valid[1],good1,error1);
    output_lane #(.DESTINATION(0)) lane0(good0,good1,frame0,frame1,ready[0],
        valid0,data0,grant00,grant01);
    output_lane #(.DESTINATION(1)) lane1(good0,good1,frame0,frame1,ready[1],
        valid1,data1,grant10,grant11);
    router_status status(grant00,grant01,grant10,grant11,valid0,valid1,error0,error1,
        accepted,output_valid,error);
endmodule
