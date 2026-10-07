
module spec_check_sort4(input [3:0] x0,x1,x2,x3,output ok);
    wire [3:0] y0,y1,y2,y3;
    sort4 dut(x0,x1,x2,x3,y0,y1,y2,y3);
    wire [2:0] count_x0 = {2'b0,(x0==x0)}+{2'b0,(x1==x0)}+{2'b0,(x2==x0)}+{2'b0,(x3==x0)};
    wire [2:0] count_y0 = {2'b0,(y0==x0)}+{2'b0,(y1==x0)}+{2'b0,(y2==x0)}+{2'b0,(y3==x0)};
    wire [2:0] count_x1 = {2'b0,(x0==x1)}+{2'b0,(x1==x1)}+{2'b0,(x2==x1)}+{2'b0,(x3==x1)};
    wire [2:0] count_y1 = {2'b0,(y0==x1)}+{2'b0,(y1==x1)}+{2'b0,(y2==x1)}+{2'b0,(y3==x1)};
    wire [2:0] count_x2 = {2'b0,(x0==x2)}+{2'b0,(x1==x2)}+{2'b0,(x2==x2)}+{2'b0,(x3==x2)};
    wire [2:0] count_y2 = {2'b0,(y0==x2)}+{2'b0,(y1==x2)}+{2'b0,(y2==x2)}+{2'b0,(y3==x2)};
    wire [2:0] count_x3 = {2'b0,(x0==x3)}+{2'b0,(x1==x3)}+{2'b0,(x2==x3)}+{2'b0,(x3==x3)};
    wire [2:0] count_y3 = {2'b0,(y0==x3)}+{2'b0,(y1==x3)}+{2'b0,(y2==x3)}+{2'b0,(y3==x3)};
    assign ok = (y0<=y1) && (y1<=y2) && (y2<=y3) && (count_x0==count_y0) && (count_x1==count_y1) && (count_x2==count_y2) && (count_x3==count_y3);
endmodule
