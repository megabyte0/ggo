# ui/main_app.py
from typing import Optional

import gi

from ggo.game_tree import get_name_and_version_from_toml_path
from ui.analysys_box import AnalysisBox

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        name, version = get_name_and_version_from_toml_path()
        super().__init__(application=app, title=f"{name or 'ggo'} {version or ''}")
        self.init_css()
        self.plus_page: Optional[Gtk.Box] = None
        self.set_default_size(1200, 800)

        # Notebook
        self.notebook = Gtk.Notebook()
        self._creating_tab = False

        igs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        igs_box.append(Gtk.Label(label="IGS games list (stub)"))
        self.notebook.append_page(igs_box, Gtk.Label(label="IGS"))

        self.add_plus_page()

        self.add_analysis_tab()

        # подключаем обработчик переключения
        self.notebook.connect("switch-page", self.on_switch_page)

        # Собираем финальную вертикальную коробку и один раз устанавливаем её как child окна
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.append(self.notebook)
        self.set_child(vbox)

    def init_css(self):
        # в __init__ окна — подключаем CSS один раз
        css = b"""
        .tab-close {
          padding: 0px 0px;
          border: 0;
          background-color: transparent;
          min-width: 18px;
          min-height: 18px;
          border-radius: 9px;
        }
        .tab-close:hover {
          background-color: rgba(0,0,0,0.06);
        }
        .tab-header {
          padding: 0px 0px;
          margin: 0 0;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    # метод добавления вкладки
    def add_analysis_tab(self):
        if self._creating_tab:
            return
        self._creating_tab = True
        # ... создание analysis_box ...
        analysis_box = AnalysisBox(self)

        insert_index = self.notebook.get_n_pages() - 1  # вставляем перед plus_page
        self.notebook.insert_page(analysis_box, None, insert_index)

        # заголовок: метка + кнопка
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        header.add_css_class("tab-header")

        label = Gtk.Label(label="Analysis")
        analysis_box.set_tab_label_setter(lambda s: label.set_text(s))
        label.set_hexpand(False)
        label.set_halign(Gtk.Align.START)
        label.set_margin_start(6)
        label.set_margin_end(6)
        label.set_margin_top(2)
        label.set_margin_bottom(2)

        close_btn = Gtk.Button(label="✕")
        close_btn.set_can_focus(False)
        close_btn.set_focusable(False)
        close_btn.add_css_class("tab-close")
        # выравнивание в правый верхний угол заголовка
        close_btn.set_halign(Gtk.Align.END)
        close_btn.set_valign(Gtk.Align.BASELINE_CENTER)
        close_btn.set_margin_end(2)
        close_btn.set_margin_top(2)

        # обработчик закрытия по виджету
        close_btn.connect("clicked", lambda btn, w=analysis_box: self.close_tab(w))

        header.append(label)
        header.append(close_btn)

        self.notebook.set_tab_label(analysis_box, header)
        self.notebook.set_current_page(insert_index)

        self._creating_tab = False

    def add_plus_page(self):
        # создаём plus_page и сохраняем ссылку
        self.plus_page = Gtk.Box()
        self.notebook.append_page(self.plus_page, Gtk.Label(label=""))  # пустая страница
        plus_button = Gtk.Button(label="+")
        plus_button.set_can_focus(False)
        plus_button.connect("clicked", lambda btn: self.add_analysis_tab())
        self.notebook.set_tab_label(self.plus_page, plus_button)

    def on_switch_page(self, notebook, page, page_num):
        # если переключились на plus_page — создаём новый analysis
        if page is self.plus_page and not self._creating_tab:
            # помечаем, чтобы избежать re-entrant вызовов
            self._creating_tab = True
            try:
                self.add_analysis_tab()
            finally:
                self._creating_tab = False

    def close_tab(self, page_widget):
        # безопасно удаляем страницу по виджету; не удаляем igs_page если нужно
        page_num = self.notebook.page_num(page_widget)
        if page_num != -1:
            self.notebook.remove_page(page_num)


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
