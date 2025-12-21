# ui/controller_katago.py (updated)
import threading
from collections import defaultdict
from typing import Optional, Callable, List, Dict, Any, Tuple

from ggo.game_tree import Node
from ggo.katago_engine import KataGoEngine, EngineConfig

class KatagoController:
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, cfg: Optional[Dict[str, Any]] = None):
        with cls._lock:
            if cls._instance is None:
                if cfg is None:
                    raise RuntimeError("First call to get_instance must provide cfg")
                cls._instance = cls(cfg)
            return cls._instance

    def __init__(self, cfg: Dict[str, Any]):
        # cfg: dict with keys like binary_path, model_file, threads, extra_args...
        self.cfg = cfg
        self._engine: Optional[KataGoEngine] = None  # will hold KataGoEngine instance
        self._engine_lock = threading.Lock()
        self.on_log_callbacks: List[Callable[[str], None]] = []
        self.on_move_info: Optional[Callable[[], None]] = None
        self.on_error = None
        self.on_stopped = None

        # internal log buffer
        self._log_lines: List[str] = []
        self._log_lock = threading.Lock()

        # moves cache
        self._moves: List[str] = []
        self._current_node: Optional[Node] = None
        # is analysis started
        self._is_analysis_started: bool = False
        self._analysis_color: str | None = None
        self._suggested_moves: Dict[str, List[Tuple[str, dict]]] = {}
        self._suggested_moves_hits: Dict[str, int] = defaultdict(int)

    # -------------------------
    # lifecycle
    # -------------------------
    def start(self):
        with self._engine_lock:
            if self._engine is not None:
                self._emit_log("KatagoController: engine already running")
                return
            cfg_obj = EngineConfig(
                binary_path=self.cfg["binary_path"],
                start_option=self.cfg["start_option"],
                config_file=self.cfg.get("config_file"),
                model_file=self.cfg.get("model_file"),
            )
            self._engine = KataGoEngine(cfg_obj)
            self._engine.on_log_line = self._on_engine_log_line
            self._engine.on_move_info = self._on_engine_move_info
            self._engine.on_error = self._on_error
            self._engine.start()
            self._emit_log("KatagoController: start requested")

    def stop(self):
        with self._engine_lock:
            if self._engine is None:
                self._emit_log("KatagoController: engine not running")
                return
            try:
                self._engine.stop()
                self._emit_log("KatagoController: stop requested")
                self._is_analysis_started = False
            finally:
                self._engine = None
                if self.on_stopped:
                    try:
                        self.on_stopped()
                    except Exception:
                        pass

    def stop_analysis(self):
        with self._engine_lock:
            if self._engine:
                try:
                    self._emit_log("KatagoController: stop analysis requested")
                    self._engine.stop_analysing_variation()
                    # wait here for output_line.strip() == "="
                    self._is_analysis_started = False
                except Exception as e:
                    self._emit_log(f"KatagoController error: {e}")

    def _sync_to_move_sequence(self, moves: List[str], node_id: Optional[str] = None):
        with self._engine_lock:
            if not self._engine:
                self._emit_log("KatagoController: engine not running; cannot sync")
                return
            try:
                index = -1
                for n, (move, old_move) in enumerate(zip(moves, self._moves)):
                    if move == old_move:
                        index = n
                    else:
                        break
                if index == -1:
                    self._engine.clear_board()
                    self._moves = []
                else:
                    for i in range(index + 1, len(self._moves)):
                        self._engine.undo_move()
                        self._moves = self._moves[:-1]
                for move in moves[index + 1:]:
                    self._engine.play_move(move)
                    self._moves.append(move)
                # self._engine.sync_to_move_sequence(moves, node_id=node_id, analysis_params=params)
                self._emit_log(f"KatagoController: sync_to_move_sequence for node {node_id}")
            except Exception as e:
                self._emit_log(f"KatagoController sync error: {e}")

    def sync_to_nodes_sequence(self, node_path: List[Node]):
        moves_seq = [
            f"{color} {board_coord_notation}"
            for color, sgf_move_notation, (row, col), board_coord_notation in (
                move_node.get_move()
                for move_node in node_path
                if move_node.get_move() is not None
            )
        ]
        self._sync_to_move_sequence(moves_seq)
        self._current_node = node_path[-1]

    @property
    def current_node(self):
        # for verifying if to update the board ui on backward analysis
        return self._current_node

    @property
    def analysis_color(self):
        return self._analysis_color

    def start_analysis(self, color: str | None = None):
        with self._engine_lock:
            if not self._engine:
                self._emit_log("KatagoController: engine not running; cannot start analysis")
                return
            try:
                if color is None:
                    if not self._moves:
                        color = "B"
                    else:
                        color = {"B": "W", "W": "B"}[self._moves[-1][0]]
                self._suggested_moves = {}
                self._suggested_moves_hits = defaultdict(int)
                self._engine.start_analysis(color)
                self._analysis_color = color
                self._is_analysis_started = True
                self._emit_log(f"KatagoController: analysis starting for color {color}")
            except Exception as e:
                self._emit_log(f"KatagoController analysis start error: {e}")

    # -------------------------
    # log subscribe
    # -------------------------
    def subscribe_to_log(self, cb: Callable[[str], None]):
        self.on_log_callbacks.append(cb)

    def unsubscribe_to_log(self, cb: Callable[[str], None]):
        self.on_log_callbacks.remove(cb)

    # -------------------------
    # internal log handling
    # -------------------------
    def _emit_log(self, line: str):
        with self._log_lock:
            self._log_lines.append(line)
            if len(self._log_lines) > 5000:
                self._log_lines = self._log_lines[-4000:]
        # call external callback if present
        for cb in self.on_log_callbacks:
            try:
                cb(line)
            except Exception:
                pass
        # print("KataGoController log: %r" % line)

    def _on_engine_log_line(self, line: str):
        # called from engine thread; safe to call _emit_log
        self._emit_log(line)

    def _on_engine_move_info(self, move_info: List[Tuple[str, dict]]):
        if not move_info:
            return
        first_move = move_info[0][0]
        self._suggested_moves[first_move] = move_info
        self._suggested_moves_hits[first_move] += 1
        # print(
        #     dict(self._suggested_moves_hits),
        #     {
        #         move: v[0][1]['visits']
        #         for move, v in self._suggested_moves.items()
        #     }
        # )
        # forward to external subscriber
        if self.on_move_info:
            try:
                self.on_move_info()
            except Exception as e:
                self._emit_log(f"on_move_info handler error: {e}")

    def _on_error(self, err):
        self._emit_log(f"KatagoController error: {err}")
        if self.on_error:
            try:
                self.on_error(err)
            except Exception:
                pass
