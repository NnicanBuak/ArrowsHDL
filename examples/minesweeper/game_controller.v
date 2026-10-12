// A game begins when the first cell has stored its selection.
module game_controller(input new_game,first_selected,solved,hit,
    output started,victory,defeat);
    arrows_latch start_state((|first_selected)&~new_game,new_game,started);
    arrows_latch loss_state((|hit)&started&~victory&~new_game,new_game,defeat);
    arrows_latch win_state((&solved)&started&~defeat&~new_game,new_game,victory);
endmodule
