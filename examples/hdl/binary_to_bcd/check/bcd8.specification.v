module spec(input [7:0] binary,output ok);
    wire [11:0] bcd;
    bcd8 dut(binary,bcd);
    wire [3:0] digit0 = (binary / 1) % 10;
wire [3:0] digit1 = (binary / 10) % 10;
wire [3:0] digit2 = (binary / 100) % 10;
    assign ok = bcd == {digit2,digit1,digit0};
endmodule