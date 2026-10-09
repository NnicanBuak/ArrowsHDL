module spec(input [3:0] binary,output ok);
    wire [7:0] bcd;
    bcd4 dut(binary,bcd);
    wire [3:0] digit0 = (binary / 1) % 10;
wire [3:0] digit1 = (binary / 10) % 10;
    assign ok = bcd == {digit1,digit0};
endmodule