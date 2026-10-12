module waveform_selector(input [7:0] waves,input [2:0] selection,output waveform);
    assign waveform=waves[selection];
endmodule
