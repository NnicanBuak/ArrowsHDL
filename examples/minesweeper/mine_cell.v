// The repeated cell: mine storage, reveal state, neighbor count and display.
module mine_cell(input new_game,selected,started,victory,defeat,
    input [8:0] protected_cells,input [7:0] neighbor_mines,neighbor_zero_open,
    input [2:0] previous_status,
    output mine,opened,first_selected,zero_open,solved,hit,visible_mine,
    output [2:0] status,
    output [6:0] segments);
    wire [3:0] count;
    wire [2:0] entropy;
    wire candidate;
    genvar bit_index;
    generate for(bit_index=0;bit_index<3;bit_index=bit_index+1) begin: random_bit
        arrows_random random_source(new_game,entropy[bit_index]);
    end endgenerate
    // Holding New Game generates candidates; releasing it retains the board.
    arrows_register mine_memory(new_game,&entropy,candidate);
    arrows_latch first_memory(selected&~started&~new_game,new_game,first_selected);
    assign mine=candidate&~(|protected_cells);
    wire reveal=(selected|(|neighbor_zero_open))&started&~mine&~victory&~defeat&~new_game;
    arrows_latch reveal_memory(reveal,new_game,opened);
    assign zero_open=opened&~(|neighbor_mines);
    assign solved=opened|mine;
    // The first chosen cell is excluded until its protection has propagated.
    assign hit=selected&started&mine&~first_selected&~victory&~defeat&~new_game;
    assign visible_mine=mine&defeat;
    // Collect board status along the cell chain: [2] solved, [1] hit, [0] selected.
    assign status={previous_status[2]&solved,previous_status[1]|hit,
                   previous_status[0]|first_selected};
    assign count={3'b0,neighbor_mines[0]}+{3'b0,neighbor_mines[1]}+
                 {3'b0,neighbor_mines[2]}+{3'b0,neighbor_mines[3]}+
                 {3'b0,neighbor_mines[4]}+{3'b0,neighbor_mines[5]}+
                 {3'b0,neighbor_mines[6]}+{3'b0,neighbor_mines[7]};
    seven_segment display_driver(count,opened,segments);
endmodule
