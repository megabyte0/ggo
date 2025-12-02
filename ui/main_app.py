# ui/main_app.py
from typing import Any

import gi

from ui.tree_canvas import TreeCanvas

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

from ui.board_view import BoardView
from ui.controller import BoardController

class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="ggo — modular UI")
        self.set_default_size(1200, 800)

        notebook = Gtk.Notebook()

        board_view = BoardView(board_size=19)
        print("main_app board_view id:", id(board_view))
        analysis_box = self.get_analysis_box(board_view)

        notebook.append_page(analysis_box, Gtk.Label(label="Analysis"))

        # Tab 2: IGS list
        igs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        igs_box.append(Gtk.Label(label="IGS games list (stub)"))
        notebook.append_page(igs_box, Gtk.Label(label="IGS"))

        # Собираем финальную вертикальную коробку и один раз устанавливаем её как child окна
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.append(notebook)
        self.set_child(vbox)

        # Создаём контроллер и связываем UI элементы с ним
        self.controller = BoardController(board_view)
        print("[main_app] controller id:", id(self.controller))

        self.controller.attach_tree_canvas(self.tree_canvas)
        # initial populate (controller сделает rebuild_tree_store)

        # подключаем кнопки навигации (они созданы в get_analysis_box и сохранены в self)
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

        # tree under charts: use TreeCanvas inside scrolled window
        tree_scroller = Gtk.ScrolledWindow()
        tree_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.tree_canvas = TreeCanvas(node_radius=3, level_vgap=24, sibling_hgap=12)
        tree_scroller.set_size_request(320, -1)
        tree_scroller.set_hexpand(False)
        tree_scroller.set_child(self.tree_canvas)
        right_panel.append(tree_scroller)
        analysis_box.append(right_panel)

        return analysis_box

    def _wire_nav_buttons(self):
        # кнопки уже созданы в get_analysis_box и сохранены в self
        # подключаем их к методам контроллера
        # контроллер должен реализовать go_first/go_prev/go_next/go_last
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
