# ui/controller_katago.py
import threading
from typing import Optional, Callable, List, Dict, Any

# импорт вашего движка (предположительно katago_engine.KataGoEngine)
from ggo.katago_engine import KataGoEngine, EngineConfig

# Для примера, если у вас нет katago_engine, можно мокать поведение.
# Здесь предполагается, что KataGoEngine имеет: start(), stop(), sync_to_move_sequence(...),
# stop_analysing_variation(), и генерирует лог строки через callback on_log_line (необязательно).
# Подстройте под реальную реализацию.

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
        self.on_analysis_update = None
        self.on_heatmap = None
        self.on_error = None
        self.on_stopped = None

        # internal log buffer
        self._log_lines: List[str] = []
        self._log_lock = threading.Lock()

    # -------------------------
    # lifecycle
    # -------------------------
    def start(self):
        with self._engine_lock:
            if self._engine is not None:
                self._emit_log("KatagoController: engine already running")
                return
            # create and start engine here
            # Example (adapt to your engine):
            cfg_obj = EngineConfig(
                binary_path=self.cfg["binary_path"],
                start_option=self.cfg["start_option"],
                config_file=self.cfg.get("config_file"),
                model_file=self.cfg.get("model_file"),
            )
            self._engine = KataGoEngine(cfg_obj)
            # self._engine.on_analysis_update = self._on_analysis_update
            # self._engine.on_heatmap = self._on_heatmap
            # self._engine.on_error = self._on_error
            self._engine.on_log_line = self._on_engine_log_line  # if engine supports
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
            finally:
                self._engine = None
                if self.on_stopped:
                    try:
                        self.on_stopped()
                    except Exception:
                        pass

    def stop_analysing_variation(self):
        with self._engine_lock:
            if self._engine:
                try:
                    # self._engine.stop_analysing_variation()
                    self._emit_log("KatagoController: stop analysing variation requested")
                except Exception as e:
                    self._emit_log(f"KatagoController error: {e}")

    def sync_to_move_sequence(self, moves: List[str], node_id: Optional[str] = None, params: Optional[Dict[str, Any]] = None):
        with self._engine_lock:
            if not self._engine:
                self._emit_log("KatagoController: engine not running; cannot sync")
                return
            try:
                # self._engine.sync_to_move_sequence(moves, node_id=node_id, analysis_params=params)
                self._emit_log(f"KatagoController: sync_to_move_sequence for node {node_id}")
            except Exception as e:
                self._emit_log(f"KatagoController sync error: {e}")
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

    # optional: expose snapshot of log
    def get_log(self) -> List[str]:
        with self._log_lock:
            return list(self._log_lines)

    # engine callbacks (if engine provides raw lines)
    def _on_engine_log_line(self, line: str):
        # called from engine thread; safe to call _emit_log
        self._emit_log(line)

    # placeholders for analysis/heatmap callbacks
    def _on_analysis_update(self, update):
        if self.on_analysis_update:
            try:
                self.on_analysis_update(update)
            except Exception:
                pass

    def _on_heatmap(self, heat):
        if self.on_heatmap:
            try:
                self.on_heatmap(heat)
            except Exception:
                pass

    def _on_error(self, err):
        self._emit_log(f"KatagoController error: {err}")
        if self.on_error:
            try:
                self.on_error(err)
            except Exception:
                pass
