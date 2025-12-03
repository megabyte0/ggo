# ui/main_app.py
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

from ui.tree_canvas import TreeCanvas
from ui.game_tab import GameTab

from ui.board_view import BoardView
from ui.controller import Controller

class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="ggo — modular UI")
        self.set_default_size(1200, 800)

        # Notebook
        self.notebook = Gtk.Notebook()

        # Создаём board_view и контроллер раньше, чтобы callback'и могли к ним обращаться
        board_view = BoardView(board_size=19)
        print("main_app board_view id:", id(board_view))

        # Создаём контроллер сразу — он может понадобиться в callback'ах загрузки
        self.controller = Controller(board_view)
        print("[main_app] controller id:", id(self.controller))
        # propagate controller reference to game_tab so save can resolve authoritative GameTree
        try:
            if hasattr(self, "game_tab") and self.game_tab is not None:
                try:
                    self.game_tab.set_controller(self.controller)
                except Exception as e:
                    print("[WARN] main_app: game_tab.set_controller raised:", e)
                # if controller already has a game_tree, propagate it
                try:
                    if getattr(self.controller, "tree", None) and getattr(self.controller.tree, "game_tree", None):
                        self.game_tab.set_game_tree(self.controller.tree.game_tree)
                        print("[main_app] propagated game_tree to game_tab id:", id(self.controller.tree.game_tree))
                except Exception as e:
                    print("[WARN] main_app: propagating game_tree to game_tab raised:", e)
        except Exception as e:
            print("[WARN] main_app: error while wiring game_tab/controller:", e)

        # Теперь строим analysis_box (внутри него создаётся TreeCanvas и кнопки)
        analysis_box = self.get_analysis_box(board_view)

        # Добавляем вкладки
        self.notebook.append_page(analysis_box, Gtk.Label(label="Analysis"))

        igs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        igs_box.append(Gtk.Label(label="IGS games list (stub)"))
        self.notebook.append_page(igs_box, Gtk.Label(label="IGS"))

        # Собираем финальную вертикальную коробку и один раз устанавливаем её как child окна
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.append(self.notebook)
        self.set_child(vbox)

        # attach tree canvas to controller (контроллер будет обновлять дерево при необходимости)
        self.controller.attach_tree_canvas(self.tree_canvas)
        # If GameTab already has a GameTree, load it into the controller safely.
        try:
            gt = None
            try:
                gt = self.game_tab.get_game_tree()
            except Exception as e:
                gt = None
            if gt is not None:
                try:
                    # prefer controller.load_game_tree if implemented
                    if hasattr(self.controller, "load_game_tree"):
                        self.controller.load_game_tree(gt)
                    # fallback to older tree.load API if present
                    elif getattr(self.controller, "tree", None) and hasattr(self.controller.tree, "load"):
                        self.controller.tree.load(gt)
                except Exception as e:
                    print("[WARN] main_app: failed to load GameTree into controller:", e)
        except Exception as e:
            print("[WARN] main_app: unexpected error while wiring controller tree:", e)

        # подключаем кнопки навигации
        self._wire_nav_buttons()

    def get_analysis_box(self, board_view) -> Any:
        # основной горизонтальный анализ-бокс: слева katago, центр доска, справа графики/дерево
        analysis_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        # left katago panel
        left_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        left_panel.set_size_request(260, -1)
        left_panel.append(Gtk.Label(label="KataGo panel"))
        self.var_scroller = Gtk.ScrolledWindow()
        self.var_list = Gtk.ListBox()
        self.var_scroller.set_child(self.var_list)
        left_panel.append(self.var_scroller)
        analysis_box.append(left_panel)

        # center board + top info + nav (nav только под гобаном)
        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        # top info: win prob / score lead
        top_info = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        top_info.set_halign(Gtk.Align.CENTER)
        self.lbl_winprob = Gtk.Label(label="Win: —")
        self.lbl_scorelead = Gtk.Label(label="Score lead: —")
        top_info.append(self.lbl_winprob)
        top_info.append(self.lbl_scorelead)
        center.append(top_info)

        # board itself
        center.append(board_view)

        # nav buttons under board (only for the board)
        nav = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        nav.set_halign(Gtk.Align.CENTER)
        self.btn_first = Gtk.Button(label="<<")
        self.btn_prev = Gtk.Button(label="<")
        self.btn_next = Gtk.Button(label=">")
        self.btn_last = Gtk.Button(label=">>")
        nav.append(self.btn_first); nav.append(self.btn_prev); nav.append(self.btn_next); nav.append(self.btn_last)
        center.append(nav)

        analysis_box.append(center)

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
        self.game_tab = GameTab()
        # сразу привязываем контроллер к game_tab, чтобы GameTab мог резолвить authoritative GameTree
        try:
            try:
                self.game_tab.set_controller(self.controller)
            except Exception as e:
                print("[WARN] main_app: game_tab.set_controller raised:", e)
            # если контроллер уже содержит дерево — передаём его в game_tab
            try:
                if getattr(self.controller, "tree", None) and getattr(self.controller.tree, "game_tree", None):
                    self.game_tab.set_game_tree(self.controller.tree.game_tree)
                    print("[main_app] propagated game_tree to game_tab id:", id(self.controller.tree.game_tree))
            except Exception as e:
                print("[WARN] main_app: propagating game_tree to game_tab raised:", e)
        except Exception as e:
            print("[WARN] main_app: error while wiring game_tab/controller:", e)

        btn_open = Gtk.Button(label="Open SGF")
        btn_save = Gtk.Button(label="Save SGF")
        controls_box.append(btn_open)
        controls_box.append(btn_save)
        right_panel.append(controls_box)

        # tree under charts: use TreeCanvas inside scrolled window
        tree_scroller = Gtk.ScrolledWindow()
        tree_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.tree_canvas = TreeCanvas(node_radius=3, level_vgap=24, sibling_hgap=12)
        # безопасно привязываем root: game_tab может ещё не иметь game_tree
        try:
            gt = None
            try:
                gt = self.game_tab.get_game_tree()
            except Exception as e:
                print("[WARN] MainWindow: game_tab.get_game_tree() raised:", e)
                gt = None

            if gt is None:
                print("[MainWindow] game_tab has no GameTree yet; skipping tree root wiring")
            else:
                print("[MainWindow] init setting tree root", id(self.tree_canvas.root), "to", id(gt.root))
                self.tree_canvas.set_tree_root(gt.root)
        except Exception as e:
            print("[WARN] MainWindow: failed to set tree root:", e)
        tree_scroller.set_size_request(320, -1)
        tree_scroller.set_hexpand(False)
        tree_scroller.set_child(self.tree_canvas)
        right_panel.append(tree_scroller)
        analysis_box.append(right_panel)

        # подключаем кнопки Open/Save к game_tab, передаём окно как parent
        btn_open.connect("clicked", lambda w: self.game_tab.open_sgf_dialog(self))
        btn_save.connect("clicked", lambda w: self.game_tab.save_sgf_dialog(self))

        # callback: переименовать вкладку
        def rename_tab(basename: str):
            try:
                self.notebook.set_tab_label_text(analysis_box, basename)
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
                print("[MainWindow] setting tree root", id(self.tree_canvas.root), "to", id(root))
                self.tree_canvas.set_tree_root(root)
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
                    self.controller.load_game_tree(gt)
                    print("[MainWindow] controller.load_game_tree called")
                    # после load_game_tree или после tree.load(gt)
                    # print("[DBG controller] controller.tree id:", id(self.tree), "tree.game_tree id:",
                    #       id(self.tree.game_tree) if getattr(self.tree, 'game_tree', None) else None)
                    
            except Exception as e:
                print("[MainWindow] controller.load_game_tree failed:", e)

        # регистрируем callback'и
        self.game_tab.set_rename_tab_callback(rename_tab)
        self.game_tab.set_on_load_callback(on_game_loaded)

        return analysis_box

    def _wire_nav_buttons(self):
        # кнопки уже созданы в get_analysis_box и сохранены в self
        self.btn_first.connect("clicked", lambda w: self.controller.go_first())
        self.btn_prev.connect("clicked", lambda w: self.controller.go_prev())
        self.btn_next.connect("clicked", lambda w: self.controller.go_next())
        self.btn_last.connect("clicked", lambda w: self.controller.go_last())

        # также даём контроллеру ссылки на метки сверху, чтобы он мог обновлять их
        self.controller.set_top_info_widgets(self.lbl_winprob, self.lbl_scorelead)


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.ggo.app")

    def do_activate(self):
        win = MainWindow(self)
        win.present()

def main():
    app = App()
    app.run(None)

if __name__ == "__main__":
    main()
