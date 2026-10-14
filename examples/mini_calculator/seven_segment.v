// Segment order is a, b, c, d, e, f, g. Displays hexadecimal 0 through F.
module seven_segment(input [3:0] value, output [6:0] segments);
    assign segments[0] = value == 0 || value == 2 || value == 3 ||
                         value == 5 || value == 6 || value == 7 ||
                         value == 8 || value == 9 || value == 10 ||
                         value == 12 || value == 14 || value == 15;
    assign segments[1] = value == 0 || value == 1 || value == 2 ||
                         value == 3 || value == 4 || value == 7 ||
                         value == 8 || value == 9 || value == 10 ||
                         value == 13;
    assign segments[2] = value == 0 || value == 1 || value == 3 ||
                         value == 4 || value == 5 || value == 6 ||
                         value == 7 || value == 8 || value == 9 ||
                         value == 10 || value == 11 || value == 13;
    assign segments[3] = value == 0 || value == 2 || value == 3 ||
                         value == 5 || value == 6 || value == 8 ||
                         value == 9 || value == 11 || value == 12 ||
                         value == 13 || value == 14;
    assign segments[4] = value == 0 || value == 2 || value == 6 ||
                         value == 8 || value == 10 || value == 11 ||
                         value == 12 || value == 13 || value == 14 ||
                         value == 15;
    assign segments[5] = value == 0 || value == 4 || value == 5 ||
                         value == 6 || value == 8 || value == 9 ||
                         value == 10 || value == 11 || value == 12 ||
                         value == 14 || value == 15;
    assign segments[6] = value == 2 || value == 3 || value == 4 ||
                         value == 5 || value == 6 || value == 8 ||
                         value == 9 || value == 10 || value == 11 ||
                         value == 13 || value == 14 || value == 15;
endmodule
