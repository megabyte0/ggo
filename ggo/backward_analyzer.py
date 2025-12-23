# backward_analyzer_katago_resolver.py
import threading
import time
from typing import Callable, Optional, List
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib
from ui.controller_katago import KatagoController


class BackwardAnalyzer:
    """
    button         Gtk.Button (или объект с set_label)
    current_node_resolver  callable[[], Optional[Node]] — возвращает текущую ноду (может возвращать None)
    kc_resolver    optional callable[[], Optional[KatagoController]] — как получить контроллер (если None, класс попытается импортировать KatagoController.get_instance)
    ggnv_threshold порог (int), per_node_timeout таймаут ожидания GGNV в секундах
    """

    def __init__(self,
                 button,
                 current_node_resolver: Callable[[], Optional[object]],
                 *,
                 ggnv_threshold: int = 1000,
                 per_node_timeout: float = 60.0):
        self.button = button
        self._get_current_node = current_node_resolver
        self.ggnv_threshold = int(ggnv_threshold)
        self.per_node_timeout = float(per_node_timeout)

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._step_event = threading.Event()
        self._running_lock = threading.Lock()
        self._running = False

        # начальная метка
        try:
            self.button.set_label("<|")
        except Exception:
            pass

        try:
            self.button.connect("clicked", lambda btn: self.toggle())
        except Exception:
            pass

    # --- публичные методы ---
    def start(self):
        with self._running_lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()
            self._step_event.clear()
            print("Setting the label in start")
            GLib.idle_add(self._set_button_label, "…")
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()

    def stop(self):
        with self._running_lock:
            if not self._running:
                return
            kc = self._resolve_kc_once()
            kc.stop_analysis()
            self._stop_event.set()
            try:
                self._step_event.set()
            except Exception:
                pass
            self._running = False
            print("Setting the label in stop")
            GLib.idle_add(self._set_button_label, "<|")

    def toggle(self):
        if self.is_running():
            self.stop()
        else:
            self.start()

    def is_running(self) -> bool:
        with self._running_lock:
            return self._running

    # --- внутренние ---
    def _set_button_label(self, text: str):
        try:
            self.button.set_label(text)
        except Exception:
            pass
        return False

    def _resolve_kc_once(self):
        try:
            return KatagoController.get_instance()
        except Exception:
            print("KatagoEngine not started")
            return None

    def _node_path(self, node) -> List:
        path = []
        n = node
        while n is not None:
            path.insert(0, n)
            n = getattr(n, "parent", None)
        return path

    def _count_remaining(self, node) -> int:
        """Считает ноды от node до root с GGNV < threshold."""
        cnt = 0
        n = node
        while n is not None:
            try:
                raw = (n.get_prop("GGNV") or [None])[0]
                val = int(raw) if raw is not None else 0
            except Exception:
                val = 0
            if val < self.ggnv_threshold:
                cnt += 1
            n = getattr(n, "parent", None)
        return cnt

    def _worker(self):
        kc = self._resolve_kc_once()
        if kc is None:
            print("Setting the label in worker start, kc is None")
            GLib.idle_add(self._set_button_label, "<|")
            with self._running_lock:
                self._running = False
            return

        # передаём event в контроллер (best-effort) — контроллер должен вызывать ev.set() при достижении GGNV
        try:
            setattr(kc, "_backwards_step_event", self._step_event)
        except Exception as e:
            print(" setattr kc._backwards_step_event:", e)
            pass

        # стартовая нода берётся через переданный резолвер
        node = None
        try:
            node = self._get_current_node()
        except Exception:
            node = None

        # если резолвер вернул None — завершаем
        if node is None:
            print("Setting the label in worker, resolver returned None")
            GLib.idle_add(self._set_button_label, "<|")
            with self._running_lock:
                self._running = False
            try:
                delattr(kc, "_backwards_step_event")
            except Exception:
                pass
            return

        # основной цикл: пропускаем ноды с GGNV >= threshold (включая стартовую)
        while not (node is None or node.parent is None or self._stop_event.is_set()):
            print("Current node is", node)
            # если текущая нода уже проанализирована — пропускаем её сразу
            try:
                raw = (node.get_prop("GGNV") or [None])[0]
                ggnv = int(raw) if raw is not None else 0
            except Exception:
                ggnv = 0

            if ggnv >= self.ggnv_threshold:
                node = getattr(node, "parent", None)
                print("(1) Skipping the current with ggnv =", ggnv)
                continue  # пропускаем и идём дальше

            # обновим метку кнопки — число оставшихся ходов (включая эту)
            remaining = self._count_remaining(node)
            GLib.idle_add(self._set_button_label, str(remaining))

            # синхронизируем движок на path и стартуем анализ
            path = self._node_path(node)
            try:
                kc.stop_sync_start(path, force_start=True)
            except Exception:
                # если метод отсутствует или падает — продолжаем ожидание GGNV
                pass

            # быстрый прямой чек GGNV
            try:
                raw = (node.get_prop("GGNV") or [None])[0]
                ggnv = int(raw) if raw is not None else 0
            except Exception:
                ggnv = 0

            if ggnv >= self.ggnv_threshold:
                # если порог уже достигнут (включая случай, когда он был достигнут до старта анализа),
                # просто переходим к родителю
                node = getattr(node, "parent", None)
                print("(2) Skipping the current with ggnv =", ggnv)
                continue

            # иначе ждём сигнала от контроллера или опрашиваем
            ev = getattr(kc, "_backwards_step_event", None)
            reached = False
            if isinstance(ev, threading.Event):
                try:
                    ev.clear()
                except Exception:
                    pass
                ev.wait(timeout=self.per_node_timeout)
                try:
                    raw = (node.get_prop("GGNV") or [None])[0]
                    ggnv = int(raw) if raw is not None else 0
                except Exception:
                    ggnv = 0
                reached = (ggnv >= self.ggnv_threshold)
                print("(1) Reached is set to", reached)
            else:
                print("fallback query node")
                # fallback: опрос
                t0 = time.time()
                while time.time() - t0 < self.per_node_timeout and not self._stop_event.is_set():
                    try:
                        raw = (node.get_prop("GGNV") or [None])[0]
                        if raw is not None and int(raw) >= self.ggnv_threshold:
                            reached = True
                            break
                    except Exception:
                        pass
                    time.sleep(0.4)

            if self._stop_event.is_set():
                break

            if reached:
                node = getattr(node, "parent", None)
            else:
                print("Break on non reached")
                break

        # cleanup
        kc.stop_analysis()
        try:
            delattr(kc, "_backwards_step_event")
        except Exception:
            pass
        print("Setting the label in worker cleanup")
        GLib.idle_add(self._set_button_label, "<|")
        with self._running_lock:
            self._running = False
