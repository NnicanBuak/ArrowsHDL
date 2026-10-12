// Seven independent clocks. Periods are functional timing, not placement hints.
module oscillator_bank(output [7:0] waves);
    assign waves[0]=0;
    genvar channel;
    generate for(channel=1;channel<8;channel=channel+1) begin: oscillator
        localparam PERIOD = channel==1 ? 20 : channel==2 ? 24 : channel==3 ? 32 :
                            channel==4 ? 40 : channel==5 ? 48 : channel==6 ? 64 : 80;
        arrows_clock #(.PERIOD(PERIOD)) clock(waves[channel]);
    end endgenerate
endmodule
