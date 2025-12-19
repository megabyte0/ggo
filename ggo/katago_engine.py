# katago_engine.py
# Python 3.8+
import subprocess
import threading
import queue
import json
import time
import os
from typing import Callable, Dict, List, Optional, Any
from dataclasses import dataclass, field

# If using GTK in integration, import GLib for thread->UI dispatch:
try:
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import GLib
except Exception as e:
    print("[Katago engine] import Glib", e)
    GLib = None  # integration code will check and fallback


@dataclass
class EngineConfig:
    binary_path: str
    start_option: Optional[str] = None
    model_file: Optional[str] = None
    config_file: Optional[str] = None
    threads: Optional[int] = None
    extra_args: List[str] = field(default_factory=list)
    working_dir: Optional[str] = None
    env: Optional[Dict[str, str]] = None


@dataclass
class PVMove:
    move: str
    winrate: Optional[float] = None
    visits: Optional[int] = None


@dataclass
class AnalysisUpdate:
    node_id: Optional[str]
    winrate: Optional[float]
    score_lead: Optional[float]
    pv: List[PVMove]
    raw: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class HeatmapData:
    node_id: Optional[str]
    probs: Dict[str, float] = field(default_factory=dict)
    visits: Dict[str, int] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class KataGoEngine:
    """
    Lightweight wrapper around KataGo process.
    - Start/Stop engine process
    - Sync to move sequence (list of moves in GTP or simple coords)
    - Stop analysing variation
    - Callbacks: on_analysis_update, on_heatmap, on_error, on_stopped
    - log property (thread-safe)
    """

    def __init__(self, cfg: EngineConfig):
        self.cfg = cfg
        self._proc: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._writer_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._stdout_queue: "queue.Queue[str]" = queue.Queue()
        self._log_lines: List[str] = []
        self._log_lock = threading.Lock()

        # callbacks
        self.on_analysis_update: Optional[Callable[[AnalysisUpdate], None]] = None
        self.on_heatmap: Optional[Callable[[HeatmapData], None]] = None
        self.on_error: Optional[Callable[[Exception], None]] = None
        self.on_stopped: Optional[Callable[[], None]] = None
        self.on_log_line: Optional[Callable[[str], None]] = None

        # internal state
        self._current_node_id: Optional[str] = None
        self._analysis_lock = threading.Lock()
        self._throttle_interval = 0.25  # seconds, throttle UI updates
        self._last_emit_time = 0.0
        self._pending_update: Optional[AnalysisUpdate] = None

    # -------------------------
    # Logging
    # -------------------------
    def _append_log(self, line: str):
        with self._log_lock:
            # print("[KatagoEngine] _append_log", line)
            self._log_lines.append(line)
            # keep log bounded (optional)
            if len(self._log_lines) > 5000:
                self._log_lines = self._log_lines[-4000:]
            if self.on_log_line is not None:
                self.on_log_line(line)

    @property
    def log(self) -> List[str]:
        with self._log_lock:
            return list(self._log_lines)

    # -------------------------
    # Process management
    # -------------------------
    def start(self) -> None:
        """Start KataGo process. Raises on failure."""
        if self._proc is not None:
            return  # already started

        cmd = [self.cfg.binary_path]
        # prefer JSON analysis mode if available (kata-analyze or analysis engine)
        # Many KataGo builds accept "analysis" JSON mode via --analysis-params or similar.
        # We keep it generic: pass extra args from config.
        if self.cfg.start_option:
            cmd += [self.cfg.start_option]
        if self.cfg.model_file:
            cmd += ["-model", self.cfg.model_file]
        if self.cfg.config_file:
            cmd += ["-config", self.cfg.config_file]
        if self.cfg.threads:
            cmd += ["-threads", str(self.cfg.threads)]
        cmd += list(self.cfg.extra_args)

        env = os.environ.copy()
        if self.cfg.env:
            env.update(self.cfg.env)

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=self.cfg.working_dir,
                env=env,
                bufsize=1,
                universal_newlines=True,
            )
        except Exception as e:
            self._append_log(f"Failed to start KataGo: {e}")
            if self.on_error:
                self.on_error(e)
            raise

        self._stop_event.clear()
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()
        self._append_log("KataGo started")

    def stop(self) -> None:
        """Stop KataGo process gracefully."""
        if self._proc is None:
            return
        try:
            # try to send quit via stdin if supported
            with self._writer_lock:
                if self._proc.stdin:
                    try:
                        self._proc.stdin.write("quit\n")
                        self._proc.stdin.flush()
                    except Exception:
                        pass
            # give it a moment
            time.sleep(0.1)
            if self._proc.poll() is None:
                try:
                    self._proc.terminate()
                except Exception:
                    pass
            # wait briefly
            try:
                self._proc.wait(timeout=2.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        finally:
            self._stop_event.set()
            self._proc = None
            self._append_log("KataGo stopped")
            if self.on_stopped:
                try:
                    self.on_stopped()
                except Exception:
                    pass

    # -------------------------
    # I/O and parsing
    # -------------------------
    def _reader_loop(self):
        """Read stdout lines, parse JSON chunks or GTP responses."""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for raw_line in proc.stdout:
                if raw_line is None:
                    break
                line = raw_line.rstrip("\n")
                self._append_log(line)
                # try parse JSON if line looks like JSON
                stripped = line.strip()
                if not stripped:
                    continue
                # Many KataGo builds emit JSON objects per line for analysis updates.
                if stripped.startswith("{") or stripped.startswith("["):
                    try:
                        obj = json.loads(stripped)
                        self._handle_json_message(obj)
                    except Exception:
                        # not JSON or partial; push to queue for further processing
                        self._stdout_queue.put(line)
                else:
                    # non-json line: push to queue for potential GTP parsing
                    self._stdout_queue.put(line)
                if self._stop_event.is_set():
                    break
        except Exception as e:
            self._append_log(f"Reader loop error: {e}")
            if self.on_error:
                self.on_error(e)
        finally:
            # ensure stopped callback
            if self.on_stopped:
                try:
                    self.on_stopped()
                except Exception:
                    pass

    def _handle_json_message(self, obj: Any):
        """
        Parse JSON messages from KataGo. The exact schema depends on KataGo version.
        We try to extract PV, winrate, scoreLead, visits, and move probabilities.
        """
        try:
            # Example: obj may be {"analysis": {...}} or direct analysis dict
            # Normalize to a dict we can inspect
            data = obj
            if isinstance(obj, dict) and "analysis" in obj:
                data = obj["analysis"]

            # Try to extract node id if present
            node_id = None
            if isinstance(data, dict):
                node_id = data.get("nodeId") or data.get("id") or None

            # Extract winrate/scoreLead
            winrate = None
            score_lead = None
            if isinstance(data, dict):
                if "winrate" in data:
                    try:
                        winrate = float(data["winrate"])
                    except Exception:
                        pass
                if "scoreLead" in data:
                    try:
                        score_lead = float(data["scoreLead"])
                    except Exception:
                        pass

            # Extract PV (principal variation) if present
            pv_list: List[PVMove] = []
            if isinstance(data, dict) and "pv" in data and isinstance(data["pv"], list):
                for mv in data["pv"]:
                    if isinstance(mv, dict):
                        move = mv.get("move") or mv.get("mv") or None
                        wr = mv.get("winrate")
                        visits = mv.get("visits")
                        pv_list.append(PVMove(move=move, winrate=wr, visits=visits))
                    else:
                        pv_list.append(PVMove(move=str(mv)))

            # Extract move probs / visits for heatmap
            probs = {}
            visits = {}
            if isinstance(data, dict) and "moveInfos" in data and isinstance(data["moveInfos"], dict):
                for coord, info in data["moveInfos"].items():
                    try:
                        probs[coord] = float(info.get("winrate", info.get("scoreLead", 0.0)))
                    except Exception:
                        probs[coord] = 0.0
                    try:
                        visits[coord] = int(info.get("visits", 0))
                    except Exception:
                        visits[coord] = 0

            update = AnalysisUpdate(
                node_id=node_id,
                winrate=winrate,
                score_lead=score_lead,
                pv=pv_list,
                raw=data,
            )

            # throttle emission to UI
            now = time.time()
            with self._analysis_lock:
                self._pending_update = update
                if now - self._last_emit_time >= self._throttle_interval:
                    self._emit_pending_update()
                else:
                    # schedule delayed emission in background thread
                    threading.Timer(self._throttle_interval, self._emit_pending_update).start()
        except Exception as e:
            self._append_log(f"JSON parse error: {e}")
            if self.on_error:
                self.on_error(e)

    def _emit_pending_update(self):
        with self._analysis_lock:
            upd = self._pending_update
            self._pending_update = None
            self._last_emit_time = time.time()
        if upd is None:
            return
        # call callback in main thread if GLib available
        if self.on_analysis_update:
            try:
                if GLib is not None:
                    GLib.idle_add(lambda: self.on_analysis_update(upd))
                else:
                    # call directly (user must ensure thread-safety)
                    self.on_analysis_update(upd)
            except Exception as e:
                self._append_log(f"on_analysis_update callback error: {e}")
                if self.on_error:
                    self.on_error(e)

        # also produce heatmap if moveInfos present in raw
        try:
            raw = upd.raw or {}
            if isinstance(raw, dict) and "moveInfos" in raw:
                probs = {}
                visits = {}
                for coord, info in raw["moveInfos"].items():
                    try:
                        probs[coord] = float(info.get("winrate", 0.0))
                    except Exception:
                        probs[coord] = 0.0
                    try:
                        visits[coord] = int(info.get("visits", 0))
                    except Exception:
                        visits[coord] = 0
                heat = HeatmapData(node_id=upd.node_id, probs=probs, visits=visits, raw=raw)
                if self.on_heatmap:
                    if GLib is not None:
                        GLib.idle_add(lambda: self.on_heatmap(heat))
                    else:
                        self.on_heatmap(heat)
        except Exception as e:
            self._append_log(f"heatmap creation error: {e}")
            if self.on_error:
                self.on_error(e)

    # -------------------------
    # Commands to engine
    # -------------------------
    def _send_line(self, line: str):
        """Send a raw line to engine stdin (thread-safe)."""
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("Engine not running")
        with self._writer_lock:
            try:
                self._proc.stdin.write(line + "\n")
                self._proc.stdin.flush()
                self._append_log(line)
            except Exception as e:
                self._append_log(f"Failed to write to engine stdin: {e}")
                if self.on_error:
                    self.on_error(e)

    def sync_to_move_sequence(self, moves: List[str], node_id: Optional[str] = None,
                              analysis_params: Optional[Dict[str, Any]] = None):
        """
        Sync engine to a sequence of moves.
        moves: list of moves in GTP coords (e.g., 'B D4', or 'D4' depending on engine).
        node_id: optional identifier to attach to subsequent analysis updates.
        analysis_params: optional dict with analysis options (visits, timeMs, etc).
        """
        if self._proc is None:
            raise RuntimeError("Engine not running")
        # Clear board and play moves
        try:
            # Use GTP style commands if engine supports them
            # Many KataGo builds accept "clear_board" and "play" commands
            self._send_line("clear_board")
            for mv in moves:
                # mv may be like "B D4" or "D4" — try to be flexible
                if isinstance(mv, str) and mv.strip():
                    if mv.strip().upper().startswith(("B ", "W ")):
                        self._send_line(f"play {mv.strip()}")
                    else:
                        # assume alternating colors starting with B
                        # but better to accept explicit color in moves list
                        self._send_line(f"play {mv.strip()}")
            # request analysis: many KataGo builds support "kata-analyze" or "lz-analyze" style
            # We'll try a generic JSON analysis request if supported by the binary via "kata-analyze"
            # Fallback: send "genmove" or "analyze" depending on engine
            # Attach node id by sending a comment line (not standard) — instead we store locally
            self._current_node_id = node_id
            # Build analysis command
            if analysis_params is None:
                analysis_params = {"visits": 100, "timeMs": 2000}
            # Try JSON analysis command
            try:
                cmd = {"id": "analysis", "method": "katagoAnalysis", "params": analysis_params}
                # Some KataGo builds accept JSON lines; otherwise user can override extra_args to enable JSON mode
                self._send_line(json.dumps(cmd))
            except Exception:
                # fallback: try "kata-analyze" textual command
                self._send_line("kata-analyze")
        except Exception as e:
            self._append_log(f"sync_to_move_sequence error: {e}")
            if self.on_error:
                self.on_error(e)

    def stop_analysing_variation(self):
        """Stop current variation analysis (best-effort)."""
        # Many engines accept "stop" or "kata-stop" commands; try common ones
        try:
            if self._proc is None:
                return
            # generic stop
            self._send_line("stop")
            # some builds accept "kata-stop"
            self._send_line("kata-stop")
        except Exception as e:
            self._append_log(f"stop_analysing_variation error: {e}")
            if self.on_error:
                self.on_error(e)
