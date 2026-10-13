module pulse_sequencer(input [7:0] controls,output [7:0] active,
    output [2:0] selection,output waveform);
    wire [7:0] waves;
    selection_memory memory(controls,active,selection);
    oscillator_bank clocks(waves);
    waveform_selector selector(waves,selection,waveform);
endmodule
