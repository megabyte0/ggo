# ui/main_app.py
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

from ui.board_view import BoardView
from ui.controller import Controller

class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="ggo — modular UI")
        self.set_default_size(1200, 800)

        notebook = Gtk.Notebook()

        # Tab 1: Analysis
        analysis_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        left_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left_panel.set_size_request(240, -1)
        left_panel.append(Gtk.Label(label="Katago panel (stub)"))
        analysis_box.append(left_panel)

        board_view = BoardView(board_size=19)
        print("main_app board_view id:", id(board_view))
        analysis_box.append(board_view)

        right_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right_panel.set_size_request(300, -1)
        right_panel.append(Gtk.Label(label="Charts (winrate/score/diff)"))
        analysis_box.append(right_panel)

        notebook.append_page(analysis_box, Gtk.Label(label="Analysis"))

        # Tab 2: IGS list
        igs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        igs_box.append(Gtk.Label(label="IGS games list (stub)"))
        notebook.append_page(igs_box, Gtk.Label(label="IGS"))

        # bottom controls under board (navigation)
        nav = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_first = Gtk.Button(label="<<")
        btn_prev = Gtk.Button(label="<")
        btn_next = Gtk.Button(label=">")
        btn_last = Gtk.Button(label=">>")
        nav.append(btn_first); nav.append(btn_prev); nav.append(btn_next); nav.append(btn_last)

        btn_test = Gtk.Button(label="Place test stone")
        nav.append(btn_test)
        btn_test.connect("clicked", lambda w: (board_view.set_board(
            [['B' if (r == 3 and c == 3) else board_view.board_state[r][c] for c in range(board_view.board_size)] for r
             in range(board_view.board_size)])))

        # Собираем финальную вертикальную коробку и один раз устанавливаем её как child окна
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.append(notebook)
        vbox.append(nav)
        self.set_child(vbox)
        self.controller = Controller(board_view)
        print("[main_app] controller id:", id(self.controller))

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
