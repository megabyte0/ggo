from typing import Optional, Callable

import gi

from ggo.game_tree import GameTree, Node
from ui.board_view import BoardView
from ui.controller import Controller
from ui.controller_katago import KatagoController
from ui.game_tab import GameTab
from ui.tree_canvas import TreeCanvas

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib


class AnalysisBox(Gtk.Box):
    def __init__(self, main_window: Gtk.ApplicationWindow):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.controller: Optional[Controller] = None
        self.board_view: Optional[BoardView] = None
        self.tree_canvas: Optional[TreeCanvas] = None
        self.game_tab: Optional[GameTab] = None
        self.btn_last: Optional[Gtk.Button] = None
        self.btn_next: Optional[Gtk.Button] = None
        self.btn_prev: Optional[Gtk.Button] = None
        self.btn_first: Optional[Gtk.Button] = None
        self.lbl_scorelead: Optional[Gtk.Label] = None
        self.lbl_winprob: Optional[Gtk.Label] = None
        self.var_list: Optional[Gtk.ListBox] = None
        self.var_scroller: Optional[Gtk.ScrolledWindow] = None
        self.main_window = main_window
        self.btn_katago_start: Optional[Gtk.Button] = None
        self.btn_katago_stop: Optional[Gtk.Button] = None
        self.log_view: Optional[Gtk.TextView] = None
        self.log_buffer: Optional[Gtk.TextBuffer] = None
        self.build_analysis_box()

    def build_analysis_box(self) -> Gtk.Box:
        def get_game_tree():
            return self.controller.get_game_tree()

        # Создаём board_view и контроллер раньше, чтобы callback'и могли к ним обращаться
        self.board_view = BoardView(board_size=19)
        print("[main_app] board_view id:", id(self.board_view))

        # Создаём контроллер сразу — он может понадобиться в callback'ах загрузки
        self.controller = Controller(self.board_view)
        print("[main_app] controller id:", id(self.controller))

        # Теперь строим analysis_box (внутри него создаётся TreeCanvas и кнопки)
        # основной горизонтальный анализ-бокс: слева katago, центр доска, справа графики/дерево
        analysis_box = self  # Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        left_panel = self.build_left_panel()
        analysis_box.append(left_panel)

        # center board + top info + nav (nav только под гобаном)
        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        top_info = self.build_top_info_labels()
        center.append(top_info)

        # board itself
        center.append(self.board_view)

        nav = self.build_nav_buttons()
        center.append(nav)

        analysis_box.append(center)

        right_panel = self.build_right_panel(get_game_tree)
        analysis_box.append(right_panel)

        self._wire_game_tab_callbacks(analysis_box)

        # attach tree canvas to controller (контроллер будет обновлять дерево при необходимости)
        self.controller.attach_tree_canvas(self.tree_canvas)

        # подключаем кнопки навигации
        self._wire_nav_buttons()

        return analysis_box

    def _wire_game_tab_callbacks(self, analysis_box):
        # callback: переименовать вкладку
        def rename_tab(basename: str):
            try:
                self.notebook.set_tab_label_text(analysis_box, basename)  # ! .notebook does not exist
            except Exception:
                pass

        # on_game_loaded: надёжно обновляет TreeCanvas и уведомляет контроллер
        def on_game_loaded(gt):
            # лог для отладки
            print("[MainWindow] on_game_loaded called. gt:", type(gt), "root:", getattr(gt, "root", None))
            if gt is None:
                print("[MainWindow] GameTree is None — parser failed or not available")
                return

            root = getattr(gt, "root", None)
            if root is None:
                print("[MainWindow] gt.root is None — nothing to show")
                return

            # Попробуем вывести количество детей (если есть)
            try:
                children = getattr(root, "children", None)
                cnt = len(children) if children is not None else 0
                print(f"[MainWindow] root children count: {cnt}")
            except Exception as e:
                print("[MainWindow] error reading root.children:", e)

            # Обновляем TreeCanvas
            try:
                # print("[MainWindow] setting tree root", id(self.tree_canvas.root), "to", id(root))
                game_tree = self.controller.get_game_tree()
                for root_child in game_tree.root.children:
                    game_tree._sync_is_current(root_child)
                # на всякий случай форсируем пересчёт и перерисовку
                try:
                    self.tree_canvas._recompute_layout()
                except Exception:
                    pass
                self.tree_canvas.queue_draw()
                print("[MainWindow] tree_canvas updated")
            except Exception as e:
                print("[MainWindow] failed to update tree_canvas:", e)

            # Уведомляем контроллер, если у него есть метод загрузки дерева
            try:
                if hasattr(self.controller, "load_game_tree"):
                    self.controller.load_game_tree()
                    print("[MainWindow] controller.load_game_tree called")
                    # после load_game_tree или после tree.load(gt)
                    # print("[DBG controller] controller.tree id:", id(self.tree), "tree.game_tree id:",
                    #       id(self.tree.game_tree) if getattr(self.tree, 'game_tree', None) else None)

            except Exception as e:
                print("[MainWindow] controller.load_game_tree failed:", e)

        # регистрируем callback'и
        self.game_tab.set_rename_tab_callback(rename_tab)
        self.game_tab.set_on_load_callback(on_game_loaded)

    def build_right_panel(self, get_game_tree: Callable[[], GameTree | None]) -> Gtk.Box:
        # right charts + tree
        right_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        right_panel.set_size_request(320, -1)

        # charts placeholders
        right_panel.append(Gtk.Label(label="Winrate chart"))
        right_panel.append(Gtk.Label(label="Score chart"))
        right_panel.append(Gtk.Label(label="Diff chart"))

        # --- Game controls (Open/Save) placed above tree ---
        controls_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        controls_box.set_halign(Gtk.Align.CENTER)
        # создаём GameTab (логика) и кнопки, которые вызывают его методы
        self.game_tab = GameTab(get_game_tree=get_game_tree)

        btn_open = Gtk.Button(label="Open SGF")
        btn_save = Gtk.Button(label="Save SGF")

        # подключаем кнопки Open/Save к game_tab, передаём окно как parent
        btn_open.connect("clicked", lambda w: self.game_tab.open_sgf_dialog(self.main_window))
        btn_save.connect("clicked", lambda w: self.game_tab.save_sgf_dialog(self.main_window))

        controls_box.append(btn_open)
        controls_box.append(btn_save)
        right_panel.append(controls_box)

        # tree under charts: use TreeCanvas inside scrolled window
        tree_scroller = Gtk.ScrolledWindow()
        tree_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.tree_canvas = TreeCanvas(node_radius=3, level_vgap=24, sibling_hgap=12, get_game_tree=get_game_tree)
        tree_scroller.set_size_request(320, -1)
        tree_scroller.set_hexpand(False)
        tree_scroller.set_child(self.tree_canvas)
        right_panel.append(tree_scroller)
        return right_panel

    def build_nav_buttons(self) -> Gtk.Box:
        # nav buttons under board (only for the board)
        nav = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        nav.set_halign(Gtk.Align.CENTER)
        self.btn_first = Gtk.Button(label="<<")
        self.btn_prev = Gtk.Button(label="<")
        self.btn_next = Gtk.Button(label=">")
        self.btn_last = Gtk.Button(label=">>")
        nav.append(self.btn_first)
        nav.append(self.btn_prev)
        nav.append(self.btn_next)
        nav.append(self.btn_last)
        return nav

    def build_top_info_labels(self) -> Gtk.Box:
        # top info: win prob / score lead
        top_info = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        top_info.set_halign(Gtk.Align.CENTER)
        self.lbl_winprob = Gtk.Label(label="Win: —")
        self.lbl_scorelead = Gtk.Label(label="Score lead: —")
        top_info.append(self.lbl_winprob)
        top_info.append(self.lbl_scorelead)
        return top_info

    def build_left_panel(self) -> Gtk.Box:
        left_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        left_panel.set_size_request(260, -1)

        left_panel.append(Gtk.Label(label="KataGo panel"))

        # Start / Stop buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.btn_katago_start = Gtk.Button(label="Start")
        self.btn_katago_stop = Gtk.Button(label="Stop")
        btn_box.append(self.btn_katago_start)
        btn_box.append(self.btn_katago_stop)
        left_panel.append(btn_box)

        # Log area
        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_wrap_mode(Gtk.WrapMode.NONE)
        self.log_buffer = self.log_view.get_buffer()
        log_scroller = Gtk.ScrolledWindow()
        log_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        log_scroller.set_vexpand(True)
        # log_scroller.set_min_content_height(200)
        log_scroller.set_child(self.log_view)
        left_panel.append(log_scroller)

        # Button callbacks
        self.btn_katago_start.connect("clicked", lambda w: self._on_katago_start_clicked())
        self.btn_katago_stop.connect("clicked", lambda w: self._on_katago_stop_clicked())

        return left_panel

    def _append_log_line(self, text: str):
        # always call from main thread; safe wrapper for background threads
        def _do():
            end = self.log_buffer.get_end_iter()
            self.log_buffer.insert(end, text + "\n")
            # auto-scroll to end
            mark = self.log_buffer.create_mark(None, self.log_buffer.get_end_iter(), False)
            self.log_view.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)

        if GLib is not None:
            GLib.idle_add(_do)
        else:
            _do()

    def _on_katago_start_clicked(self):
        try:
            # prepare cfg only on first creation; subsequent calls ignore cfg
            cfg = {
                "binary_path": "/opt/KataGo/cpp/katago",  # замените на реальный путь или настройку UI
                "start_option": "gtp",
                # "model_file": None,
                # "threads": 4,
                # "extra_args": []
                "config_file": "/home/user/katago/gtp_example.cfg",
            }
            kc = KatagoController.get_instance(cfg)
            # subscribe to log callback once
            # ensure we don't reassign multiple times
            if getattr(self, "_katago_log_subscribed", False) is False:
                def _log_cb(line: str):
                    # ensure UI update happens in main thread
                    if GLib is not None:
                        GLib.idle_add(lambda: self._append_log_line(line))
                    else:
                        self._append_log_line(line)

                kc.subscribe_to_log(_log_cb)
                self._katago_log_subscribed = True

            kc.start()
            self._append_log_line("KataGo: start requested")
        except Exception as e:
            self._append_log_line(f"KataGo start error: {e}")

    def _on_katago_stop_clicked(self):
        try:
            # get instance without cfg (must exist)
            try:
                kc = KatagoController.get_instance()
            except Exception:
                # if not created yet, nothing to stop
                self._append_log_line("KataGo: controller not running")
                return
            kc.stop()
            self._append_log_line("KataGo: stop requested")
        except Exception as e:
            self._append_log_line(f"KataGo stop error: {e}")

    def _wire_nav_buttons(self):
        # кнопки уже созданы в get_analysis_box и сохранены в self
        self.btn_first.connect("clicked", lambda w: self.controller.go_first())
        self.btn_prev.connect("clicked", lambda w: self.controller.go_prev())
        self.btn_next.connect("clicked", lambda w: self.controller.go_next())
        self.btn_last.connect("clicked", lambda w: self.controller.go_last())

        # также даём контроллеру ссылки на метки сверху, чтобы он мог обновлять их
        self.controller.set_top_info_widgets(self.lbl_winprob, self.lbl_scorelead)
