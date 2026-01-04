# game_tree.py
# Minimal SGF parser/serializer (version adapted for round-trip consistency)
#
# Goals:
# - Parse SGF into a simple tree of Node objects preserving property order and multiple values.
# - Preserve variations as variations (attach variations to the correct parent node).
# - Serialize back to SGF preserving structure and property ordering produced by the parser.
# - Provide utility methods for round-trip use and simple introspection (get_node_path).
# - Add simple mutation API (add_move, add_variation) expected by UI/controller code.
#
# Note: This is not a full SGF implementation but aims for consistent import/export
# for typical SGF files used in this project.
import os
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Dict, Any, Callable
import re
import sys

DEBUG = True


# -------------------------
# Node model
# -------------------------
class Node:
    """
    Represents a single SGF node (a semicolon entry).
    - props: list of (key, [values]) preserving insertion order and multiple values
    - children: list of Node children (variations / mainline continuation)
    - parent: optional parent Node
    - _is_variation: True if this node was created as a variation (inside parentheses)
    """
    __slots__ = (
        "props",
        "children",
        "parent",
        "_is_variation",
        "is_current",
        "analysis_results",
    )

    def __init__(self, parent: Optional["Node"] = None, is_variation: bool = False):
        # props as list of (key, [values]) to preserve order and duplicates
        self.props: List[Tuple[str, List[str]]] = []
        self.children: List["Node"] = []
        self.parent: Optional["Node"] = parent
        self._is_variation: bool = is_variation
        self.is_current: bool = False
        self.analysis_results: dict = {}

    # convenience: get property values (first occurrence) or None
    def get_prop(self, key: str) -> Optional[List[str]]:
        for k, vals in self.props:
            if k == key:
                return vals
        return None

    def set_prop(self, key: str, values: List[str]):
        # replace existing first occurrence
        for idx, (k, vals) in enumerate(self.props):
            if k == key:
                self.props[idx] = (key, list(values))
                return
        self.props.append((key, list(values)))

    def add_prop_value(self, key: str, value: str):
        for idx, (k, vals) in enumerate(self.props):
            if k == key:
                vals.append(value)
                self.props[idx] = (k, vals)
                return
        self.props.append((key, [value]))

    def props_dict(self) -> Dict[str, List[str]]:
        d: Dict[str, List[str]] = {}
        for k, vals in self.props:
            if k in d:
                d[k].extend(vals)
            else:
                d[k] = list(vals)
        return d

    def has_move(self) -> bool:
        pd = self.props_dict()
        return any(
            color in pd and pd[color] and any(pd[color])
            for color in ["B", "W"]
        )

    def __repr__(self):
        pd = self.props_dict()
        mv = None
        if "B" in pd:
            mv = f"B {pd['B']}"
        elif "W" in pd:
            mv = f"W {pd['W']}"
        return f"<Node move={mv} props={{{', '.join(pd.keys())}}} children={len(self.children)}>"

    def set_is_variation(self, is_variation: bool) -> None:
        self._is_variation = is_variation

    def get_moves(self, board_size: int = 19) -> List[Tuple[str, str, Tuple[int, int], str]]:
        return [
            self.convert_move(move, board_size)
            for move in self._get_moves()
        ]

    def convert_move(self, _get_move_result: Tuple[str, str], board_size: int) -> Tuple[str, str | None, Tuple[int, int] | None, str | None]:
        color, sgf_move_notation = _get_move_result
        if len(sgf_move_notation) != 2:
            return color, None, None, None
        col = ord(sgf_move_notation[0]) - ord('a')
        row = ord(sgf_move_notation[1]) - ord('a')
        col_coord_notation = chr(ord('A') + col + int(col > ord('H') - ord('A')))
        board_coord_notation = f"{col_coord_notation}{board_size - row}"
        return color, sgf_move_notation, (row, col), board_coord_notation

    def _get_moves(self) -> List[Tuple[str, str]]:
        result = []
        for k, vals in self.props:
            if k in ["B", "W", "AB", "AW"] and vals:
                result.extend((k, val) for val in vals)
        return result

