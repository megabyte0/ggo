# ui/controller.py
from typing import Any, List, Tuple, Optional, Callable
from gi.repository import GLib

from ggo.game_tree import GameTree, Node
from ui.board_view import BoardView
from ui.controller_board import BoardAdapter, DEBUG as BOARD_DEBUG
from ui.controller_katago import KatagoController
from ui.controller_tree import TreeAdapter, DEBUG as TREE_DEBUG
from ui.tree_canvas import TreeCanvas

# enable debug here
DEBUG = True
BOARD_DEBUG = DEBUG
TREE_DEBUG = DEBUG


class Controller:
    """
    Facade controller that связывает BoardAdapter и TreeAdapter,
    а также TreeCanvas/TreeStore/BoardView.
    """

    def __init__(self, board_view: BoardView, board_size=19):
        self.game_tree = GameTree()
        self.get_game_tree = lambda: self.game_tree
        self.board: BoardAdapter = BoardAdapter(board_view, board_size=board_size)
        self.tree: TreeAdapter = TreeAdapter(get_game_tree=self.get_game_tree)
        self.tree_canvas: Optional[TreeCanvas] = None
        self.tree_store = None
        self.tree_view = None
        self._board_view_node_cached: Optional[Node] = None
        # self.current_node: Optional[Node] = None
        # wire board view callbacks if available
        try:
            board_view.on_click(self._on_click)
            board_view.on_hover(self._on_hover)
            board_view.on_leave(self._on_leave)
            board_view.on_ctrl_click(self._on_ctrl_click)
        except Exception as e:
            print("[Controller] failed to wire board view callbacks", e)
        self.game_tree.subscribe(self._on_game_tree_event)

    @property
    def current_node(self):
        return self.game_tree.current
    @current_node.setter
    def current_node(self, node):
        self.game_tree.current = node

    # --- integration points ---
    def attach_tree_canvas(self, tree_canvas: TreeCanvas):
        self.tree_canvas = tree_canvas
        try:
            self.tree_canvas.set_on_node_selected(self._on_tree_node_selected)
        except Exception:
            setattr(self.tree_canvas, "_on_node_selected_cb", self._on_tree_node_selected)

    def attach_tree_widgets(self, tree_store, tree_view):
        self.tree_store = tree_store
        self.tree_view = tree_view
        sel = self.tree_view.get_selection()
        sel.connect("changed", self._on_tree_selection_changed)
        self._rebuild_tree_store()

    # --- loading SGF ---
    def load_game_tree(self):
        """Called by MainWindow when SGF parsed. Keep reference and apply AB/AW and mainline."""
        self.tree.load()
        root = self.tree.get_root()
        self.current_node = root
        if DEBUG:
            print("[Controller] load_game_tree root children:", len(root.children) if root else None)
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
        if main_nodes:
            self.current_node = main_nodes[-1]

    # --- TreeStore building (Gtk) ---
    def _rebuild_tree_store(self):
        if self.tree_store is None:
            return
        self.tree_store.clear()

        def add_node_recursive(parent_iter, node):
            mv = None
            if hasattr(node, "get_prop"):
                b = node.get_prop("B")
                w = node.get_prop("W")
                if b and len(b) > 0:
                    mv = f"B {b[0]}"
                elif w and len(w) > 0:
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
        if not node:
            return
        if DEBUG:
            print("[Controller] _on_tree_selection_changed: node id", id(node))
        self.game_tree.current = node

    # --- TreeCanvas callback ---
    def _on_tree_node_selected(self, node):
        if DEBUG:
            print("[Controller] _on_tree_node_selected: node id", id(node))
        if node is None:
            return
        self.game_tree.current = node

    # --- Board callbacks ---
    def _on_click(self, r: int, c: int, n_press: int):
        color = self.board.current_player()
        sgf_coord = chr(ord('a') + c) + chr(ord('a') + r)
        if DEBUG:
            print("[Controller] board click at", (r, c), "sgf:", sgf_coord, "color:", color)
        parent = self.current_node if self.current_node is not None else self.tree.find_last_mainline_node()
        # check existing child
        found = None
        for ch in getattr(parent, "children", []):
            # compare by first B/W prop
            mv = self._node_to_string(ch)
            if mv and mv.endswith(sgf_coord):
                found = ch
                break

        if found is None:
            # try to apply to board model
            ok = self.board.play_move(color, (r, c))
            if ok:
                # add move in-place
                new_node = self.tree.add_move(parent, color, sgf_coord, props=None)
                self._board_view_node_cached = new_node
                self._on_board_changed(new_node)
            else:
                if DEBUG:
                    print("[Controller] illegal move, not added")
                return
            # advance current node
            self.current_node = new_node
            self._rebuild_tree_store()
            # GLib.idle_add(self._refresh_view)
        else:
            # navigate into existing child
            self.current_node = found
            # moves = self.tree.get_node_path(found)
            # self._apply_move_sequence_to_board(moves)
            # GLib.idle_add(self._refresh_view)

    def _on_hover(self, r: int, c: int):
        # show ghost if legal
        from ggo.goban_model import Move, IllegalMove
        color = self.board.current_player()
        mv = Move(color=color, point=(r, c), is_pass=False, is_resign=False,
                  move_number=self.board.model.move_number + 1)
        try:
            self.board.model.legal(mv)
            legal = True
        except IllegalMove:
            legal = False
        if legal:
            try:
                self.board.view.show_ghost((r, c), color)
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
                s = self._node_to_string(mv)
                if s:
                    normalized.append(s)
        if DEBUG:
            print("[Controller] applying move sequence:", normalized)
        # reset board
        self.board.reset()
        # apply moves
        for mv in normalized:
            if ' ' in mv:
                color, coord = mv.split(' ', 1)
                coord = coord.strip()
                if coord == "" or coord.lower() == "pass":
                    # ignore pass for now
                    continue
                r, c = self._sgf_to_rc(coord, size=self.board.size)
                if r is None:
                    continue
                ok = self.board.play_move(color, (r, c))
                if not ok:
                    if DEBUG:
                        print("[Controller] failed to apply move", mv)
            else:
                # treat as coord only
                r, c = self._sgf_to_rc(mv, size=self.board.size)
                if r is None:
                    continue
                self.board.play_move('B', (r, c))
        # refresh view
        self._refresh_view()

    def _node_to_string(self, node) -> str:
        # Node -> string
        s = None
        if hasattr(node, "get_prop"):
            b = node.get_prop("B")
            w = node.get_prop("W")
            if b and len(b) > 0:
                s = f"B {b[0]}"
            elif w and len(w) > 0:
                s = f"W {w[0]}"
        else:
            for k, vals in getattr(node, "props", []):
                if k in ("B", "W") and vals:
                    s = f"{k} {vals[0]}"
                    break
        return s

    # --- helpers ---
    def _refresh_view(self):
        """ board: set board from model, queue_draw"""
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

    def _rc_to_sgf(self, r: int, c: int):
        return ''.join(chr(i + ord('a')) for i in (c, r))

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

    def _on_ctrl_click(self, r: int, c: int):
        mv = self._rc_to_sgf(r, c)
        print("[Controller] ctrl-click at", (r, c), "(%s)" % mv)
        game_tree = self.get_game_tree()
        print("[Controller] ctrl-click current_node id:", id(self.game_tree.current))
        if self.game_tree.current is None:
            return
        found_node = game_tree.ascend_to_move(self.game_tree.current, mv)
        print("[Controller] ctrl-click found:", found_node)
        if found_node is None:
            return
        self.game_tree.current = found_node

    def _on_game_tree_event(self, event, payload):
        """Handle events from GameTree."""
        print("[Controller] on_game_tree_event:", event, payload)
        if event == "current_changed":
            node = payload
            if self._board_view_node_cached is not node:
                # update board by applying moves from root to node
                try:
                    self._board_view_node_cached = node
                    self._on_board_changed(node)
                    path = self.tree.get_node_path(node) if getattr(self, "tree", None) else None
                    if path:
                        self._apply_move_sequence_to_board(path)
                except Exception:
                    pass
            else:
                self._refresh_view()
            # update tree canvas highlight
            if getattr(self, "tree_canvas", None):
                try:
                    self.tree_canvas.select_node(node)
                    # self.tree_canvas.queue_draw()
                except Exception:
                    pass
        elif event == "tree_loaded":
            root = payload
            if getattr(self, "tree_canvas", None):
                try:
                    pass
                except Exception:
                    pass
            try:
                self.game_tree.move_first()
            except Exception:
                pass
        elif event == "tree_changed":
            self.tree_canvas._recompute_layout()

    # navigation callbacks (buttons / keyboard call these)
    def go_prev(self):
        try:
            self.game_tree.move_prev()
        except Exception:
            pass

    def go_next(self):
        try:
            self.game_tree.move_next()
        except Exception:
            pass

    def go_first(self):
        try:
            self.game_tree.move_first()
        except Exception:
            pass

    def go_last(self):
        try:
            self.game_tree.move_last()
        except Exception:
            pass

    def _on_board_changed(self, node: Node | None):
        self._katago_controller_sync(node, force=False)

    def _katago_controller_sync(self, node: Node | None, force: bool = False):
        if node is None:
            return
        try:
            kc = KatagoController.get_instance()
        except Exception:
            # self._append_log_line("KataGo: controller not running")
            return
        if not (kc._is_analysis_started or force):
            return
        # if not current tab: return
        moves_seq = [
            f"{color} {board_coord_notation}"
            for color, sgf_move_notation, (row, col), board_coord_notation in (
                move_node.get_move()
                for move_node in self.get_game_tree().get_node_path(node)
                if move_node.get_move() is not None
            )
        ]
        if kc._is_analysis_started:
            kc.stop_analysis()
        kc.sync_to_move_sequence(moves_seq)
        kc.start_analysis()
