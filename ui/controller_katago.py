# ui/controller_katago.py (updated)
import threading
import time
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
        self._log_lock = threading.RLock()
        self._log_condition = threading.Condition(self._log_lock)

        # moves cache
        self._moves: List[str] = []
        self._current_node: Optional[Node] = None
        # is analysis started
        self._is_analysis_started: bool = False
        self._analysis_color: str | None = None
        self._suggested_moves: Dict[str, List[Tuple[str, dict]]] = {}
        self._suggested_moves_hits: Dict[str, int] = defaultdict(int)
        # backwards analysis
        self._backwards_step_event: Optional[threading.Event] = None

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
                # to not to undo on stop then start and back
                self._moves = []
                self._current_node = None
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
                    wait_returned = self._wait_until_output(
                        lambda output_line: output_line.strip() == "=",
                        timeout=2,
                    )
                    # print("[KatagoController] stop analysis, wait returned:", wait_returned)
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

    def stop_sync_start(self, node_path: List[Node], force_start: bool = False):
        if not (self._is_analysis_started or force_start):
            return
        # if not current tab: return
        if self._is_analysis_started:
            self.stop_analysis()
        self.sync_to_nodes_sequence(node_path)
        self.start_analysis()

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
        """Добавляет строку в буфер и уведомляет ожидающие потоки."""
        with self._log_lock:
            self._log_lines.append(line)
            with self._log_condition:
                self._log_condition.notify_all()

        # вызываем колбэки вне блокировки
        for cb in list(self.on_log_callbacks):
            try:
                cb(line)
            except Exception:
                pass

    def _wait_until_output(self, predicate: Callable[[str], bool], timeout: float | None = None) -> bool:
        """
        Ждёт появления строки target в логах, но только новых записей,
        появившихся после вызова этого метода. Возвращает True если найдено,
        False при таймауте.
        """
        deadline = None if timeout is None else time.time() + timeout
        with self._log_condition:
            start_index = len(self._log_lines)
            while True:
                remaining = None if deadline is None else max(0.0, deadline - time.time())
                if remaining == 0.0:
                    return False
                self._log_condition.wait(timeout=remaining)
                # проверяем только новые записи с индекса start_index
                for ln in self._log_lines[start_index:]:
                    if predicate(ln):
                        return True
                # обновляем start_index, чтобы в следующей итерации смотреть только ещё более новые
                start_index = len(self._log_lines)

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
