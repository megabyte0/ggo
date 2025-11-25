# tests/test_captures.py
import pytest
from ggo.goban_model import Board

def test_single_capture():
    # Простая и однозначная ситуация: 3x3, белый в центре, затем черные ставят
    # на все 4 соседние точки и захватывают белого.
    b = Board(size=3)
    # White plays center
    b.play('W', (1,1))
    # Black surrounds: up, left, right, down
    b.play('B', (0,1))
    b.play('W', None, is_pass=True)
    b.play('B', (1,0))
    b.play('W', None, is_pass=True)
    b.play('B', (1,2))
    b.play('W', None, is_pass=True)
    # final surrounding move that removes last liberty
    b.play('B', (2,1))  # this move should capture the white stone at (1,1)
    assert b.get((1,1)) is None
