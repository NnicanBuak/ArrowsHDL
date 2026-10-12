// A rising edge toggles one stored selection bit; holding a button is one click.
module selection_memory(input [7:0] controls,output [7:0] active,output [2:0] selection);
    genvar channel;
    generate for(channel=0;channel<8;channel=channel+1) begin: button
        wire pressed;
        arrows_rise edge_detector(controls[channel],pressed);
        arrows_toggle memory(pressed,active[channel]);
    end endgenerate
    // Lowest numbered active channel wins. Channel zero means silence.
    assign selection = active[0] ? 0 : active[1] ? 1 : active[2] ? 2 :
                       active[3] ? 3 : active[4] ? 4 : active[5] ? 5 :
                       active[6] ? 6 : active[7] ? 7 : 0;
endmodule
