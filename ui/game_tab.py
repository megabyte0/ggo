# ui/game_tab.py
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
import os
from datetime import datetime
from typing import Optional, Callable
from ggo.game_tree import GameTree

class GameTab:
    """
    Логика загрузки/сохранения SGF. НЕ является Gtk-виджетом.
    - open_sgf_dialog(parent_window) / save_sgf_dialog(parent_window)
    - set_rename_tab_callback(callback(basename))
    - set_on_load_callback(callback(GameTree))
    Хранит self._gt (GameTree) и self._loaded_filepath.
    """

    def __init__(self):
        # Do not create GameTree here. Controller is authoritative owner.
        self._gt: Optional[GameTree] = None
        self._loaded_filepath: Optional[str] = None
        self._rename_tab_callback: Optional[Callable[[str], None]] = None
        self._on_load_callback: Optional[Callable[[object], None]] = None
        self._controller = None

    def set_controller(self, controller):
        """Attach Controller so GameTab can resolve authoritative GameTree for save."""
        self._controller = controller

    def set_game_tree(self, gt: GameTree):
        """Set GameTree reference (used after load or when controller provides it)."""
        self._gt = gt

    def set_rename_tab_callback(self, callback: Callable[[str], None]):
        self._rename_tab_callback = callback

    def set_on_load_callback(self, callback: Callable[[object], None]):
        self._on_load_callback = callback

    def get_sgf_text(self) -> str:
        if self._gt is not None and hasattr(self._gt, "to_sgf"):
            try:
                return self._gt.to_sgf()
            except Exception:
                return ""
        return ""

    def _extract_pw_pb_from_tree(self) -> (str, str):
        if self._gt is None or getattr(self._gt, "root", None) is None:
            return "White", "Black"
        props = getattr(self._gt.root, "props", {}) or {}
        pw = props.get("PW")
        pb = props.get("PB")
        def norm(v):
            if v is None: return None
            return v[0] if isinstance(v, list) and v else (v if isinstance(v, str) else str(v))
        return norm(pw) or "White", norm(pb) or "Black"

    def _default_filename(self) -> str:
        pw, pb = self._extract_pw_pb_from_tree()
        safe = lambda s: "".join(c if c.isalnum() or c in "-_." else "_" for c in s).strip("_")
        date_s = datetime.now().strftime("%Y-%m-%d")
        return f"{safe(pw)}-{safe(pb)}-{date_s}.sgf"

    # ---------------------------
    # File dialogs using Gtk.FileChooserDialog (async)
    # ---------------------------
    def open_sgf_dialog(self, parent_window: Optional[Gtk.Window] = None):
        parent = parent_window if parent_window is not None else None
        dialog = Gtk.FileChooserDialog(title="Open SGF", transient_for=parent, action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.ACCEPT)
        filt = Gtk.FileFilter()
        filt.set_name("SGF files")
        filt.add_pattern("*.sgf")
        dialog.add_filter(filt)
        dialog.set_modal(True)

        def on_response(dialog_obj, response):
            try:
                if response == Gtk.ResponseType.ACCEPT:
                    file = dialog_obj.get_file()
                    if file is None:
                        return
                    filename = file.get_path()
                    try:
                        with open(filename, "r", encoding="utf-8") as f:
                            text = f.read()
                    except Exception as e:
                        self._show_message(parent, "Error", f"Cannot open file:\n{e}")
                        return

                    # load into a new GameTree and set it (controller will be notified via callback)
                    if GameTree is not None:
                        try:
                            gt = GameTree()
                            if hasattr(gt, "load_sgf_simple"):
                                gt.load_sgf_simple(text)
                            elif hasattr(gt, "load_sgf"):
                                gt.load_sgf(text)
                            self.set_game_tree(gt)
                        except Exception as e:
                            print("[WARN] GameTab.open_sgf_dialog: failed to parse SGF:", e)
                            self._gt = None

                    # if parser provides normalized text, use it
                    if self._gt is not None and hasattr(self._gt, "to_sgf"):
                        try:
                            sgf_out = self._gt.to_sgf()
                        except Exception:
                            sgf_out = text
                    else:
                        sgf_out = text

                    self._loaded_filepath = filename

                    # notify parent (MainWindow) to rename tab
                    basename = os.path.basename(filename)
                    if self._rename_tab_callback:
                        try:
                            self._rename_tab_callback(basename)
                        except Exception as e:
                            print("[WARN] GameTab: rename_tab_callback raised:", e)

                    # notify on_load callback with GameTree (if available)
                    if self._on_load_callback:
                        try:
                            self._on_load_callback(self._gt)
                        except Exception as e:
                            print("[WARN] GameTab: on_load_callback raised:", e)
            finally:
                try:
                    dialog_obj.disconnect(handler_id)
                except Exception:
                    pass
                dialog_obj.destroy()

        handler_id = dialog.connect("response", on_response)
        dialog.show()

    def save_sgf_dialog(self, parent_window: Optional[Gtk.Window] = None):
        parent = parent_window if parent_window is not None else None
        dialog = Gtk.FileChooserDialog(title="Save SGF", transient_for=parent, action=Gtk.FileChooserAction.SAVE)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.ACCEPT)
        filt = Gtk.FileFilter()
        filt.set_name("SGF files")
        filt.add_pattern("*.sgf")
        dialog.add_filter(filt)
        dialog.set_modal(True)

        if self._loaded_filepath:
            dialog.set_current_name(self._loaded_filepath)
        else:
            dialog.set_current_name(self._default_filename())

        def on_response(dialog_obj, response):
            try:
                if response == Gtk.ResponseType.ACCEPT:
                    file = dialog_obj.get_file()
                    if file is None:
                        return
                    filename = file.get_path()
                    if not filename.lower().endswith(".sgf"):
                        filename = filename + ".sgf"
                    try:
                        # Resolve authoritative GameTree: prefer local, else controller
                        gt = self._gt
                        if gt is None and getattr(self, "_controller", None):
                            try:
                                ta = getattr(self._controller, "tree", None)
                                if ta:
                                    gt = getattr(ta, "game_tree", None)
                            except Exception:
                                gt = None

                        print("[DBG save] resolved gt id:", id(gt) if gt else None)
                        if gt is None:
                            self._show_message(parent, "Error", "No game loaded to save.")
                            return

                        root = getattr(gt, "root", None)
                        print("[DBG save] gt.root id:", id(root) if root else None,
                              "children:", len(getattr(root, "children", [])) if root else None)
                        try:
                            sgf_out = gt.to_sgf() or ""
                        except Exception as e:
                            print("[DBG save] to_sgf error:", e)
                            sgf_out = ""
                        print("[DBG save] to_sgf length:", len(sgf_out))
                        print("[DBG save] to_sgf head:", repr(sgf_out[:400]))

                        # atomic write
                        tmp = filename + ".tmp"
                        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                            f.write(sgf_out)
                        os.replace(tmp, filename)
                        print(f"[save] wrote {len(sgf_out)} bytes to {filename}")
                        self._loaded_filepath = filename
                        basename = os.path.basename(filename)
                        if self._rename_tab_callback:
                            try:
                                self._rename_tab_callback(basename)
                            except Exception:
                                pass
                        return
                    except Exception as e:
                        self._show_message(parent, "Error", f"Cannot save file:\n{e}")
                        return
                    except Exception as e:
                        self._show_message(parent, "Error", f"Cannot save file:\n{e}")
                        return
                    self._loaded_filepath = filename
                    basename = os.path.basename(filename)
                    if self._rename_tab_callback:
                        try:
                            self._rename_tab_callback(basename)
                        except Exception:
                            pass
            finally:
                try:
                    dialog_obj.disconnect(handler_id)
                except Exception:
                    pass
                dialog_obj.destroy()

        handler_id = dialog.connect("response", on_response)
        dialog.show()

    def _show_message(self, parent, title: str, message: str):
        md = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.INFO,
                               buttons=Gtk.ButtonsType.OK, text=title)
        md.format_secondary_text(message)
        md.run()
        md.destroy()

    def get_game_tree(self) -> GameTree:
        return self._gt
