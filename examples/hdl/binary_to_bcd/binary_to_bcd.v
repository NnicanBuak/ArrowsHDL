// Unsigned binary word to packed decimal digits, least significant digit first.
// DIGITS must hold the largest INPUT_BITS-bit value.
module binary_to_bcd #(parameter INPUT_BITS = 8, parameter DIGITS = 3)
    (input [INPUT_BITS-1:0] binary, output [4*DIGITS-1:0] bcd);
    wire [4*DIGITS-1:0] stage [0:INPUT_BITS];
    assign stage[0] = 0;
    genvar step, digit;
    generate
        for (step = 0; step < INPUT_BITS; step = step+1) begin: stages
            wire [4*DIGITS-1:0] corrected;
            for (digit = 0; digit < DIGITS; digit = digit+1) begin: digits
                assign corrected[4*digit +: 4] = stage[step][4*digit +: 4] >= 4'd5
                    ? stage[step][4*digit +: 4] + 4'd3 : stage[step][4*digit +: 4];
            end
            assign stage[step+1] = {corrected[4*DIGITS-2:0], binary[INPUT_BITS-1-step]};
        end
    endgenerate
    assign bcd = stage[INPUT_BITS];
endmodule

module bcd4(input [3:0] binary, output [7:0] bcd);
    binary_to_bcd #(.INPUT_BITS(4), .DIGITS(2)) convert(binary, bcd);
endmodule

module bcd8(input [7:0] binary, output [11:0] bcd);
    binary_to_bcd #(.INPUT_BITS(8), .DIGITS(3)) convert(binary, bcd);
endmodule
