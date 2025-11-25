# tests/test_board_basics.py
import pytest
from ggo.goban_model import Board, Move, OccupiedPoint, Suicide

def test_play_on_empty():
    b = Board(size=5)
    b.play('B', (2,2))
    assert b.get((2,2)) == 'B'
    assert b.move_number == 1

def test_play_on_occupied_raises():
    b = Board(size=5)
    b.play('B', (0,0))
    with pytest.raises(OccupiedPoint):
        b.play('W', (0,0))
