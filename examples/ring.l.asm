FORMAT 0
; Кольцо из 8 клеток с записью импульса и чтением через AND.
PLACE arrow 0 0 right
PLACE arrow 1 0 right
PLACE arrow 2 0 down
PLACE splitter_up_right 2 1 down mirrored
PLACE arrow 2 2 left
PLACE arrow 1 2 left
PLACE arrow 0 2 up
PLACE arrow 0 1 up
PLACE level_source 1 -2 down
PLACE arrow 1 -1 down
PLACE level_source 3 0 down
PLACE and 3 1 right
PLACE level_target 4 1 up
