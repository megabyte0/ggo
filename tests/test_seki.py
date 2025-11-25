# tests/test_seki.py
from ggo.goban_model import Board

def test_seki_example_not_captured():
    # Construct a minimal seki-like arrangement where mutual life occurs.
    b = Board(size=5)
    # manual placement sequence approximating seki
    b.play('B', (1,1))
    b.play('W', (1,2))
    b.play('B', (2,2))
    b.play('W', (2,1))
    # no captures should have occurred
    assert b.get((1,1)) == 'B'
    assert b.get((1,2)) == 'W'
