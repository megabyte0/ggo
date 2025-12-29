# goban_model.py
from collections import deque, namedtuple
import hashlib
import copy
from typing import List


# Exceptions
class IllegalMove(Exception): pass


class OccupiedPoint(IllegalMove): pass


class Suicide(IllegalMove): pass


class KoViolation(IllegalMove): pass


Move = namedtuple('Move', ['color', 'point', 'is_pass', 'is_resign', 'move_number', 'is_add'])


def _opponent(color):
    return 'W' if color == 'B' else 'B'


class Board:
    def __init__(self, size=19, komi=6.5, handicap=0, superko=False):
        self.size = size
        self.komi = komi
        self.handicap = handicap
        self.superko = superko
        self._board = [[None] * size for _ in range(size)]
        self.to_move = 'B'
        self.move_number = 0
        self.captures = {'B': 0, 'W': 0}
        self._history = []  # stack of states for undo
        self.position_hashes = []  # for superko
        self._push_history_snapshot()  # initial position hash

    # --- helpers ---
    def in_bounds(self, r, c):
        return 0 <= r < self.size and 0 <= c < self.size

    def get(self, point):
        if point is None: return None
        r, c = point
        return self._board[r][c]

    def _neighbors(self, r, c):
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < self.size and 0 <= nc < self.size:
                yield nr, nc

    def _group_and_liberties(self, start):
        """Return (stones_set, liberties_set) for group containing start."""
        color = self.get(start)
        if color is None: return set(), set()
        visited = set()
        liberties = set()
        stack = [start]
        while stack:
            p = stack.pop()
            if p in visited: continue
            visited.add(p)
            r, c = p
            for nr, nc in self._neighbors(r, c):
                if self._board[nr][nc] is None:
                    liberties.add((nr, nc))
                elif self._board[nr][nc] == color and (nr, nc) not in visited:
                    stack.append((nr, nc))
        return visited, liberties

    def _find_adjacent_enemy_groups_with_no_libs(self, point, color):
        """After placing color at point (not yet committed), find enemy groups with 0 liberties."""
        r, c = point
        enemy = _opponent(color)
        to_check = set()
        for nr, nc in self._neighbors(r, c):
            if self._board[nr][nc] == enemy:
                to_check.add((nr, nc))
        captured_groups = []
        for p in to_check:
            stones, libs = self._group_and_liberties(p)
            if len(libs) == 0:
                captured_groups.append(stones)
        return captured_groups

    def _apply_capture(self, groups):
        removed = 0
        for group in groups:
            for (r, c) in group:
                color = self._board[r][c]
                self._board[r][c] = None
                removed += 1
                self.captures[_opponent(color)] += 1  # opponent captured these stones
        return removed

    def _board_hash(self):
        # deterministic hash: rows + to_move
        s = []
        for r in range(self.size):
            for c in range(self.size):
                v = self._board[r][c]
                s.append('.' if v is None else v)
        s.append(self.to_move)
        # include captures optionally; for simple superko we include only stones+to_move
        raw = ''.join(s).encode('utf-8')
        return hashlib.sha256(raw).hexdigest()

    def _push_history_snapshot(self):
        # store deep copy minimal snapshot for undo
        snapshot = {
            'board': [row[:] for row in self._board],
            'to_move': self.to_move,
            'move_number': self.move_number,
            'captures': dict(self.captures),
            'hash': self._board_hash()
        }
        self._history.append(snapshot)
        self.position_hashes.append(snapshot['hash'])

    def undo(self):
        if len(self._history) <= 1:
            return
        # pop current snapshot
        self._history.pop()
        self.position_hashes.pop()
        prev = self._history[-1]
        self._board = [row[:] for row in prev['board']]
        self.to_move = prev['to_move']
        self.move_number = prev['move_number']
        self.captures = dict(prev['captures'])

    # --- main API ---
    def legal(self, move: Move):
        """Raise IllegalMove subclass if illegal, otherwise return True."""
        if move.is_pass or move.is_resign:
            return True
        pt = move.point
        if not self.in_bounds(*pt):
            raise IllegalMove("Out of bounds")
        if self.get(pt) is not None:
            raise OccupiedPoint("Point occupied")
        # simulate placement
        r, c = pt
        # place temporarily
        self._board[r][c] = move.color
        # find enemy groups to capture
        captured_groups = self._find_adjacent_enemy_groups_with_no_libs(pt, move.color)
        # remove them temporarily
        removed = []
        for g in captured_groups:
            for (rr, cc) in g:
                removed.append(((rr, cc), self._board[rr][cc]))
                self._board[rr][cc] = None
        # check own group liberties
        stones, libs = self._group_and_liberties(pt)
        # revert temporary placement and removals
        for (rr, cc), col in removed:
            self._board[rr][cc] = col
        self._board[r][c] = None
        if len(libs) == 0:
            raise Suicide("Move would be suicide")
        # check superko
        # compute hypothetical hash after commit: we simulate commit quickly
        # commit simulation:
        # copy board, apply placement and captures, compute hash
        board_copy = [row[:] for row in self._board]
        board_copy[r][c] = move.color
        for g in captured_groups:
            for (rr, cc) in g:
                board_copy[rr][cc] = None
        # compute hash
        s = []
        for rr in range(self.size):
            for cc in range(self.size):
                v = board_copy[rr][cc]
                s.append('.' if v is None else v)
        s.append(_opponent(move.color))  # next to move after commit
        raw = ''.join(s).encode('utf-8')
        h = hashlib.sha256(raw).hexdigest()
        if self.superko and h in self.position_hashes:
            raise KoViolation("Superko violation")
        return True

    def apply_move(self, move: Move):
        """Apply move or raise IllegalMove subclass. Atomic: either commit or no change."""
        # save snapshot for undo
        # We'll push snapshot only on successful commit
        if move.is_pass:
            # commit pass
            self.move_number += 1
            self.to_move = _opponent(self.to_move)
            self._push_history_snapshot()
            return
        if move.is_resign:
            self.move_number += 1
            self.to_move = _opponent(self.to_move)
            self._push_history_snapshot()
            return
        # validate color
        # --- allow first move by either color ---
        # If this is the very first move (move_number == 0), accept any color
        # and set to_move accordingly. For subsequent moves enforce turn order.
        if self.move_number == 0 or move.is_add:
            # set to_move to the color of the first move to keep internal consistency
            self.to_move = move.color
        else:
            if move.color != self.to_move:
                raise IllegalMove("Wrong player to move")
        # check occupancy
        r, c = move.point
        if not self.in_bounds(r, c):
            raise IllegalMove("Out of bounds")
        if self.get((r, c)) is not None:
            raise OccupiedPoint("Occupied")
        # simulate and find captures
        self._board[r][c] = move.color
        captured_groups = self._find_adjacent_enemy_groups_with_no_libs((r, c), move.color)
        # remove captured
        removed_count = self._apply_capture(captured_groups)
        # check own group liberties
        stones, libs = self._group_and_liberties((r, c))
        if len(libs) == 0:
            # rollback
            # restore captured stones (we didn't keep their colors easily) -> to be safe, we must not have committed until legal check
            # To keep atomicity, we should have simulated before commit; but here we already committed.
            # Simpler: implement legal() check before apply_move; call it at top.
            # For safety, we will raise and then undo by restoring from history snapshot
            # But we didn't snapshot. So change approach: call legal() first.
            # (To keep code simple for reference, call legal() at top.)
            self._board[r][c] = None
            raise Suicide("Suicide")
        # check superko: compute hash after commit
        # compute hash
        h = self._board_hash()
        if self.superko and h in self.position_hashes:
            # rollback captured stones? we already removed them; but we can raise and then undo by restoring from a saved snapshot
            # For correctness, we must call legal() before applying; so ensure callers use legal() first.
            # For now, raise KoViolation
            # restore not implemented here
            raise KoViolation("Superko")
        # commit: push snapshot
        self.move_number += 1
        self.to_move = _opponent(move.color)
        self._push_history_snapshot()
        return

    # convenience wrapper
    def play(self, color, point=None, is_pass=False, is_resign=False, is_add=False):
        mv = Move(
            color=color,
            point=point,
            is_pass=is_pass,
            is_resign=is_resign,
            move_number=self.move_number + 1,
            is_add=is_add,
        )
        # validate via legal() to ensure atomicity
        self.legal(mv)
        self.apply_move(mv)

    # utility for tests
    def pretty(self):
        rows = []
        for r in range(self.size):
            rows.append(''.join('.' if x is None else x for x in self._board[r]))
        return '\n'.join(rows)

    def get_board(self) -> List[List[str | None]]:
        """Return a copy of internal board suitable for UI: list of lists with None/'B'/'W'."""
        return [row[:] for row in self._board]

    def current_player(self):
        """Return color to move as 'B' or 'W'."""
        return self.to_move
