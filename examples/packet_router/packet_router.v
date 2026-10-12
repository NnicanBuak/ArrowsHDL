// Aggregate lane status and ingress parity errors.
module router_status(input lane0_grant0,lane0_grant1,lane1_grant0,lane1_grant1,
                     input lane0_valid,lane1_valid,error0,error1,
                     output [1:0] accepted,output_valid,error);
    assign accepted={lane0_grant1|lane1_grant1,lane0_grant0|lane1_grant0};
    assign output_valid={lane1_valid,lane0_valid};
    assign error={error1,error0};
endmodule
