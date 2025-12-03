# ui/controller.py
from typing import Any, List, Tuple, Optional
from gi.repository import GLib

from ui.controller_board import BoardAdapter, DEBUG as BOARD_DEBUG
from ui.controller_tree import TreeAdapter, DEBUG as TREE_DEBUG
from ggo.game_tree import GameTree, Node

# enable debug here
DEBUG = True
BOARD_DEBUG = DEBUG
TREE_DEBUG = DEBUG


class Controller:
    """
    Controller coordinates BoardAdapter (board view/model) and TreeAdapter (game tree).
    Responsibilities:
      - handle board clicks and hover and translate to tree mutations (add_move)
      - attach TreeCanvas via TreeAdapter
      - load GameTree into the UI and apply mainline moves to the board
      - navigation (first/prev/next/last)
    """

    def __init__(self, board: BoardAdapter):
        self.board = board
        self.tree: Optional[TreeAdapter] = None
        self.current_node: Optional[Node] = None

        # top info widgets (labels) set by MainWindow
        self._lbl_winprob = None
        self._lbl_scorelead = None

        if BOARD_DEBUG:
            print("[Controller] initialized with board id:", id(board))

        # Try to wire board events (click / hover) to controller handlers.
        # Support several possible signal names to be robust across board implementations.
        try:
            # GTK-style connect or adapter connect
            if hasattr(self.board, "connect"):
                # click signal variants
                for sig in ("clicked", "click", "button-press-event", "board-click"):
                    try:
                        # many GTK callbacks pass (widget, event) or (widget, r, c)
                        # use a wrapper that tolerates different signatures
                        def make_click_handler():
                            def handler(*args, **kwargs):
                                # try to extract r,c from args or event
                                r = c = None
                                # common: handler(widget, r, c)
                                if len(args) >= 3 and isinstance(args[1], int) and isinstance(args[2], int):
                                    r, c = args[1], args[2]
                                # common GTK: handler(widget, event) -> event has coords or grid indices
                                elif len(args) >= 2:
                                    ev = args[1]
                                    try:
                                        # if event provides board indices
                                        if hasattr(ev, "r") and hasattr(ev, "c"):
                                            r, c = ev.r, ev.c
                                        # if event has x/y pixel coords, board may expose mapping
                                        elif hasattr(self.board, "pixel_to_cell"):
                                            try:
                                                r, c = self.board.pixel_to_cell(ev.x, ev.y)
                                            except Exception:
                                                r = c = None
                                    except Exception:
                                        r = c = None
                                # adapter-style: handler(r, c)
                                elif len(args) >= 2 and isinstance(args[0], int) and isinstance(args[1], int):
                                    r, c = args[0], args[1]
                                # fallback: ignore
                                if r is not None and c is not None:
                                    try:
                                        self._on_click(r, c, 1)
                                    except Exception as e:
                                        print("[WARN] Controller: click handler raised:", e)
                                return None
                            return handler
                        self.board.connect(sig, make_click_handler())
                    except Exception:
                        pass
                # hover/motion signal variants
                for sig in ("hovered", "motion-notify-event", "board-hover", "motion"):
                    try:
                        def make_hover_handler():
                            def handler(*args, **kwargs):
                                r = c = None
                                if len(args) >= 3 and isinstance(args[1], int) and isinstance(args[2], int):
                                    r, c = args[1], args[2]
                                elif len(args) >= 2:
                                    ev = args[1]
                                    try:
                                        if hasattr(ev, "r") and hasattr(ev, "c"):
                                            r, c = ev.r, ev.c
                                        elif hasattr(self.board, "pixel_to_cell"):
                                            try:
                                                r, c = self.board.pixel_to_cell(ev.x, ev.y)
                                            except Exception:
                                                r = c = None
                                    except Exception:
                                        r = c = None
                                elif len(args) >= 2 and isinstance(args[0], int) and isinstance(args[1], int):
                                    r, c = args[0], args[1]
                                if r is not None and c is not None:
                                    try:
                                        self._on_hover(r, c)
                                    except Exception as e:
                                        print("[WARN] Controller: hover handler raised:", e)
                                return None
                            return handler
                        self.board.connect(sig, make_hover_handler())
                    except Exception:
                        pass

            # adapter-style callbacks
            if hasattr(self.board, "set_on_click"):
                try:
                    self.board.set_on_click(lambda r, c, n=1: self._on_click(r, c, n))
                except Exception:
                    pass
            if hasattr(self.board, "set_on_hover"):
                try:
                    self.board.set_on_hover(lambda r, c: self._on_hover(r, c))
                except Exception:
                    pass
        except Exception as e:
            print("[WARN] Controller: failed to wire board events:", e)

    # -------------------------
    # Wiring
    # -------------------------
    def attach_tree_canvas(self, tree_canvas_adapter: TreeAdapter):
        """
        Attach TreeAdapter (or TreeCanvas wrapper) so controller can update tree view.
        """
        self.tree = tree_canvas_adapter
        if TREE_DEBUG:
            print("[Controller] attach_tree_canvas setting root from",
                  id(getattr(self.tree, "root", None)),
                  "to", id(getattr(self.tree, "root", None)))
        # refresh view once attached
        try:
            GLib.idle_add(self._refresh_view)
        except Exception:
            pass

    def set_top_info_widgets(self, lbl_winprob, lbl_scorelead):
        self._lbl_winprob = lbl_winprob
        self._lbl_scorelead = lbl_scorelead

    # -------------------------
    # Board interaction: hover + click
    # -------------------------
    def _on_hover(self, r: int, c: int):
        """
        Called when pointer hovers over board cell (r,c).
        Should be lightweight and not raise.
        """
        try:
            coord = chr(ord('a') + c) + chr(ord('a') + r)
            if BOARD_DEBUG:
                print("[DBG board] hover r,c:", (r, c), "sgf:", coord)
            # If board supports showing a ghost stone or highlight, call it
            try:
                if getattr(self.board, "show_hover", None):
                    self.board.show_hover(r, c)
            except Exception:
                pass
            # Optionally update top info label with hovered coord (non-intrusive)
            try:
                if self._lbl_winprob is not None:
                    # keep existing text; do not overwrite important info
                    pass
            except Exception:
                pass
        except Exception as e:
            print("[WARN] Controller._on_hover failed:", e)

    def _on_click(self, r: int, c: int, n_press: int = 1):
        """
        Called when board is clicked. Translate to SGF coord and add move via TreeAdapter.
        """
        try:
            color = self.board.current_player() if getattr(self.board, "current_player", None) else None
            sgf_coord = chr(ord('a') + c) + chr(ord('a') + r)
            if BOARD_DEBUG:
                print("[DBG board] click r,c:", (r, c), "sgf:", sgf_coord, "color:", color,
                      "current_node id:", id(self.current_node) if getattr(self, "current_node", None) else None)
        except Exception as e:
            print("[WARN] Controller._on_click: failed to read board state:", e)
            color = None
            sgf_coord = chr(ord('a') + c) + chr(ord('a') + r)

        # Determine parent node for new move
        parent = self.current_node
        if parent is None:
            # try to find last mainline node
            try:
                parent = self.find_last_mainline_node()
            except Exception:
                parent = None

        if DEBUG:
            print("[Controller] adding move under parent:", parent)

        # Add move via TreeAdapter / GameTree
        try:
            if self.tree is None:
                print("[WARN] Controller: no tree adapter attached; cannot add move")
                return
            node = self.tree.add_move(parent, color=color, coord=sgf_coord)
            if DEBUG:
                print("[DBG add_move] Controller id:", id(self), "TreeAdapter id:", id(self.tree), "game_tree id:", id(getattr(self.tree, 'game_tree', None)))
                print("[DBG add_move] parent:", parent, "new_node:", node)
            # update current_node and refresh
            self.current_node = node
            try:
                GLib.idle_add(self._refresh_view)
            except Exception:
                pass
        except Exception as e:
            print("[WARN] Controller._on_click: add_move failed:", e)

        # debug: log node context
        if getattr(self, "current_node", None):
            try:
                self._log_node_context(self.current_node)
            except Exception as e:
                print("[WARN] Controller._on_click: _log_node_context raised:", e)

    def _log_node_context(self, node: Node):
        """
        Debug helper: print node props, parent, children count and path.
        """
        try:
            nid = id(node)
            props = getattr(node, "props", None)
            parent = getattr(node, "parent", None)
            children = getattr(node, "children", None)
            print("[DBG node] id:", nid, "props:", props, "parent id:", id(parent) if parent else None, "children:", len(children) if children is not None else None)
            # print path from root to node
            path = []
            cur = node
            while cur is not None:
                mv = None
                try:
                    if hasattr(cur, "get_prop"):
                        b = cur.get_prop("B"); w = cur.get_prop("W")
                        if b and len(b) > 0:
                            mv = f"B {b[0]}"
                        elif w and len(w) > 0:
                            mv = f"W {w[0]}"
                    else:
                        for k, vals in getattr(cur, "props", []):
                            if k in ("B", "W") and vals:
                                mv = f"{k} {vals[0]}"
                                break
                except Exception:
                    mv = None
                path.append(mv or "(no-move)")
                cur = getattr(cur, "parent", None)
            path.reverse()
            print("[DBG node] path (root->node):", " -> ".join(path))
        except Exception as e:
            print("[WARN] Controller._log_node_context failed:", e)

    # -------------------------
    # Tree selection
    # -------------------------
    def _on_tree_node_selected(self, node: Optional[Node]):
        """
        Called when user selects a node in the tree view.
        Controller should update board to reflect node's position.
        """
        if node is None:
            return
        self.current_node = node
        # debug: log node context
        try:
            self._log_node_context(node)
        except Exception as e:
            print("[WARN] Controller._on_tree_node_selected: _log_node_context raised:", e)

        # compute move sequence from root to this node and apply to board
        try:
            moves = self.tree.get_node_path(node)
            if DEBUG:
                print("[Controller] applying move sequence:", moves)
            self._apply_move_sequence_to_board(moves)
            GLib.idle_add(self._refresh_view)
        except Exception as e:
            print("[WARN] Controller._on_tree_node_selected: failed to apply move sequence:", e)

    # -------------------------
    # Navigation helpers
    # -------------------------
    def find_last_mainline_node(self) -> Optional[Node]:
        """
        Return last node on mainline (first-child chain) or None.
        """
        if self.tree and hasattr(self.tree, "find_last_mainline_node"):
            try:
                return self.tree.find_last_mainline_node()
            except Exception:
                pass
        # fallback: traverse root -> first child chain
        try:
            gt = getattr(self.tree, "game_tree", None)
            if gt is None:
                return None
            root = getattr(gt, "root", None)
            if root is None:
                return None
            cur = root
            last = None
            while True:
                children = getattr(cur, "children", None) or []
                if not children:
                    break
                # pick first child as mainline
                cur = children[0]
                last = cur
            return last
        except Exception:
            return None

    def go_first(self):
        # set current_node to first move (root's first child)
        try:
            gt = getattr(self.tree, "game_tree", None)
            if gt and getattr(gt, "root", None) and getattr(gt.root, "children", None):
                self.current_node = gt.root.children[0]
                self._apply_move_sequence_to_board(self.tree.get_node_path(self.current_node))
                GLib.idle_add(self._refresh_view)
        except Exception as e:
            print("[WARN] Controller.go_first failed:", e)

    def go_prev(self):
        # move to parent of current_node
        try:
            if self.current_node and getattr(self.current_node, "parent", None):
                self.current_node = self.current_node.parent
                self._apply_move_sequence_to_board(self.tree.get_node_path(self.current_node))
                GLib.idle_add(self._refresh_view)
        except Exception as e:
            print("[WARN] Controller.go_prev failed:", e)

    def go_next(self):
        # move to first child of current_node
        try:
            if self.current_node and getattr(self.current_node, "children", None):
                children = getattr(self.current_node, "children", [])
                if children:
                    self.current_node = children[0]
                    self._apply_move_sequence_to_board(self.tree.get_node_path(self.current_node))
                    GLib.idle_add(self._refresh_view)
        except Exception as e:
            print("[WARN] Controller.go_next failed:", e)

    def go_last(self):
        # move to last node on mainline
        try:
            last = self.find_last_mainline_node()
            if last:
                self.current_node = last
                self._apply_move_sequence_to_board(self.tree.get_node_path(self.current_node))
                GLib.idle_add(self._refresh_view)
        except Exception as e:
            print("[WARN] Controller.go_last failed:", e)

    # -------------------------
    # Board application helpers
    # -------------------------
    def _apply_move_sequence_to_board(self, moves: List[Any]) -> bool:
        """
        Apply a sequence of moves (list of Node or list of SGF move strings) to the board model/view.
        Tries several board APIs in order and returns True on success, False otherwise.
        This function is defensive: it resets/clears the board if possible before applying moves.
        """
        if moves is None:
            return False

        # Normalize moves into list of (color, coord) tuples or SGF strings
        normalized: List[Any] = []
        for m in moves:
            # Node-like object: try to extract B/W props
            try:
                if hasattr(m, "get_prop") or hasattr(m, "props"):
                    color = None
                    coord = None
                    if hasattr(m, "get_prop"):
                        b = m.get_prop("B"); w = m.get_prop("W")
                        if b and len(b) > 0:
                            color = "B"; coord = b[0]
                        elif w and len(w) > 0:
                            color = "W"; coord = w[0]
                    else:
                        for k, vals in getattr(m, "props", []):
                            if k == "B" and vals:
                                color = "B"; coord = vals[0]; break
                            if k == "W" and vals:
                                color = "W"; coord = vals[0]; break
                    if color is not None and coord is not None:
                        normalized.append((color, coord))
                        continue
            except Exception:
                pass

            # Fallback: string form like "B pd" or "pd"
            try:
                s = str(m).strip()
                if " " in s:
                    parts = s.split(None, 1)
                    normalized.append((parts[0], parts[1]))
                else:
                    normalized.append(s)
            except Exception:
                continue

        # Reset/clear board if possible
        try:
            if getattr(self, "board", None):
                if hasattr(self.board, "reset"):
                    try:
                        self.board.reset()
                        print("[Controller] board.reset() called before applying loaded moves")
                    except Exception as e:
                        print("[WARN] Controller: board.reset() raised:", e)
                elif hasattr(self.board, "clear"):
                    try:
                        self.board.clear()
                        print("[Controller] board.clear() called before applying loaded moves")
                    except Exception as e:
                        print("[WARN] Controller: board.clear() raised:", e)
        except Exception as e:
            print("[WARN] Controller: error while trying to reset board:", e)

        # Try bulk APIs first
        try:
            if getattr(self, "board", None):
                if hasattr(self.board, "set_moves"):
                    try:
                        self.board.set_moves(normalized)
                        print("[Controller] board.set_moves applied")
                        return True
                    except Exception as e:
                        print("[WARN] Controller: board.set_moves failed:", e)
                if hasattr(self.board, "apply_sgf_moves"):
                    try:
                        self.board.apply_sgf_moves(normalized)
                        print("[Controller] board.apply_sgf_moves applied")
                        return True
                    except Exception as e:
                        print("[WARN] Controller: board.apply_sgf_moves failed:", e)

                # Fallback: play moves one by one
                if hasattr(self.board, "play_move_sgf"):
                    ok = True
                    for mv in normalized:
                        try:
                            if isinstance(mv, tuple):
                                color, coord = mv
                                self.board.play_move_sgf(f"{color} {coord}")
                            else:
                                self.board.play_move_sgf(str(mv))
                        except Exception as e:
                            print("[WARN] Controller: board.play_move_sgf failed for", mv, ":", e)
                            ok = False
                            break
                    if ok:
                        return True

                if hasattr(self.board, "play_move"):
                    ok = True
                    for mv in normalized:
                        try:
                            if isinstance(mv, tuple):
                                color, coord = mv
                                self.board.play_move(color, coord)
                            else:
                                s = str(mv)
                                if " " in s:
                                    c, co = s.split(None, 1)
                                    self.board.play_move(c, co)
                                else:
                                    raise RuntimeError("unknown move format")
                        except Exception as e:
                            print("[WARN] Controller: board.play_move failed for", mv, ":", e)
                            ok = False
                            break
                    if ok:
                        return True
        except Exception as e:
            print("[WARN] Controller: error while applying moves to board:", e)

        print("[WARN] Controller: no suitable board API found to apply loaded moves")
        return False

    # -------------------------
    # Loading GameTree
    # -------------------------
    def load_game_tree(self, gt: GameTree):
        """
        Load a GameTree into the controller's TreeAdapter and apply its mainline to the board.
        Resets the board (if possible) and sets current_node to the last mainline node.
        """
        try:
            if getattr(self, "tree", None) is None:
                print("[Controller] load_game_tree: no tree adapter attached")
                return
            try:
                self.tree.game_tree = gt
            except Exception as e:
                print("[WARN] Controller.load_game_tree: failed to set tree.game_tree:", e)
                self.tree.game_tree = gt

            # collect mainline nodes
            main_nodes: List[Node] = []
            try:
                if hasattr(self.tree, "collect_mainline_nodes"):
                    main_nodes = self.tree.collect_mainline_nodes()
                else:
                    root = getattr(gt, "root", None)
                    if root and getattr(root, "children", None):
                        cur = root.children[0]
                        while cur is not None:
                            main_nodes.append(cur)
                            next_child = None
                            for c in getattr(cur, "children", []):
                                if not getattr(c, "_is_variation", False):
                                    next_child = c
                                    break
                            cur = next_child
            except Exception as e:
                print("[WARN] Controller.load_game_tree: failed to enumerate mainline nodes:", e)

            # apply moves
            applied = False
            try:
                applied = self._apply_move_sequence_to_board(main_nodes)
            except Exception as e:
                print("[WARN] Controller.load_game_tree: applying moves raised:", e)

            if applied:
                print("[Controller] load_game_tree: applied mainline moves")
            else:
                print("[Controller] load_game_tree: failed to apply moves to board")

            # set current_node
            if main_nodes:
                self.current_node = main_nodes[-1]
            else:
                try:
                    root = getattr(gt, "root", None)
                    if root and getattr(root, "children", None):
                        self.current_node = root.children[0]
                    else:
                        self.current_node = None
                except Exception:
                    self.current_node = None

            try:
                GLib.idle_add(self._refresh_view)
            except Exception:
                pass
        except Exception as e:
            print("[WARN] Controller.load_game_tree unexpected error:", e)

    # -------------------------
    # Refresh / view update
    # -------------------------
    def _refresh_view(self):
        """
        Called via GLib.idle_add to refresh board and tree views.
        """
        try:
            # update board widgets (if any)
            try:
                if getattr(self, "board", None) and hasattr(self.board, "refresh"):
                    self.board.refresh()
            except Exception:
                pass

            # update tree canvas if attached
            try:
                if getattr(self, "tree", None) and hasattr(self.tree, "refresh"):
                    self.tree.refresh()
            except Exception:
                pass

            # update top info labels if available
            try:
                if self._lbl_winprob is not None:
                    # placeholder: compute winprob from current_node or tree
                    self._lbl_winprob.set_text("Win: —")
                if self._lbl_scorelead is not None:
                    self._lbl_scorelead.set_text("Score lead: —")
            except Exception:
                pass
        except Exception as e:
            print("[WARN] Controller._refresh_view failed:", e)
        return False  # GLib.idle_add: return False to run once
