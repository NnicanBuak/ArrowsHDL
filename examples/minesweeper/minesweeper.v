// A 5x5 board assembled from one generated row-major array of cells.
module minesweeper(input new_game, input [24:0] selected,
    output [24:0] opened, mine, first_selected,
    output started, victory, defeat);
    wire [24:0] zero_open, solved, hit, visible_mine;
    wire [6:0] segments [0:24];
    wire [2:0] status_chain [0:25];
    assign status_chain[0] = 3'b100;

    game_controller game(new_game, status_chain[25][0], status_chain[25][2],
                         status_chain[25][1], started, victory, defeat);

    genvar i, n;
    generate for (i=0; i<25; i=i+1) begin: cells
        localparam ROW = i / 5;
        localparam COL = i % 5;
        wire [8:0] protected_cells;
        wire [7:0] neighbor_mines, neighbor_zero_open;
        for (n=0; n<9; n=n+1) begin: neighbors
            localparam DR = n / 3 - 1;
            localparam DC = n % 3 - 1;
            if (n == 4) begin: center
                assign protected_cells[n] = first_selected[i];
            end else if (ROW+DR >= 0 && ROW+DR < 5 && COL+DC >= 0 && COL+DC < 5) begin: inside
                assign protected_cells[n] = first_selected[(ROW+DR)*5+COL+DC];
            end else begin: edge
                assign protected_cells[n] = 1'b0;
            end
            if (n < 4) begin: upper_mine
                if (ROW+DR >= 0 && ROW+DR < 5 && COL+DC >= 0 && COL+DC < 5) begin: inside
                    assign neighbor_mines[n] = mine[(ROW+DR)*5+COL+DC];
                    assign neighbor_zero_open[n] = zero_open[(ROW+DR)*5+COL+DC];
                end else begin: edge
                    assign neighbor_mines[n] = 1'b0;
                    assign neighbor_zero_open[n] = 1'b0;
                end
            end else if (n > 4) begin: lower_mine
                if (ROW+DR >= 0 && ROW+DR < 5 && COL+DC >= 0 && COL+DC < 5) begin: inside
                    assign neighbor_mines[n-1] = mine[(ROW+DR)*5+COL+DC];
                    assign neighbor_zero_open[n-1] = zero_open[(ROW+DR)*5+COL+DC];
                end else begin: edge
                    assign neighbor_mines[n-1] = 1'b0;
                    assign neighbor_zero_open[n-1] = 1'b0;
                end
            end
        end
        mine_cell u_cell(
            .new_game(new_game), .selected(selected[i]), .started(started),
            .victory(victory), .defeat(defeat), .protected_cells(protected_cells),
            .neighbor_mines(neighbor_mines), .neighbor_zero_open(neighbor_zero_open),
            .previous_status(status_chain[i]), .mine(mine[i]), .opened(opened[i]),
            .first_selected(first_selected[i]), .zero_open(zero_open[i]),
            .solved(solved[i]), .hit(hit[i]), .visible_mine(visible_mine[i]),
            .status(status_chain[i+1]), .segments(segments[i]));
    end endgenerate
endmodule