def get_name_and_version_from_toml_path(path: str = "../pyproject.toml") -> tuple[Any, Any]:
    name = None
    version = None

    print("[get_name_and_version_from_toml_path] reading ", path, " at", os.getcwd())
    try:
        # try tomllib (py3.11+) then toml
        try:
            import tomllib
            if os.path.exists(path):
                with open(path, "rb") as f:
                    data = tomllib.load(f)
            else:
                data = {}
        except Exception as e:
            print("[get_name_and_version_from_toml_path] failed to load pyproject.toml:", path, e)
            # try toml package
            try:
                import toml
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        data = toml.load(f)
                else:
                    data = {}
            except Exception as e:
                print("[get_name_and_version_from_toml_path] failed to load pyproject.toml:", path, e)
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
        print("[get_name_and_version_from_toml_path] failed to load pyproject.toml:", path, e)
        name = None
        version = None
    return name, version


# -------------------------
# GameTree wrapper
# -------------------------
class GameTree:
    """
    Simple wrapper around parsed SGF tree(s).
    - root: a synthetic root Node whose children are the top-level trees parsed from the SGF.
      The synthetic root itself does not correspond to a semicolon in the SGF (unless the SGF
      had an explicit root node).
    """

    def __init__(self):
        self.root: Node = Node(parent=None)
        self._current = None
        self._subs = []

    # -------------------------
    # Parsing
    # -------------------------
    def load_sgf_simple(self, sgf_text: str):
        """
        Parse SGF text into the GameTree structure.
        This parser:
        - tokenizes parentheses '(', ')', semicolons ';', property identifiers and bracketed values.
        - creates a Node for each ';' token and attaches properties parsed after it.
        - handles nested variations by using a stack of parent contexts; marks nodes created inside
          parentheses as variations so serializer can preserve mainline vs variations.
        """
        text = sgf_text
        i = 0
        n = len(text)

        def read_bracket_value(idx: int) -> Tuple[str, int]:
            # assumes text[idx] == '['
            idx += 1
            buf_chars = []
            while idx < n:
                ch = text[idx]
                if ch == "\\":
                    # escape next char (including newline)
                    idx += 1
                    if idx < n:
                        buf_chars.append(text[idx])
                        idx += 1
                    continue
                if ch == "]":
                    idx += 1
                    break
                buf_chars.append(ch)
                idx += 1
            return ("".join(buf_chars), idx)

        # stack holds tuples (parent_node, in_variation_flag)
        # parent_node: the node under which new nodes should be appended when a ';' is seen
        # in_variation_flag: True if this stack frame corresponds to a '(' context (variation)
        stack: List[Tuple[Node, bool]] = [(self.root, False)]
        current_node: Optional[Node] = None

        prop_re = re.compile(r"[A-Z]+")
        while i < n:
            ch = text[i]
            if ch == "(":
                # start a new variation: push a frame
                parent_for_variation = current_node if current_node is not None else stack[-1][0]
                stack.append((parent_for_variation, True))
                current_node = None
                i += 1
            elif ch == ")":
                # end current variation: pop stack and restore current_node to the parent_for_variation
                if len(stack) > 1:
                    popped_parent, popped_flag = stack.pop()
                    current_node = popped_parent
                else:
                    current_node = None
                i += 1
            elif ch == ";":
                # create a new node
                parent = current_node if current_node is not None else stack[-1][0]
                is_variation = (current_node is None and stack[-1][1] is True)
                node = Node(parent=parent, is_variation=is_variation)
                if parent is not None:
                    parent.children.append(node)
                current_node = node
                i += 1
                # skip whitespace
                while i < n and text[i].isspace():
                    i += 1
                # parse properties for this node
                while i < n:
                    if text[i].isspace():
                        i += 1
                        continue
                    if text[i] in ";()":
                        break
                    m = prop_re.match(text, i)
                    if not m:
                        # unexpected char, skip
                        i += 1
                        continue
                    prop_id = m.group(0)
                    i = m.end()
                    # skip whitespace
                    while i < n and text[i].isspace():
                        i += 1
                    values: List[str] = []
                    # read one or more bracketed values
                    while i < n and text[i] == "[":
                        val, i = read_bracket_value(i)
                        values.append(val)
                        while i < n and text[i].isspace():
                            i += 1
                    # attach property to current_node
                    if current_node is None:
                        parent = stack[-1][0] if stack else self.root
                        current_node = Node(parent=parent, is_variation=stack[-1][1])
                        parent.children.append(current_node)
                    current_node.props.append((prop_id, values))
                # continue outer loop
            else:
                # skip other characters
                i += 1

        # parsing finished
        self._emit("tree_changed", None)
        return

    # -------------------------
    # Utilities
    # -------------------------
    def get_node_path(self, node: Node) -> List[Node]:
        """
        Return list of nodes from synthetic root (excluded) down to the given node.
        If node is not attached to this tree, returns empty list.
        """
        path: List[Node] = []
        cur = node
        # climb up until we reach synthetic root or None
        while cur is not None and cur is not self.root:
            path.append(cur)
            cur = cur.parent
        if cur is not self.root:
            # node not in this tree
            return []
        path.reverse()
        return path

    def find_last_mainline_node(self) -> Optional[Node]:
        """
        Find the last node on the mainline starting from the first top-level child.
        Mainline is defined as following the first non-variation child at each step.
        """
        if not self.root.children:
            return None
        cur = self.root.children[0]
        while True:
            # choose first child that is not a variation
            next_child = None
            for c in cur.children:
                if not getattr(c, "_is_variation", False):
                    next_child = c
                    break
            if next_child is None:
                return cur
            cur = next_child

    # -------------------------
    # Mutation API (for UI/controller)
    # -------------------------
    def add_move(self, parent: Optional[Node], color: str = None, coord: str = None, *,
                 props: Optional[Any] = None, is_variation: Optional[bool] = None) -> Node:
        """
        Add a move node as a child of `parent`.
        Backwards-compatible:
          - old callers: add_move(parent, "B", "pd")
          - new callers: add_move(parent=..., props=[("AB", ["pd"]), ("AB", ["dd"]), ("AW", ["qq"])])
          - or: add_move(parent=..., props={"AB": ["pd","dd"], "AW": ["qq"]})
        If parent is None, append to the last mainline node (or create top-level if empty).
        Returns the created Node.
        """
        # determine parent
        if parent is None:
            parent = self.find_last_mainline_node()
            if parent is None:
                parent = self.root

        # determine is_variation flag
        if is_variation is None:
            is_variation = False

        node = Node(parent=parent, is_variation=is_variation)

        # attach move from (color, coord) if provided
        if color is not None and coord is not None:
            node.props.append((color, [coord]))

        # attach props if provided
        if props:
            # Preferred form: list of (key, values) pairs to preserve duplicates/order
            if isinstance(props, (list, tuple)):
                for item in props:
                    # item can be ("AB", ["pd","dd"]) or ("AB", "pd")
                    if not isinstance(item, (list, tuple)) or len(item) < 1:
                        continue
                    k = item[0]
                    v = item[1] if len(item) > 1 else []
                    if isinstance(v, (list, tuple)):
                        vals = [str(x) for x in v]
                    else:
                        vals = [str(v)]
                    # append each occurrence as a single property entry (preserves duplicates)
                    node.props.append((k, vals))
            elif isinstance(props, dict):
                # dict: values may be lists; order is dict order (Python 3.7+ preserves insertion order)
                for k, v in props.items():
                    if isinstance(v, (list, tuple)):
                        vals = [str(x) for x in v]
                    else:
                        vals = [str(v)]
                    node.props.append((k, vals))
            else:
                # unsupported type — ignore
                pass

        parent.children.append(node)
        self._emit("tree_changed", None)
        return node

    def add_variation(self, parent: Node, color: str, coord: str) -> Node:
        """
        Add a variation node as an additional child of `parent` (i.e., not mainline).
        Returns the created Node.
        """
        if parent is None:
            raise ValueError("parent must be a Node")
        if color not in ("B", "W"):
            raise ValueError("color must be 'B' or 'W'")
        node = Node(parent=parent, is_variation=True)
        node.props.append((color, [coord]))
        parent.children.append(node)
        return node

    # -------------------------
    # Serialization
    # -------------------------
    def _escape_value(self, v: str) -> str:
        v = v.replace("\\", "\\\\")
        v = v.replace("]", "\\]")
        return v

    def _serialize_node_props(self, node: Node) -> str:
        parts: List[str] = []
        for key, vals in node.props:
            if not vals:
                parts.append(f"{key}")
                continue
            vs = "".join(f"[{self._escape_value(v)}]" for v in vals)
            parts.append(f"{key}{vs}")
        return "".join(parts)

    def _serialize_subtree(self, node: Node) -> str:
        """
        Serialize a subtree starting at node into SGF.
        Serializes the mainline (first non-variation child chain) inline and emits additional children as variations.
        """
        # Build mainline: follow the first child that is NOT marked as variation.
        seq_parts: List[str] = []
        mainline_nodes: List[Node] = []
        cur = node
        while cur is not None:
            props_str = self._serialize_node_props(cur)
            seq_parts.append(";" + props_str)
            mainline_nodes.append(cur)
            # find mainline child: first child with _is_variation == False
            main_child = None
            for c in cur.children:
                if not getattr(c, "_is_variation", False):
                    main_child = c
                    break
            cur = main_child

        mainline = "".join(seq_parts)

        # collect variations attached to any node in the mainline
        var_parts: List[str] = []
        for mn in mainline_nodes:
            for c in mn.children:
                # treat children that are not part of the chosen mainline as variations
                if c not in mainline_nodes:
                    var_parts.append("(" + self._serialize_subtree(c) + ")")
        return mainline + "".join(var_parts)

    def to_sgf(self) -> str:
        """
        Serialize the GameTree to SGF text.
        - If the synthetic root has a single top-level child, serialize that child wrapped in parentheses.
        - If multiple top-level children exist, serialize each as a parenthesized tree concatenated.
        """
        print("[DBG to_sgf] called for instance id", id(self), "root id", id(self.root))
        top_children = self.root.children
        if not top_children:
            return ""
        if len(top_children) == 1:
            return "(" + self._serialize_subtree(top_children[0]) + ")"
        parts: List[str] = []
        for ch in top_children:
            parts.append("(" + self._serialize_subtree(ch) + ")")
        return "".join(parts)

    #
    # Missing game props
    #
    def add_missing_game_props(self):
        # --- normalization: ensure at least one game node under synthetic root ---
        if self.root is None:
            return

        # If root already has children, we leave structure as-is
        if getattr(self.root, "children", None):
            if DEBUG:
                print("[TreeAdapter] load: root already has children:", len(self.root.children))
            return

        # read defaults: prefer pyproject.toml project.name and project.version
        defaults = self._defaults_from_pyproject()

        # create a Node under synthetic root with canonical game properties
        try:
            node = Node(parent=self.root, is_variation=False)
        except TypeError:
            # older Node signature may not accept is_variation
            node = Node(parent=self.root)

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
        name, version = get_name_and_version_from_toml_path(path)

        # build defaults
        if name and version:
            ap_val = f"{name}:{version}"
        elif name:
            ap_val = f"{name}:0.0"
        else:
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

    def add_missing_game_props_1(self, path: str = "../pyproject.toml") -> Node:
        root = self.root
        # build defaults (minimal): GM from pyproject (name+version) if available, else "1"
        name, version = get_name_and_version_from_toml_path(path)

        if name and version:
            ap = f"{name}:{version}"
        elif name:
            ap = f"{name}:0.0"
        else:
            ap = "ggo:0.1"

        # create the game node and attach to root
        try:
            game_node = Node(parent=root, is_variation=False)
        except TypeError:
            game_node = Node(parent=root)
        # canonical header props
        from datetime import datetime, timezone
        dt = datetime.now(timezone.utc).date().isoformat()
        header_order = [("GM", ["1"]), ("FF", ["4"]), ("CA", ["UTF-8"]), ("AP", [ap]), ("KM", ["6.5"]),
                        ("SZ", ["19"]), ("DT", [dt])]
        for k, vals in header_order:
            game_node.props.append((k, list(vals)))
        root.children.append(game_node)
        game_node.parent = root
        parent = game_node
        return parent

    def need_game_node(self) -> bool:
        root: Node = self.root
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
        return need_game_node

    #
    # Normalization, accend, decend
    #
    def walk(self, fn: Callable[[Node], None], node: Node):
        fn(node)
        while len(node.children or []) == 1:
            node = node.children[0]
            fn(node)
        children = node.children or []
        for child in children:
            self.walk(fn, child)

    def walk_root(self, fn: Callable[[Node], None]):
        self.walk(fn, self.root)

    def normalize_is_variation(self):
        def normalize_is_variation_fn(node: Node):
            children = node.children or []
            is_variation = len(children) >= 2
            for child in children:
                # print("[GameTree] normalize_is_variation_fn id", id(children[idx]), "is_variation", is_variation)
                child.set_is_variation(is_variation)

        self.walk_root(normalize_is_variation_fn)

    def ascend(self, fn: Callable[[Node], Optional[bool]], node: Node):
        while node is not None and node.parent:
            _continue = fn(node)
            if _continue is False:
                break
            node = node.parent

    def ascend_to_move(self, node: Node, mv: str) -> Optional[Node]:
        found_node: Optional[Node] = None

        def not_has_move(node: Node):
            nonlocal found_node
            props_dict = node.props_dict()
            for k in ['B', 'W', 'AB', 'AW']:
                if k in props_dict and props_dict[k] and mv in props_dict[k]:
                    found_node = node
                    return False
            return True

        self.ascend(not_has_move, node)
        return found_node

    def descend(self, fn: Callable[[Node], Optional[Node]], node: Node):
        while True:
            child = fn(node)
            if child not in node.children:
                return
            node = child

    def get_current_child(self, node: Node) -> Node | None:
        current_children = [
            child
            for child in node.children
            if child.is_current
        ]
        assert len(current_children) <= 1, current_children
        if not current_children:
            return None
        else:
            return current_children[0]

    def _sync_is_current(self, node: Node):
        if node.is_current:
            return
        node_to_reset_current: Optional[Node] = None

        def ascend_fn(node: Node) -> bool:
            nonlocal node_to_reset_current
            if node.parent is None:
                return False
            if node.parent.parent is None:
                node.is_current = True
                return False
            current_child = self.get_current_child(node.parent)
            node.is_current = True
            if current_child is None:
                return True
            if not (current_child is node):
                node_to_reset_current = current_child
            return False

        self.ascend(ascend_fn, node)

        def descend_reset_current_fn(node: Node):
            node.is_current = False
            return self.get_current_child(node)

        def descend_set_mainline_current_fn(node: Node) -> Node | None:
            node.is_current = True
            current_child = self.get_current_child(node)
            if current_child is not None:
                return current_child
            if node.children:
                return node.children[0]
            return None

        if node_to_reset_current:
            self.descend(descend_reset_current_fn, node_to_reset_current)
        self.descend(descend_set_mainline_current_fn, node)

    def clear(self):
        self.root = Node(parent=None)

    #
    # Setting current, subscribe, unsubscribe
    #
    @property
    def current(self) -> Node | None:
        return self._current

    @current.setter
    def current(self, node: Node) -> None:
        if node is self._current:
            return
        old = self._current
        self._current = node
        self._sync_is_current(node)
        self._emit("current_changed", node)

    def subscribe(self, cb):
        """cb(event_name: str, payload)"""
        if cb not in self._subs:
            self._subs.append(cb)

    def unsubscribe(self, cb):
        try:
            self._subs.remove(cb)
        except ValueError:
            pass

    def _emit(self, event, payload):
        for cb in list(self._subs):
            try:
                cb(event, payload)
            except Exception as e:
                print("[GameTree]", event, "_emit exception for", "%r(%r): %s" % (cb, payload, e))

    #
    # Getting first, last, prev, next
    #
    def get_first(self):
        first = None

        def ascend_to_root_child_fn(node: Node):
            nonlocal first
            first = node
            if node.parent is None or node.parent.parent is None:
                return False
            return True

        if self._current is not None:
            self.ascend(ascend_to_root_child_fn, self._current)
            return first
        else:
            return self.root

    def get_last(self):
        last = None

        def descend_to_current_leaf_fn(node: Node):
            nonlocal last
            if not node.is_current:
                return None
            current_child = self.get_current_child(node)
            if current_child:
                last = current_child
            return current_child

        if self._current is not None:
            self.descend(descend_to_current_leaf_fn, self._current)
            return last
        else:
            return self.root

    def get_current_path(self) -> List[Node]:
        path = []
        if self._current is None:
            return path

        def ascend_to_root_child_fn(node: Node) -> bool:
            path.append(node)
            return True

        self.ascend(ascend_to_root_child_fn, self._current)
        path.reverse()

        def descend_to_current_leaf_fn(node: Node):
            if not node.is_current:
                return None
            current_child = self.get_current_child(node)
            if current_child:
                path.append(current_child)
            return current_child

        self.descend(descend_to_current_leaf_fn, self._current)
        return path

    #
    # Moving last, first, next, prev
    #
    def move_first(self):
        first = self.get_first()
        if first and first is not self._current:
            self._current = first
            self._emit("current_changed", first)

    def move_last(self):
        last = self.get_last()
        if last and last is not self._current:
            self._current = last
            self._emit("current_changed", last)

    def move_next(self):
        if not self._current or not self._current.is_current:
            _next = self.root
        else:
            _next = self.get_current_child(self._current)
        if _next and _next is not self._current:
            self._current = _next
            self._emit("current_changed", _next)

    def move_prev(self):
        if not self._current or not self._current.is_current:
            prev = self.root
        else:
            if self._current.parent:
                prev = self._current.parent
                if prev is self.root:
                    prev.is_current = True
            else:
                prev = self._current
        if prev and prev is not self._current:
            self._current = prev
            self._emit("current_changed", prev)


