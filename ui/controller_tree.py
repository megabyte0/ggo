# ui/controller_tree.py
from typing import Any, List, Optional, Tuple
from ggo.game_tree import GameTree, Node
from datetime import datetime, timezone
import os

# DEBUG флаг: включи True для подробного вывода
DEBUG = False


class TreeAdapter:
    """
    Adapter for GameTree operations:
      - load GameTree instance
      - add_move (mutates tree)
      - get_node_path
      - collect AB/AW and mainline nodes
    """

    def __init__(self, get_game_tree):
        # self.get_game_tree(): Optional[GameTree] = None
        self.get_game_tree = get_game_tree

    def load(self):
        """
        Load a parsed GameTree instance and normalize synthetic root:
        - If synthetic root has no top-level game node, create one with default properties.
        Defaults are taken from pyproject.toml (project.name/project.version) when available,
        otherwise sensible fallbacks are used.
        """
        # self.get_game_tree() = gt
        if DEBUG:
            print("[TreeAdapter] load: game_tree loaded:", bool(self.get_game_tree()))
        self.get_game_tree().add_missing_game_props()

    def get_root(self) -> Optional[Node]:  # all usages are in the controller
        return self.get_game_tree().root if self.get_game_tree() else None

    def get_node_path(self, node: Node) -> List[Node]:
        if self.get_game_tree() and hasattr(self.get_game_tree(), "get_node_path"):
            return self.get_game_tree().get_node_path(node)
        # fallback: climb parents
        path = []
        cur = node
        while cur is not None:
            path.append(cur)
            cur = getattr(cur, "parent", None)
        path.reverse()
        return path

    def add_move(self, parent: Optional[Node], color: str = None, coord: str = None, props: Optional[Any] = None,
                 is_variation: Optional[bool] = None) -> Node:
        """
        Wrapper around GameTree.add_move that ensures in-place mutation and
        creates a game node under synthetic root when the first move is added.
        Behavior:
          - If parent is None: try last mainline node; if none, use synthetic root.
          - If parent is synthetic root and root has no game child (or first child has no B/W),
            create a new game node with default header props and attach it to root,
            then add the move under that new game node.
        """
        # if self.get_game_tree() is None:
        #     self.get_game_tree() = GameTree()
        assert self.get_game_tree() is not None

        root = self.get_game_tree().root

        # Resolve parent if None: prefer last mainline node, else synthetic root
        if parent is None:
            try:
                parent = self.find_last_mainline_node()
            except Exception:
                parent = None
            if parent is None:
                parent = root

        # If parent is synthetic root (root) ensure there is a game node to attach to
        if parent is root:
            need_game_node = self.get_game_tree().need_game_node()

            if need_game_node:
                parent = self.get_game_tree().add_missing_game_props_1()

        # Now call underlying GameTree.add_move with resolved parent
        node = self.get_game_tree().add_move(parent, color, coord, props=props, is_variation=is_variation)
        if DEBUG:
            print("[TreeAdapter] add_move parent resolved to:", parent, "-> new node:", node)
        return node

    def find_last_mainline_node(self) -> Optional[Node]:
        if self.get_game_tree() and hasattr(self.get_game_tree(), "find_last_mainline_node"):
            return self.get_game_tree().find_last_mainline_node()
        # fallback: traverse first top child
        if not self.get_game_tree() or not self.get_game_tree().root.children:
            return None
        cur = self.get_game_tree().root.children[0]
        while True:
            next_child = None
            for c in getattr(cur, "children", []):
                if not getattr(c, "_is_variation", False):
                    next_child = c
                    break
            if next_child is None:
                return cur
            cur = next_child

    def collect_ab_aw(self) -> List[Tuple[str, Tuple[int, int]]]:
        """
        Collect AB/AW from root and first child.
        Returns list of tuples ("B"/"W", sgf_coord_string).
        Conversion to numeric coords is left to caller.
        """
        stones = []
        if not self.get_game_tree():
            return stones
        root = self.get_game_tree().root

        def collect(node):
            for k, vals in getattr(node, "props", []):
                if k == "AB":
                    for v in vals:
                        stones.append(("B", v))
                elif k == "AW":
                    for v in vals:
                        stones.append(("W", v))

        collect(root)
        if root.children:
            collect(root.children[0])
        if DEBUG:
            print("[TreeAdapter] collected AB/AW:", stones)
        return stones

    def collect_mainline_nodes(self) -> List[Node]:
        """Return nodes along mainline from first top child."""
        if not self.get_game_tree() or not self.get_game_tree().root.children:
            return []
        start = self.get_game_tree().root.children[0]
        res = []
        cur = start
        while cur is not None:
            res.append(cur)
            next_child = None
            for c in getattr(cur, "children", []):
                if not getattr(c, "_is_variation", False):
                    next_child = c
                    break
            cur = next_child
        return res
