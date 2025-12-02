# katago_gtp_wrapper.py
import subprocess
import threading
import re
from typing import Callable, Dict, Any, List, Tuple
from gi.repository import GLib

# Регулярка для парсинга "info move ..." строк
_INFO_MOVE_RE = re.compile(r'^info move\s+(\S+)\s+(.*)$')

def _parse_key_values(s: str) -> Dict[str, str]:
    # простая парсилка ключ-значение, ключи и значения разделены пробелами,
    # pv — может содержать последовательность ходов (буква+число)
    parts = s.split()
    out = {}
    i = 0
    while i < len(parts):
        k = parts[i]
        # ключи в выводе katago бывают без "=", просто имя, затем значение
        # но pv идёт как "pv E16 C14 D15"
        if k == 'pv':
            i += 1
            pv = []
            while i < len(parts) and re.match(r'^[A-Za-z]\d+$', parts[i]):
                pv.append(parts[i])
                i += 1
            out['pv'] = pv
            continue
        # обычный ключ value
        if i+1 < len(parts):
            out[k] = parts[i+1]
            i += 2
        else:
            i += 1
    return out

class KataGoGTP:
    def __init__(self, katago_cmd: List[str], on_update: Callable[[dict], None]=None):
        """
        katago_cmd: список аргументов для subprocess (например ["katago", "gtp", "-config", "cfg"])
        on_update: callback(payload) — вызывается в GLib main loop (через idle_add) при приходе новых данных
        """
        self.katago_cmd = katago_cmd
        self.on_update = on_update
        self.proc = None
        self._reader_thread = None
        self._running = False
        # cache: pos_key -> {move_str: payload}
        self.cache: Dict[str, Dict[str, dict]] = {}

    def start(self):
        if self.proc is not None:
            return
        self.proc = subprocess.Popen(self.katago_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        self._running = True
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def stop(self):
        self._running = False
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass
        self.proc = None

    def send_cmd(self, cmd: str):
        if not self.proc:
            raise RuntimeError("KataGo not started")
        # GTP expects newline-terminated commands
        self.proc.stdin.write(cmd.strip() + "\n")
        self.proc.stdin.flush()

    def analyze(self, color: str, visits: int):
        # wrapper для kata-analyze GTP команды
        self.send_cmd(f"kata-analyze {color} {visits}")

    def _reader_loop(self):
        # читаем stdout построчно, парсим info move строки
        current_pos_key = None
        while self._running and self.proc:
            line = self.proc.stdout.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            # ищем info move
            m = _INFO_MOVE_RE.match(line)
            if m:
                move = m.group(1)
                rest = m.group(2)
                kv = _parse_key_values(rest)
                # payload: нормализуем поля
                payload = {
                    'move': move,
                    'visits': int(kv.get('visits', '0')),
                    'winrate': float(kv.get('winrate', 'nan')),
                    'scoreMean': float(kv.get('scoreMean', 'nan')),
                    'pv': kv.get('pv', []),
                    'raw': kv
                }
                # pos_key: KataGo не даёт позицию в каждой строке в GTP выводе,
                # поэтому мы не можем автоматически привязать к конкретной позиции здесь.
                # Вместо этого мы просто отправляем payload наружу через on_update.
                if self.on_update:
                    # marshal to main loop
                    GLib.idle_add(lambda p=payload: self.on_update(p))
            # else: можно логировать другие строки или stderr
        # reader finished

    def get_cached_for_position(self, pos_key: str) -> Dict[str, dict]:
        # если ты будешь хранить pos_key (например, хеш позиции), можно использовать кэш
        return self.cache.get(pos_key, {})
