# tests/test_suicide_and_merge.py
import pytest
from ggo.goban_model import Board, Suicide

def test_simple_suicide_forbidden():
    b = Board(size=3)
    # surround corner (0,0) so that W cannot play there
    b.play('B', (0,1))
    b.play('W', (2,2))
    b.play('B', (1,0))
    with pytest.raises(Suicide):
        b.play('W', (0,0))

def test_merge_prevents_suicide():
    b = Board(size=5)
    # create two white groups that will be connected by a move preventing suicide
    b.play('B', (0,1))
    b.play('W', (1,0))
    b.play('B', (2,2))
    b.play('W', (1,2))
    # now W plays (1,1) connecting groups and having liberties
    b.play('B', None, is_pass=True)
    b.play('W', (1,1))
    assert b.get((1,1)) == 'W'
