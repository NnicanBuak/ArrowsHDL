// A four-bit calculator. Press store to save the selected result.
module mini_calculator(
    input [3:0] operand,
    input [2:0] operation,
    input store,
    input clear,
    output [3:0] result,
    output carry,
    output zero,
    output [6:0] segments
);
    wire [4:0] saved_state;
    wire [3:0] saved_result = saved_state[3:0];
    wire [3:0] arithmetic_result;
    wire arithmetic_carry;
    wire [3:0] next_result;
    wire next_carry = (operation == 0 || operation == 1) && arithmetic_carry;
    wire [4:0] register_input = clear ? 5'b00000 : {next_carry, next_result};

    arithmetic arithmetic_unit(
        saved_result, operand, operation,
        arithmetic_result, arithmetic_carry
    );

    assign next_result = operation == 0 ? arithmetic_result :
                         operation == 1 ? arithmetic_result :
                         operation == 2 ? (saved_result & operand) :
                         operation == 3 ? (saved_result | operand) :
                         operation == 4 ? (saved_result ^ operand) :
                         operation == 5 ? ~saved_result :
                         operation == 6 ? {saved_result[2:0], 1'b0} :
                                          operand;

    arrows_register carry_register(store | clear, register_input[4], saved_state[4]);
    arrows_register result_bit_0(store | clear, register_input[0], saved_state[0]);
    arrows_register result_bit_1(store | clear, register_input[1], saved_state[1]);
    arrows_register result_bit_2(store | clear, register_input[2], saved_state[2]);
    arrows_register result_bit_3(store | clear, register_input[3], saved_state[3]);

    assign result = saved_result;
    assign carry = saved_state[4];
    assign zero = ~|saved_result;

    seven_segment decoder(saved_result, segments);
endmodule
