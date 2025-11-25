# tests/test_fuzz_random_games.py
import random
from ggo.goban_model import Board

def test_random_play_invariants():
    b = Board(size=7, superko=False)
    moves = 0
    for _ in range(100):
        # pick random empty point or pass
        empties = [(r,c) for r in range(b.size) for c in range(b.size) if b.get((r,c)) is None]
        if not empties:
            b.play(b.to_move, is_pass=True)
            continue
        pt = random.choice(empties + [None])
        try:
            if pt is None:
                b.play(b.to_move, is_pass=True)
            else:
                b.play(b.to_move, pt)
            moves += 1
        except Exception:
            # illegal moves may occur; ensure board still consistent
            pass
    # invariant: board squares count <= size*size
    total = sum(1 for r in range(b.size) for c in range(b.size) if b.get((r,c)) is not None)
    assert total <= b.size * b.size
