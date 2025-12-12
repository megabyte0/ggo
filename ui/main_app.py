# ui/main_app.py
from typing import Any, Optional, Callable

import gi
from gi.repository.Gtk import Box

from ggo.game_tree import GameTree, Node
from ui.analysys_box import AnalysisBox

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

        analysis_box = AnalysisBox(self)

        # Добавляем вкладки
        self.notebook.append_page(analysis_box, Gtk.Label(label="Analysis"))

        igs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        igs_box.append(Gtk.Label(label="IGS games list (stub)"))
        self.notebook.append_page(igs_box, Gtk.Label(label="IGS"))

        # Собираем финальную вертикальную коробку и один раз устанавливаем её как child окна
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.append(self.notebook)
        self.set_child(vbox)


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
