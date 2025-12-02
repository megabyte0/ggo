# ui/controller.py
from gi.repository import GLib, Gdk
from ggo.goban_model import Board, IllegalMove
from ggo.game_tree import GameTree, Node
from ui.board_view import BoardView

class BoardController:
    def __init__(self, board_view: BoardView, board_size=19, katago_enabled=False):
        self.model = Board(size=board_size)
        self.view = board_view
        self.katago_enabled = katago_enabled

        # Game tree
        self.game_tree = GameTree()
        self.current_node = self.game_tree.root

        # TreeStore widgets will be provided by main_app (set after controller created)
        self._lbl_winprob = None
        self._lbl_scorelead = None

        self.game_tree = GameTree()
        self.current_node = self.game_tree.root
        self.tree_canvas = None

        # wire view callbacks
        self.view.on_click(self._on_click)
        self.view.on_hover(self._on_hover)
        self.view.on_leave(self._on_leave)

        # initial render
        self._refresh_view()

    # ---------- Tree UI integration ----------
    def attach_tree_widgets(self, tree_store, tree_view):
        """Main app calls this to give controller access to TreeStore and TreeView."""
        self.tree_store = tree_store
        self.tree_view = tree_view
        # connect selection changed
        sel = self.tree_view.get_selection()
        sel.connect("changed", self._on_tree_selection_changed)
        # initial populate
        self.rebuild_tree_store()

    def rebuild_tree_store(self):
        """Rebuild Gtk.TreeStore from self.game_tree.root recursively."""
        if self.tree_store is None:
            return
        self.tree_store.clear()
        def add_node_recursive(parent_iter, node: Node):
            # display text: move or root
            text = node.move if node.move else "(root)"
            iter_ = self.tree_store.append(parent_iter, [text, node])
            for child in node.children:
                add_node_recursive(iter_, child)
        # add children of root as top-level trees
        for child in self.game_tree.root.children:
            add_node_recursive(None, child)

    def _on_tree_selection_changed(self, selection):
        model, treeiter = selection.get_selected()
        if treeiter is None:
            return
        node = model[treeiter][1]  # stored Node object
        if node:
            # go to this node: set current_node and update board
            self.current_node = node
            moves = self.game_tree.get_node_path(node)
            # moves are strings like "B Q16" or "W D4" depending on implementation
            # convert to sequence of (color, gtp_move) and apply via model
            self._apply_move_sequence_to_model(moves)
            GLib.idle_add(self._refresh_view)

    # ---------- Click handling on board ----------
    def _on_click(self, r, c, n_press):
        color = self.model.current_player()
        gtp_move = self._rc_to_gtp((r, c))
        # check existing child
        found = None
        for child in self.current_node.children:
            mv = child.move or ""
            if mv.endswith(gtp_move) or mv == f"{color} {gtp_move}" or mv == gtp_move:
                found = child
                break
        if found is None:
            new_node = self.game_tree.add_move(self.current_node, color, gtp_move, props={})
            # try to apply move
            try:
                self.model.play(color, point=(r, c))
            except IllegalMove as e:
                # rollback tree addition
                self.current_node.children.remove(new_node)
                print("Illegal move on click:", e)
                return
            # advance current node
            self.current_node = new_node
            # update canvas
            self.rebuild_tree_canvas()
            # select new node
            if self.tree_canvas:
                self.tree_canvas.select_node(new_node)
            GLib.idle_add(self._refresh_view)
        else:
            # navigate into existing child
            self.current_node = found
            moves = self.game_tree.get_node_path(found)
            self._apply_move_sequence_to_model(moves)
            self.rebuild_tree_canvas()
            if self.tree_canvas:
                self.tree_canvas.select_node(found)
            GLib.idle_add(self._refresh_view)

    def _select_node_in_tree(self, node: Node):
        """Find treeiter for node and select it."""
        if self.tree_store is None:
            return False
        def find_iter(model, treeiter):
            # DFS search
            while treeiter:
                n = model[treeiter][1]
                if n is node:
                    self.tree_view.get_selection().select_iter(treeiter)
                    return True
                # descend
                child = model.iter_children(treeiter)
                if child and find_iter(model, child):
                    return True
                treeiter = model.iter_next(treeiter)
            return False
        # search top-level iters
        it = self.tree_store.get_iter_first()
        while it:
            if find_iter(self.tree_store, it):
                return False
            it = self.tree_store.iter_next(it)
        return False

    # ---------- Helpers: apply sequence to model ----------
    def _apply_move_sequence_to_model(self, moves: list):
        """
        moves: list of move strings as returned by GameTree.get_node_path,
        e.g. ["B Q16", "W D4", ...] or ["Q16", "D4"] depending on GameTree.
        We will reset model to root and replay moves.
        """
        # reset model
        # simplest: create new Board and replay moves
        size = self.model.size
        self.model = Board(size=size)
        for mv in moves:
            if not mv:
                continue
            # normalize
            if ' ' in mv:
                color, gtp = mv.split(' ', 1)
            else:
                # assume alternating colors starting with B if model.move_number==0
                # but safer: if mv stored without color, alternate based on move index
                idx = moves.index(mv)
                color = 'B' if idx % 2 == 0 else 'W'
                gtp = mv
            r,c = self._gtp_to_rc(gtp)
            try:
                self.model.play(color, point=(r, c))
            except IllegalMove as e:
                print("Error applying move sequence:", e)
                break

    # ---------- Hover handlers (keep existing behavior) ----------
    def _on_hover(self, r, c):
        # show ghost only if legal
        from ggo.goban_model import Move
        color = self.model.current_player()
        mv = Move(color=color, point=(r,c), is_pass=False, is_resign=False, move_number=self.model.move_number+1)
        try:
            self.model.legal(mv)
            legal = True
        except IllegalMove:
            legal = False
        if legal:
            self.view.show_ghost((r,c), color)
        else:
            self.view.clear_ghost()

    def _on_leave(self):
        self.view.clear_ghost()

    # ---------- Utility: coordinate conversions ----------
    def _rc_to_gtp(self, pt: tuple) -> str:
        r, c = pt
        # GTP columns: A..T skipping I is common, but many GUIs use A..T without skip.
        # We'll use letters A..T and numbers 1..19 with row = size - r
        col_letter = chr(ord('A') + c)
        row_number = self.model.size - r
        return f"{col_letter}{row_number}"

    def _gtp_to_rc(self, s: str) -> tuple:
        s = s.strip().upper()
        col = ord(s[0]) - ord('A')
        row = int(s[1:])
        r = self.model.size - row
        c = col
        return (r, c)

    # ---------- Refresh view ----------
    def _refresh_view(self):
        self.view.set_board(self.model.get_board())

    def set_top_info_widgets(self, lbl_winprob_widget, lbl_scorelead_widget):
        """Main app передаёт сюда виджеты, контроллер будет обновлять их."""
        self._lbl_winprob = lbl_winprob_widget
        self._lbl_scorelead = lbl_scorelead_widget
        # сразу обновим (если есть данные)
        self._update_top_info(None, None)

    def _update_top_info(self, winprob: float, scorelead: float):
        """Обновляет метки над доской. Вызывать из GLib main loop."""
        if self._lbl_winprob is not None:
            text = f"Win: {winprob*100:.1f}%" if winprob is not None else "Win: —"
            # set_text должен вызываться в главном потоке; GLib.idle_add безопасен
            GLib.idle_add(self._lbl_winprob.set_text, text)
        if self._lbl_scorelead is not None:
            text = f"Score lead: {scorelead:+.2f}" if scorelead is not None else "Score lead: —"
            GLib.idle_add(self._lbl_scorelead.set_text, text)

    def attach_tree_canvas(self, tree_canvas):
        """Привязать TreeCanvas виджет, контроллер будет обновлять его."""
        self.tree_canvas = tree_canvas
        # set callback for selection
        self.tree_canvas.set_on_node_selected(self._on_tree_node_selected)
        # initial populate
        self.rebuild_tree_canvas()

    def rebuild_tree_canvas(self):
        if not self.tree_canvas:
            return
        # pass root to canvas
        self.tree_canvas.set_tree_root(self.game_tree.root)
        # optionally select current node
        self.tree_canvas.select_node(self.current_node)

    def _on_tree_node_selected(self, node):
        # when user clicks node in canvas, navigate to it
        self.current_node = node
        moves = self.game_tree.get_node_path(node)
        self._apply_move_sequence_to_model(moves)
        GLib.idle_add(self._refresh_view)
        # update canvas selection
        if self.tree_canvas:
            self.tree_canvas.select_node(node)

