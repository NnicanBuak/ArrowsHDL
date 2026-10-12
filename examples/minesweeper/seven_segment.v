// Bit order: a, b, c, d, e, f, g. A closed cell leaves its display dark.
module seven_segment(input [3:0] count,input visible,output [6:0] segments);
    wire enabled=visible & (count<=8);
    wire one=count==1,two=count==2,three=count==3,four=count==4,seven=count==7;
    assign segments[0]=enabled & ~one & ~four;
    assign segments[1]=enabled & (count!=5) & (count!=6);
    assign segments[2]=enabled & ~two;
    assign segments[3]=enabled & ~one & ~four & ~seven;
    assign segments[4]=enabled & ((count==0)|two|(count==6)|(count==8));
    assign segments[5]=enabled & ~one & ~two & ~three & ~seven;
    assign segments[6]=enabled & (count!=0) & ~one & ~seven;
endmodule
