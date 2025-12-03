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

    def __init__(self):
        self.game_tree: Optional[GameTree] = None

    def load(self, gt: GameTree):
        """
        Load a parsed GameTree instance and normalize synthetic root:
        - If synthetic root has no top-level game node, create one with default properties.
        Defaults are taken from pyproject.toml (project.name/project.version) when available,
        otherwise sensible fallbacks are used.
        """
        self.game_tree = gt
        if DEBUG:
            print("[TreeAdapter] load: game_tree loaded:", bool(self.game_tree))

        # --- normalization: ensure at least one game node under synthetic root ---
        root = self.game_tree.root if self.game_tree else None
        if root is None:
            return

        # If root already has children, we leave structure as-is
        if getattr(root, "children", None):
            if DEBUG:
                print("[TreeAdapter] load: root already has children:", len(root.children))
            return

        # read defaults: prefer pyproject.toml project.name and project.version
        defaults = self._defaults_from_pyproject()

        # create a Node under synthetic root with canonical game properties
        try:
            node = Node(parent=root, is_variation=False)
        except TypeError:
            # older Node signature may not accept is_variation
            node = Node(parent=root)

        # canonical order of properties in SGF header
        order = ["GM", "FF", "CA", "AP", "KM", "SZ", "DT"]
        for k in order:
            v = defaults.get(k)
            if v is None:
                continue
            # append as single property entry preserving order
            node.props.append((k, [v]))

        # attach node to synthetic root
        root.children.append(node)
        node.parent = root

        if DEBUG:
            print("[TreeAdapter] load: created default game node under synthetic root with props:", node.props)

    def _defaults_from_pyproject(self, path: str = "../pyproject.toml") -> dict:
        """
        Try to read project.name and project.version from pyproject.toml.
        Fallback to sensible defaults if file not found or parsing fails.
        Returns dict with keys: GM, FF, CA, AP, KM, SZ, DT
        Note: GM is set to "<name> <version>" if available, else "1".
        AP is set to "name:version" if available, else "ggo:0.1".
        DT is current UTC date YYYY-MM-DD.
        """
        defaults = {}
        name = None
        version = None

        print("[TreeAdapter] reading ", path, " at", os.getcwd())
        # try tomllib (py3.11+), then toml package, then fallback
        try:
            try:
                import tomllib  # Python 3.11+
                if os.path.exists(path):
                    with open(path, "rb") as f:
                        data = tomllib.load(f)
                else:
                    data = {}
            except Exception as e:
                print("[TreeAdapter] failed to load pyproject.toml:", path, e)
                # try toml package
                try:
                    import toml
                    if os.path.exists(path):
                        with open(path, "r", encoding="utf-8") as f:
                            data = toml.load(f)
                    else:
                        data = {}
                except Exception as e:
                    print("[TreeAdapter] failed to load pyproject.toml:", path, e)
                    data = {}
            # project table may be under 'project' (PEP 621) or under 'tool.poetry'
            if isinstance(data, dict):
                proj = data.get("project")
                if proj and isinstance(proj, dict):
                    name = proj.get("name")
                    version = proj.get("version")
                else:
                    # poetry style
                    tool = data.get("tool", {})
                    poetry = tool.get("poetry") if isinstance(tool, dict) else None
                    if poetry and isinstance(poetry, dict):
                        name = poetry.get("name")
                        version = poetry.get("version")
        except Exception as e:
            print("[TreeAdapter] failed to load pyproject.toml:", path, e)
            name = None
            version = None

        # build defaults
        if name and version:
            gm_val = f"{name} {version}"
            ap_val = f"{name}:{version}"
        elif name:
            gm_val = f"{name}"
            ap_val = f"{name}:0.0"
        else:
            gm_val = "1"
            ap_val = "ggo:0.1"

        defaults["GM"] = "1"  # str(gm_val)
        defaults["FF"] = "4"
        defaults["CA"] = "UTF-8"
        defaults["AP"] = ap_val
        defaults["KM"] = "6.5"
        defaults["SZ"] = "19"
        # UTC date
        try:
            dt = datetime.now(timezone.utc).date().isoformat()
            defaults["DT"] = dt
        except Exception:
            defaults["DT"] = ""

        if DEBUG:
            print("[TreeAdapter] defaults_from_pyproject:", defaults, "pyproject read name/version:", name, version)

        return defaults

    def get_root(self) -> Optional[Node]:
        return self.game_tree.root if self.game_tree else None

    def get_node_path(self, node: Node) -> List[Node]:
        if self.game_tree and hasattr(self.game_tree, "get_node_path"):
            return self.game_tree.get_node_path(node)
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
        if self.game_tree is None:
            self.game_tree = GameTree()
        # ensure game_tree.root exists
        if getattr(self.game_tree, "root", None) is None:
            try:
                r = Node(parent=None)
                setattr(self.game_tree, "root", r)
                if DEBUG:
                    print("[DBG fix] created missing game_tree.root id:", id(r))
            except Exception as e:
                print("[DBG fix] failed to create root:", e)

        root = self.game_tree.root

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
            need_game_node = False
            if not getattr(root, "children", []):
                need_game_node = True
            else:
                first = root.children[0]
                # check if first child has a move (B/W)
                has_move = False
                for k, vals in getattr(first, "props", []):
                    if k in ("B", "W") and vals:
                        has_move = True
                        break
                if not has_move:
                    # if first child is property-only, treat it as header: create a new game node
                    # and attach it after header (we keep header as properties on root if desired)
                    need_game_node = True

            if need_game_node:
                # build defaults (minimal): GM from pyproject (name+version) if available, else "1"
                gm = "1"
                ap = "ggo:0.1"
                try:
                    # try tomllib (py3.11+) then toml
                    import os
                    try:
                        import tomllib
                        if os.path.exists("pyproject.toml"):
                            with open("pyproject.toml", "rb") as f:
                                data = tomllib.load(f)
                        else:
                            data = {}
                    except Exception:
                        try:
                            import toml
                            if os.path.exists("pyproject.toml"):
                                with open("pyproject.toml", "r", encoding="utf-8") as f:
                                    data = toml.load(f)
                            else:
                                data = {}
                        except Exception:
                            data = {}
                    name = None
                    version = None
                    if isinstance(data, dict):
                        proj = data.get("project")
                        if proj and isinstance(proj, dict):
                            name = proj.get("name")
                            version = proj.get("version")
                        else:
                            tool = data.get("tool", {})
                            poetry = tool.get("poetry") if isinstance(tool, dict) else None
                            if poetry and isinstance(poetry, dict):
                                name = poetry.get("name")
                                version = poetry.get("version")
                    if name and version:
                        gm = f"{name} {version}"
                        ap = f"{name}:{version}"
                    elif name:
                        gm = str(name)
                        ap = f"{name}:0.0"
                except Exception:
                    pass

                # create the game node and attach to root
                try:
                    game_node = Node(parent=root, is_variation=False)
                except TypeError:
                    game_node = Node(parent=root)
                # canonical header props
                from datetime import datetime, timezone
                dt = datetime.now(timezone.utc).date().isoformat()
                header_order = [("GM", [gm]), ("FF", ["4"]), ("CA", ["UTF-8"]), ("AP", [ap]), ("KM", ["6.5"]),
                                ("SZ", ["19"]), ("DT", [dt])]
                for k, vals in header_order:
                    game_node.props.append((k, list(vals)))
                root.children.append(game_node)
                game_node.parent = root
                parent = game_node

        # Now call underlying GameTree.add_move with resolved parent
        node = self.game_tree.add_move(parent, color, coord, props=props, is_variation=is_variation)
        if DEBUG:
            print("[TreeAdapter] add_move parent resolved to:", parent, "-> new node:", node)
        # debug: print ids and parent path
        try:
            print("[DBG add_move] TreeAdapter id:", id(self), "game_tree id:", id(getattr(self, 'game_tree', None)))
            print("[DBG add_move] parent id:", id(parent) if parent else None, "new_node id:", id(node), "props:", getattr(node, 'props', None))
            cur = parent
            chain = []
            while cur is not None:
                mv = None
                if hasattr(cur, "get_prop"):
                    b = cur.get_prop("B"); w = cur.get_prop("W")
                    if b and len(b)>0: mv = f"B {b[0]}"
                    elif w and len(w)>0: mv = f"W {w[0]}"
                else:
                    for k, vals in getattr(cur, "props", []):
                        if k in ("B","W") and vals:
                            mv = f"{k} {vals[0]}"
                            break
                chain.append(mv or "(no-move)")
                cur = getattr(cur, "parent", None)
            chain.reverse()
            print("[DBG add_move] parent path:", " -> ".join(chain))
        except Exception:
            pass
        return node

    def find_last_mainline_node(self) -> Optional[Node]:
        if self.game_tree and hasattr(self.game_tree, "find_last_mainline_node"):
            return self.game_tree.find_last_mainline_node()
        # fallback: traverse first top child
        if not self.game_tree or not self.game_tree.root.children:
            return None
        cur = self.game_tree.root.children[0]
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
        if not self.game_tree:
            return stones
        root = self.game_tree.root

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
        if not self.game_tree or not self.game_tree.root.children:
            return []
        start = self.game_tree.root.children[0]
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
