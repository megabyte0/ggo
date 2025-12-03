# ui/controller.py
from typing import Any, List, Tuple, Optional
from gi.repository import GLib

from ui.controller_board import BoardAdapter, DEBUG as BOARD_DEBUG
from ui.controller_tree import TreeAdapter, DEBUG as TREE_DEBUG

# enable debug here
DEBUG = True
BOARD_DEBUG = DEBUG
TREE_DEBUG = DEBUG

class Controller:
    """
    Facade controller that связывает BoardAdapter и TreeAdapter,
    а также TreeCanvas/TreeStore/BoardView.
    """
    def __init__(self, board_view, board_size=19):
        self.board = BoardAdapter(board_view, board_size=board_size)
        self.tree = TreeAdapter()
        self.tree_canvas = None
        self.tree_store = None
        self.tree_view = None
        self.current_node = None
        # wire board view callbacks if available
        try:
            board_view.on_click(self._on_click)
            board_view.on_hover(self._on_hover)
            board_view.on_leave(self._on_leave)
        except Exception:
            pass

    # --- integration points ---
    def attach_tree_canvas(self, tree_canvas):
        self.tree_canvas = tree_canvas
        try:
            self.tree_canvas.set_on_node_selected(self._on_tree_node_selected)
        except Exception:
            setattr(self.tree_canvas, "_on_node_selected_cb", self._on_tree_node_selected)
        # push current root if any
        if DEBUG:
            print("[Controller] attach_tree_canvas setting root from", id(self.tree_canvas.root), "to", id(self.tree.get_root()))
        self._refresh_tree_canvas()

    def attach_tree_widgets(self, tree_store, tree_view):
        self.tree_store = tree_store
        self.tree_view = tree_view
        sel = self.tree_view.get_selection()
        sel.connect("changed", self._on_tree_selection_changed)
        self._rebuild_tree_store()

    # --- loading SGF ---
    def load_game_tree(self, gt):
        """Called by MainWindow when SGF parsed. Keep reference and apply AB/AW and mainline."""
        self.tree.load(gt)
        root = self.tree.get_root()
        self.current_node = root
        if DEBUG:
            print("[Controller] load_game_tree root children:", len(root.children) if root else None)
        # update canvas
        if DEBUG:
            print("[Controller] load_game_tree setting root from", id(self.tree_canvas.root), "to", id(self.tree.get_root()))
        self._refresh_tree_canvas()
        # apply AB/AW to board
        stones = self.tree.collect_ab_aw()
        if stones:
            # convert SGF coords to numeric and apply
            numeric = []
            for color, sgf in stones:
                rc = self._sgf_to_rc(sgf, size=self.board.size)
                if rc[0] is not None:
                    numeric.append((color, rc))
            if numeric:
                if DEBUG:
                    print("[Controller] applying AB/AW stones:", numeric)
                self.board.set_stones(numeric)
        # apply mainline to model (reset + replay)
        main_nodes = self.tree.collect_mainline_nodes()
        moves = []
        for nd in main_nodes:
            # convert node -> "B pd" etc.
            mv = None
            if hasattr(nd, "get_prop"):
                b = nd.get_prop("B")
                w = nd.get_prop("W")
                if b and len(b) > 0:
                    mv = f"B {b[0]}"
                elif w and len(w) > 0:
                    mv = f"W {w[0]}"
            else:
                for k, vals in getattr(nd, "props", []):
                    if k == "B" and vals:
                        mv = f"B {vals[0]}"
                        break
                    if k == "W" and vals:
                        mv = f"W {vals[0]}"
                        break
            if mv:
                moves.append(mv)
        if DEBUG:
            print("[Controller] mainline moves to apply:", moves)
        self._apply_move_sequence_to_board(moves)

    # --- TreeStore building (Gtk) ---
    def _rebuild_tree_store(self):
        if self.tree_store is None:
            return
        self.tree_store.clear()
        def add_node_recursive(parent_iter, node):
            mv = None
            if hasattr(node, "get_prop"):
                b = node.get_prop("B"); w = node.get_prop("W")
                if b and len(b)>0:
                    mv = f"B {b[0]}"
                elif w and len(w)>0:
                    mv = f"W {w[0]}"
            if not mv:
                mv = "(root)"
            iter_ = self.tree_store.append(parent_iter, [mv, node])
            for ch in node.children:
                add_node_recursive(iter_, ch)
        root = self.tree.get_root()
        if root:
            for ch in root.children:
                add_node_recursive(None, ch)

    def _on_tree_selection_changed(self, selection):
        model, treeiter = selection.get_selected()
        if treeiter is None:
            return
        node = model[treeiter][1]
        if node:
            self.current_node = node
            moves = self.tree.get_node_path(node)
            self._apply_move_sequence_to_board(moves)
            GLib.idle_add(self._refresh_view)

    # --- TreeCanvas callback ---
    def _on_tree_node_selected(self, node):
        if node is None:
            return
        self.current_node = node
        moves = self.tree.get_node_path(node)
        self._apply_move_sequence_to_board(moves)
        GLib.idle_add(self._refresh_view)
        # select in canvas
        try:
            if self.tree_canvas:
                self.tree_canvas.select_node(node)
        except Exception:
            pass

    # --- Board callbacks ---
    def _on_click(self, r:int, c:int, n_press:int):
        color = self.board.current_player()
        sgf_coord = chr(ord('a') + c) + chr(ord('a') + r)
        if DEBUG:
            print("[Controller] board click at", (r,c), "sgf:", sgf_coord, "color:", color)
        parent = self.current_node if self.current_node is not None else self.tree.find_last_mainline_node()
        # check existing child
        found = None
        for ch in getattr(parent, "children", []):
            # compare by first B/W prop
            mv = None
            if hasattr(ch, "get_prop"):
                b = ch.get_prop("B"); w = ch.get_prop("W")
                if b and len(b)>0:
                    mv = f"B {b[0]}"
                elif w and len(w)>0:
                    mv = f"W {w[0]}"
            else:
                for k, vals in getattr(ch, "props", []):
                    if k in ("B","W") and vals:
                        mv = f"{k} {vals[0]}"
                        break
            if mv and mv.endswith(sgf_coord):
                found = ch
                break

        if found is None:
            # add move in-place
            if DEBUG:
                print("[Controller] adding move under parent:", parent)
            new_node = self.tree.add_move(parent, color, sgf_coord, props=None)
            if DEBUG:
                # сразу после создания/получения node
                print("[DBG add_move] Controller id: ", id(self), "TreeAdapter id:", id(self.tree), "game_tree id:",
                      id(self.tree.game_tree), "root id:", id(self.tree.game_tree.root))
                print("[DBG add_move] parent:", parent, "new_node:", new_node)

            # try to apply to board model
            rc = (r,c)
            ok = self.board.play_move(color, rc)
            if not ok:
                # rollback
                try:
                    parent.children.remove(new_node)
                except Exception:
                    pass
                if DEBUG:
                    print("[Controller] illegal move, rolled back")
                return
            # advance current node
            self.current_node = new_node
            # update tree canvas and store
            if DEBUG:
                print("[Controller] _on_click setting root from", id(self.tree_canvas.root), "to", id(self.tree.get_root()))
            self._refresh_tree_canvas()
            self._rebuild_tree_store()
            if self.tree_canvas:
                self.tree_canvas.select_node(new_node)
            GLib.idle_add(self._refresh_view)
        else:
            # navigate into existing child
            self.current_node = found
            moves = self.tree.get_node_path(found)
            self._apply_move_sequence_to_board(moves)
            if DEBUG:
                print("[Controller] _on_click setting root from", id(self.tree_canvas.root), "to", id(self.tree.get_root()))
            self._refresh_tree_canvas()
            if self.tree_canvas:
                self.tree_canvas.select_node(found)
            GLib.idle_add(self._refresh_view)

    def _on_hover(self, r:int, c:int):
        # show ghost if legal
        from ggo.goban_model import Move, IllegalMove
        color = self.board.current_player()
        mv = Move(color=color, point=(r,c), is_pass=False, is_resign=False, move_number=self.board.model.move_number+1)
        try:
            self.board.model.legal(mv)
            legal = True
        except IllegalMove:
            legal = False
        if legal:
            try:
                self.board.view.show_ghost((r,c), color)
            except Exception:
                pass
        else:
            try:
                self.board.view.clear_ghost()
            except Exception:
                pass

    def _on_leave(self):
        try:
            self.board.view.clear_ghost()
        except Exception:
            pass

    # --- apply sequence to board (reset + replay) ---
    def _apply_move_sequence_to_board(self, moves: List[Any]):
        """
        moves: list of Node or list of strings "B pd"
        Reset board and replay moves.
        """
        # normalize to strings
        normalized = []
        for mv in moves:
            if mv is None:
                continue
            if isinstance(mv, str):
                normalized.append(mv)
            else:
                # Node -> string
                s = None
                if hasattr(mv, "get_prop"):
                    b = mv.get_prop("B"); w = mv.get_prop("W")
                    if b and len(b)>0:
                        s = f"B {b[0]}"
                    elif w and len(w)>0:
                        s = f"W {w[0]}"
                else:
                    for k, vals in getattr(mv, "props", []):
                        if k in ("B","W") and vals:
                            s = f"{k} {vals[0]}"
                            break
                if s:
                    normalized.append(s)
        if DEBUG:
            print("[Controller] applying move sequence:", normalized)
        # reset board
        self.board.reset()
        # apply moves
        for mv in normalized:
            if ' ' in mv:
                color, coord = mv.split(' ',1)
                coord = coord.strip()
                if coord == "" or coord.lower() == "pass":
                    # ignore pass for now
                    continue
                r,c = self._sgf_to_rc(coord, size=self.board.size)
                if r is None:
                    continue
                ok = self.board.play_move(color, (r,c))
                if not ok:
                    if DEBUG:
                        print("[Controller] failed to apply move", mv)
            else:
                # treat as coord only
                r,c = self._sgf_to_rc(mv, size=self.board.size)
                if r is None:
                    continue
                self.board.play_move('B', (r,c))
        # refresh view
        self._refresh_view()

    # --- helpers ---
    def _refresh_tree_canvas(self):
        if self.tree_canvas and self.tree.get_root():
            try:
                self.tree_canvas.set_tree_root(self.tree.get_root())  # !
                if self.current_node:
                    self.tree_canvas.select_node(self.current_node)
            except Exception:
                pass

    def _refresh_view(self):
        try:
            if hasattr(self.board.view, "set_board"):
                self.board.view.set_board(self.board.get_board())
            elif hasattr(self.board.view, "queue_draw"):
                self.board.view.queue_draw()
        except Exception:
            pass

    def _sgf_to_rc(self, s: str, size: int = 19):
        if not s or len(s) < 2:
            return (None, None)
        try:
            col = ord(s[0]) - ord('a')
            row = ord(s[1]) - ord('a')
            if 0 <= row < size and 0 <= col < size:
                return (row, col)
        except Exception:
            pass
        return (None, None)

    def set_top_info_widgets(self, lbl_winprob_widget, lbl_scorelead_widget):
        """
        Совместимость с MainWindow: пробрасываем виджеты в контроллер,
        чтобы MainWindow мог передавать метки для обновления.
        """
        # Сохраним локально (на всякий случай) и пробросим в BoardAdapter, если нужно
        self._lbl_winprob = lbl_winprob_widget
        self._lbl_scorelead = lbl_scorelead_widget

        # Если BoardAdapter/BoardView ожидают обновление — можно обновить сразу
        try:
            # если у BoardAdapter есть метод для установки виджетов — вызвать его
            if hasattr(self.board, "set_top_info_widgets"):
                self.board.set_top_info_widgets(lbl_winprob_widget, lbl_scorelead_widget)
        except Exception:
            pass

