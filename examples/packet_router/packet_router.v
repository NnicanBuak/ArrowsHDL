module packet_router(input [5:0] frame0,frame1,input [1:0] valid,ready,
    output [3:0] data0,data1,output [1:0] output_valid,accepted,error);
    wire good0,good1,g00,g01,g10,g11;
    frame_check ingress0(frame0,valid[0],good0,error[0]);
    frame_check ingress1(frame1,valid[1],good1,error[1]);
    output_lane lane0(good0&~frame0[5],good1&~frame1[5],frame0[3:0],frame1[3:0],
                      ready[0],output_valid[0],data0,g00,g01);
    output_lane lane1(good0&frame0[5],good1&frame1[5],frame0[3:0],frame1[3:0],
                      ready[1],output_valid[1],data1,g10,g11);
    assign accepted={g01|g11,g00|g10};
endmodule