# -------------------------
# CLI test
# -------------------------
if __name__ == "__main__":
    sample = None
    if len(sys.argv) > 1:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            sample = f.read()
    else:
        sample = "(;GM[1]FF[4]CA[UTF-8]AP[Sabaki:0.52.2]KM[6.5]SZ[19]DT[2025-12-09];B[pd](;W[dp];B[pp];W[dd])(;W[pp];B[dp];W[dd]))"

    print("Importing sample:", sample)
    gt = GameTree()
    gt.load_sgf_simple(sample)
    root = gt.root
    print("Root children:", len(root.children))


    def traverse_mainline(node: Optional[Node], depth=0):
        if node is None:
            return
        pd = node.props_dict()
        mv = None
        if "B" in pd:
            mv = f"B {pd['B']}"
        elif "W" in pd:
            mv = f"W {pd['W']}"
        print("Mainline move:", mv, "props:", pd)
        # follow mainline child (first non-variation child)
        main_child = None
        for c in node.children:
            if not getattr(c, "_is_variation", False):
                main_child = c
                break
        if main_child:
            traverse_mainline(main_child, depth + 1)
        # print variations
        for v in node.children:
            if v is not main_child:
                print("Variation at node:", node, "->", v)
                traverse_mainline(v, depth + 1)


    for ch in root.children:
        traverse_mainline(ch)

    out = gt.to_sgf()
    print("Exported SGF:", out)
    print("Literally match:", str(out == sample))

    # quick mutation test: add a move on mainline
    last = gt.find_last_mainline_node()
    print("Last mainline node before add:", last)
    new = gt.add_move(last, "W", "aa")
    print("Added move:", new)
    print("SGF after add:", gt.to_sgf())
