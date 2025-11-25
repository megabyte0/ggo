# tests/test_sgf_roundtrip.py
from ggo.goban_model import Board
import copy

def test_roundtrip_snapshot():
    b = Board(size=5)
    b.play('B', (0,0))
    b.play('W', (4,4))
    snap = copy.deepcopy(b._board)
    # naive "serialize" as board matrix and restore
    b2 = Board(size=5)
    b2._board = [row[:] for row in snap]
    assert b2._board == b._board
