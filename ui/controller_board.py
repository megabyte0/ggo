# ui/controller_board.py
import copy
from ggo import goban_model
from typing import Tuple, List, Optional, Any, Dict
from ggo.goban_model import Board, IllegalMove
from ui.board_view import BoardView

DEBUG = False


class BoardAdapter:
    """
    Адаптер для BoardView + Board model.
    Отвечает за:
      - хранение модели Board
      - применение одиночных ходов и пачек камней (AB/AW)
      - интерфейс, ожидаемый контроллером: play_move, set_stones, reset, place_black/place_white, show ghost
    """

    def __init__(self, board_view, board_size: int = 19):
        self.view: BoardView = board_view
        self.model: Board = Board(size=board_size)
        # board_view expected API: on_click(cb), on_hover(cb), on_leave(cb), set_board(board), queue_draw()
        # If view has different API, adapt here.
        self.size = board_size

    # --- model/view helpers ---
    def reset(self):
        if DEBUG:
            print("[BoardAdapter] reset model")
        self.model = Board(size=self.size)
        self.view.set_last_stone(None)
        if hasattr(self.view, "clear_board"):
            try:
                self.view.clear_board()
            except Exception:
                pass
        if hasattr(self.view, "queue_draw"):
            try:
                self.view.queue_draw()
            except Exception:
                pass

    def play_move(self, color: str, rc: Tuple[int, int]) -> bool:
        """Try to play a move on the model. Returns True if applied, False if illegal."""
        r, c = rc
        try:
            self.model.play(color, point=(r, c))
            self.view.set_last_stone((r, c, color))
            self.view.clear_ghost()
            if hasattr(self.view, "place_black") and color == "B":
                try:
                    self.view.place_black(r, c)
                except Exception:
                    pass
            if hasattr(self.view, "place_white") and color == "W":
                try:
                    self.view.place_white(r, c)
                except Exception:
                    pass
            if hasattr(self.view, "queue_draw"):
                try:
                    self.view.queue_draw()
                except Exception:
                    pass
            return True
        except IllegalMove as e:
            if DEBUG:
                print("[BoardAdapter] IllegalMove:", e)
            return False

    def set_stones(self, stones: List[Tuple[str, Tuple[int, int]]]):
        """
        stones: list of ("B"/"W", (r,c))
        Apply stones to model and view (batch).
        """
        if DEBUG:
            print("[BoardAdapter] set_stones:", stones)
        # reset model first (handicap usually applied on empty board)
        self.reset()
        for color, (r, c) in stones:
            try:
                # try to set directly in model if API exists
                if hasattr(self.model, "set_black") and color == "B":
                    self.model.set_black(r, c)
                elif hasattr(self.model, "set_white") and color == "W":
                    self.model.set_white(r, c)
                else:
                    # fallback to play (may check legality)
                    self.model.play(color, point=(r, c))
            except Exception:
                # ignore illegal handicap placements
                pass
            # update view
            if color == "B" and hasattr(self.view, "place_black"):
                try:
                    self.view.place_black(r, c)
                except Exception:
                    pass
            if color == "W" and hasattr(self.view, "place_white"):
                try:
                    self.view.place_white(r, c)
                except Exception:
                    pass
        if hasattr(self.view, "queue_draw"):
            try:
                self.view.queue_draw()
            except Exception:
                pass

    def place_black(self, r: int, c: int):
        try:
            if hasattr(self.model, "set_black"):
                self.model.set_black(r, c)
            else:
                self.model.play('B', point=(r, c))
        except Exception:
            pass
        if hasattr(self.view, "place_black"):
            try:
                self.view.place_black(r, c)
            except Exception:
                pass
        if hasattr(self.view, "queue_draw"):
            try:
                self.view.queue_draw()
            except Exception:
                pass

    def place_white(self, r: int, c: int):
        try:
            if hasattr(self.model, "set_white"):
                self.model.set_white(r, c)
            else:
                self.model.play('W', point=(r, c))
        except Exception:
            pass
        if hasattr(self.view, "place_white"):
            try:
                self.view.place_white(r, c)
            except Exception:
                pass
        if hasattr(self.view, "queue_draw"):
            try:
                self.view.queue_draw()
            except Exception:
                pass

    # helpers for controller
    def current_player(self) -> str:
        return self.model.current_player()

    def get_board(self):
        return self.model.get_board()

    def queue_view_draw(self):
        self.view.darea.queue_draw()

    def play_variation(self, variation):
        print("[ControllerBoard] play_variation", variation)
        try:
            self.view.stop_variation_playback()
        except Exception as e:
            print("[View] stop_variation_playback", e)
            pass
        if not variation: return
        sim = self.simulate_variation_on_model(variation)
        if sim:
            try:
                self.view.start_variation_playback_sim(sim)
            except Exception as e:
                print("[View] start_variation_playback_sim", e)
                pass
        else:
            try:
                self.view.stop_variation_playback()
            except Exception as e:
                print("[View] stop_variation_playback", e)
                pass

    def simulate_variation_on_model(self, variation):
        if not hasattr(self, 'model') or self.model is None:
            raise RuntimeError("No model for simulation")
        base: Board = copy.deepcopy(self.model)
        size = base.size

        def snapshot(b: Board):
            return b.get_board()

        states = []
        variation_move_number: Dict[Tuple[int, int], int] = {}
        for idx, item in enumerate(variation, start=1):
            player = base.current_player()
            if isinstance(item, tuple):
                p16 = item[0]
                props = item[1] if len(item) > 1 else {}
            else:
                p16 = item
                props = {}
            rc = self.view.parse_point(p16)
            if rc is None: break
            r, c = rc
            color = player
            try:
                base.play(color, (r, c))
            except Exception:
                break
            new_state = snapshot(base)
            variation_move_number[rc] = idx
            states.append((new_state, dict(variation_move_number)))
        return states
