# simplified katago_engine.py
import re
import subprocess
import threading
import queue
import time
import os
from decimal import Decimal
from typing import Callable, Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field


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


class KataGoEngine:
    def __init__(self, cfg: EngineConfig):
        self.cfg = cfg
        self._proc: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._writer_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._log_lines: List[str] = []
        self._log_lock = threading.Lock()

        # callbacks
        self.on_move_info: Optional[Callable[[List[Tuple[str, dict]]], None]] = None
        self.on_log_line: Optional[Callable[[str], None]] = None
        self.on_error: Optional[Callable[[Exception], None]] = None
        self.on_stopped: Optional[Callable[[], None]] = None

        # build parsers
        self._build_move_info_matchers()

    def _append_log(self, line: str):
        with self._log_lock:
            info_move_log_line = "info move \u2026"
            if line.startswith("info move "):
                if (
                        self._log_lines
                        and self._log_lines[-1] == info_move_log_line
                ):
                    line = None
                else:
                    line = info_move_log_line
            if line is None:
                return
            self._log_lines.append(line)
        if self.on_log_line:
            try:
                self.on_log_line(line)
            except Exception:
                pass

    def start(self) -> None:
        if self._proc is not None:
            return
        cmd = [self.cfg.binary_path]
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
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, cwd=self.cfg.working_dir, env=env,
                bufsize=1, universal_newlines=True
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
                        self._append_log("quit")
                    except Exception:
                        pass
            # give it a moment
            time.sleep(1.1)
            if self._proc.poll() is None:
                try:
                    self._proc.terminate()
                    self._append_log("terminating the process")
                except Exception:
                    pass
            # wait briefly
            try:
                self._proc.wait(timeout=2.0)
            except Exception:
                try:
                    self._proc.kill()
                    self._append_log("killing the process")
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

    def _reader_loop(self):
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for raw_line in proc.stdout:
                if raw_line is None:
                    break
                line = raw_line.rstrip("\n")
                self._append_log(line)
                stripped = line.strip()
                if not stripped:
                    continue
                if line.startswith("info move "):
                    try:
                        parsed = self._parse_move_info(line)
                        if self.on_move_info:
                            try:
                                self.on_move_info(parsed)
                            except Exception as cb_e:
                                self._append_log(f"on_move_info callback error: {cb_e}")
                                if self.on_error:
                                    self.on_error(cb_e)
                    except Exception as e:
                        self._append_log(f"parse move info error: {e}")
                        if self.on_error:
                            self.on_error(e)
                else:
                    # other lines ignored for now
                    pass
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

    def _build_move_info_matchers(self):
        move = (r'(?:[A-HJ-T]\d{1,2}|pass)', lambda s: s)
        _float = (r'-?\d+(?:\.\d+)?(?:e-?\d+)?', Decimal)
        _int = (r'\d+', int)
        moves = (r'(?:%s\ )*%s' % ((move[0],) * 2), lambda s: s.split(' '))
        self._info_move_dict = {
            'visits': _int,
            'edgeVisits': _int,
            'utility': _float,
            'winrate': _float,
            'scoreMean': _float,
            'scoreStdev': _float,
            'scoreLead': _float,
            'scoreSelfplay': _float,
            'prior': _float,
            'lcb': _float,
            'utilityLcb': _float,
            'weight': _float,
            'order': _int,
            'pv': moves,
            'isSymmetryOf': move,
        }
        self._info_move_matcher = re.compile(r'\s*info move (%s) ' % (move[0]))
        info_move_parser_str = '(%s)' % ('|'.join(
            '%s %s' % (k, _re)
            for k, (_re, _fn) in self._info_move_dict.items()
        ))
        self._info_move_parser = re.compile(info_move_parser_str)

    def _parse_move_info(self, line) -> List[Tuple[str, dict]]:
        _split = self._info_move_matcher.split(line)
        assert _split[0] == ''
        _split = _split[1:]
        result = []
        for move, props_raw in zip(_split[::2], _split[1::2]):
            props_split = self._info_move_parser.split(props_raw)
            not_parsed = [i for i in props_split[::2] if i.strip() != '']
            # if not_parsed:
            #     print(not_parsed)
            assert not not_parsed, not_parsed
            props_split = props_split[1::2]
            move_dict = {
                key: self._info_move_dict[key][1](value)
                for key, value in (i.split(' ', 1) for i in props_split)
            }
            result.append((move, move_dict))
        return result

    def _send_line(self, line: str):
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

    def play_move(self, move: str):
        if self._proc is None:
            raise RuntimeError("Engine not running")
        try:
            self._send_line(f"play {move}")
        except Exception as e:
            self._append_log(f"play_move error: {e}")
            if self.on_error:
                self.on_error(e)

    def undo_move(self):
        if self._proc is None:
            raise RuntimeError("Engine not running")
        try:
            self._send_line("undo")
        except Exception as e:
            self._append_log(f"undo error: {e}")
            if self.on_error:
                self.on_error(e)

    def clear_board(self):
        if self._proc is None:
            raise RuntimeError("Engine not running")
        try:
            self._send_line("clear_board")
        except Exception as e:
            self._append_log(f"clear_board error: {e}")
            if self.on_error:
                self.on_error(e)

    def start_analysis(self, color):
        if self._proc is None:
            raise RuntimeError("Engine not running")
        try:
            self._send_line(f"kata-analyze {color} 50")
        except Exception as e:
            self._append_log(f"kata-analyze error: {e}")
            if self.on_error:
                self.on_error(e)

    def stop_analysing_variation(self):
        if self._proc is None:
            raise RuntimeError("Engine not running")
        try:
            self._send_line("stop")
        except Exception as e:
            self._append_log(f"stop_analysing_variation error: {e}")
            if self.on_error:
                self.on_error(e)
