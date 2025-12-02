# game_tree.py
from typing import Optional, List, Dict, Any, Iterable, Tuple
import re
import json

# --- Node и GameTree ---

class Node:
    def __init__(self, move: Optional[str] = None, props: Optional[Dict[str, Any]] = None, parent: Optional['Node'] = None):
        """
        move: ход в GTP/SGF нотации, например "D4" или None для root
        props: словарь SGF свойств для этого узла
        parent: ссылка на родителя
        """
        self.move = move
        self.props: Dict[str, Any] = props or {}
        self.parent: Optional[Node] = parent
        self.children: List[Node] = []
        self.katago: Dict[str, Any] = {}  # место для анализа KataGo: move->payload или node-level data
        # optional snapshot id for fast board restore
        self.snapshot_id: Optional[str] = None

    def add_child(self, child: 'Node') -> None:
        child.parent = self
        self.children.append(child)

    def is_root(self) -> bool:
        return self.parent is None

    def path_from_root(self) -> List['Node']:
        node = self
        path = []
        while node is not None:
            path.append(node)
            node = node.parent
        return list(reversed(path))  # root .. self

    def mainline_child(self) -> Optional['Node']:
        return self.children[0] if self.children else None

    def to_sgf_node(self) -> str:
        # serialize node props and move into SGF node string
        parts = []
        for k, v in self.props.items():
            if isinstance(v, list):
                for item in v:
                    parts.append(f"{k}[{escape_sgf_value(item)}]")
            else:
                parts.append(f"{k}[{escape_sgf_value(v)}]")
        # moves in SGF are properties B[] or W[]; if move stored as "B D4" or "D4"?
        if self.move:
            # assume move stored as "B D4" or "D4" with color in props
            m = self.move
            # if move like "B D4"
            if isinstance(m, str) and ' ' in m:
                color, mv = m.split(' ', 1)
                parts.append(f"{color}[{sgf_coord_from_gtp(mv)}]")
            else:
                # if color in props (e.g., 'B' or 'W' key)
                if 'B' in self.props or 'W' in self.props:
                    # already encoded in props
                    pass
                else:
                    # default: treat as black move
                    parts.append(f"B[{sgf_coord_from_gtp(m)}]")
        return ";" + "".join(parts)

def escape_sgf_value(s: str) -> str:
    return s.replace("\\", "\\\\").replace("]", "\\]")

def sgf_coord_from_gtp(gtp: str) -> str:
    # convert GTP like "D4" to SGF coords "dd" (lowercase a..s, no 'i' handling here)
    # GTP uses letters A..T (often uppercase) and numbers; SGF uses letters a..s for columns and rows from top
    # We'll implement a simple converter assuming standard 19x19 and no 'I' skipping.
    if not gtp:
        return ""
    g = gtp.strip().upper()
    col_letter = g[0]
    row_number = int(g[1:])
    c = ord(col_letter) - ord('A')
    r = 19 - row_number
    return chr(ord('a') + c) + chr(ord('a') + r)

def gtp_from_sgf_coord(s: str) -> str:
    # convert sgf "dd" to GTP "D16" (19x19)
    if not s or len(s) < 2:
        return ""
    c = ord(s[0]) - ord('a')
    r = ord(s[1]) - ord('a')
    row = 19 - r
    col_letter = chr(ord('A') + c)
    return f"{col_letter}{row}"

class GameTree:
    def __init__(self):
        self.root = Node(move=None, props={})
        self.current: Node = self.root

    # --- загрузка SGF (простой парсер) ---
    def load_sgf(self, sgf_text: str) -> None:
        """
        Простой SGF парсер: поддерживает последовательности узлов и ветвления ( ( ... ) ).
        Не поддерживает все проперти SGF, но извлекает B[]/W[] и базовые свойства.
        """
        tokens = tokenize_sgf(sgf_text)
        # recursive descent: parse collection -> game trees
        # we parse first game tree only
        it = iter(tokens)
        try:
            self.root = Node(move=None, props={})
            self.current = self.root
            self._parse_tree(it, self.root)
        except StopIteration:
            pass

    def _parse_tree(self, it, parent_node: Node):
        # expects '(' then sequence of nodes and possibly nested branches
        for tok in it:
            if tok == '(':
                # start subtree: parse sequence into a new branch under parent_node
                # create a new child and parse sequence into it
                child = Node(move=None, props={})
                parent_node.add_child(child)
                self._parse_sequence(it, child)
            elif tok == ')':
                return
            else:
                # ignore stray tokens
                continue

    def _parse_sequence(self, it, start_node: Node):
        node = start_node
        for tok in it:
            if tok == ';':
                # parse node properties until next token that's '(' or ')' or ';'
                props = {}
                # read following property tokens
                for prop_tok in it:
                    if prop_tok in (';', '(', ')'):
                        # push back by using a small trick: we can't push back iterator, so handle control
                        # we handle by setting last token and using recursion; simpler: treat prop_tok as control
                        # but here we break and let outer loop handle control token by returning it via attribute
                        # To keep parser simple, we assume properties were already parsed by tokenizer into dict tokens.
                        # So this branch won't be used.
                        break
                # In our tokenizer we already produce structured node tokens; so this function is not used.
                pass
            elif tok == '(':
                # nested branch: create child from current node
                child = Node(move=None, props={})
                node.add_child(child)
                self._parse_sequence(it, child)
            elif tok == ')':
                return
            else:
                # ignore
                pass

    # --- simplified SGF loader using regex-based node extraction (fallback) ---
    def load_sgf_simple(self, sgf_text: str) -> None:
        """
        Более надёжный, но простая стратегия: находим последовательности узлов ';' и парсим проперти внутри.
        Поддерживает ветвления: '(' и ')' — создаём ветки.
        """
        pos = 0
        length = len(sgf_text)
        stack: List[Node] = []
        current = None
        while pos < length:
            ch = sgf_text[pos]
            if ch == '(':
                # start new tree or branch
                if current is None:
                    current = self.root
                else:
                    # create branch child of current.parent if exists, else child of current
                    parent = current
                    child = Node(move=None, props={})
                    parent.add_child(child)
                    stack.append(current)
                    current = child
                pos += 1
            elif ch == ')':
                # end branch
                if stack:
                    current = stack.pop()
                pos += 1
            elif ch == ';':
                # parse node properties until next ';' or '(' or ')'
                pos += 1
                props, consumed = parse_sgf_node_props(sgf_text[pos:])
                pos += consumed
                # create node with props
                move = None
                # detect B[] or W[] properties
                if 'B' in props:
                    move = f"B {gtp_from_sgf_coord(props['B'][0])}" if isinstance(props['B'], list) else f"B {gtp_from_sgf_coord(props['B'])}"
                elif 'W' in props:
                    move = f"W {gtp_from_sgf_coord(props['W'][0])}" if isinstance(props['W'], list) else f"W {gtp_from_sgf_coord(props['W'])}"
                node = Node(move=move, props=props)
                if current is None:
                    # attach to root
                    self.root.add_child(node)
                    current = node
                else:
                    current.add_child(node)
                    current = node
            else:
                pos += 1
        # set current to root by default
        self.current = self.root

    # --- навигация и утилиты ---
    def get_node_path(self, node: Optional[Node] = None) -> List[str]:
        """Возвращает список ходов (GTP) от root (исключая root) до node."""
        if node is None:
            node = self.current
        path_nodes = node.path_from_root()[1:]  # skip root
        moves = [n.move for n in path_nodes if n.move]
        return moves

    def go_to_node(self, node: Node) -> List[str]:
        """Установить current=node и вернуть список ходов (GTP) для применения в BoardEngine."""
        self.current = node
        return self.get_node_path(node)

    def add_move(self, parent: Node, color: str, gtp_move: str, props: Optional[Dict[str, Any]] = None) -> Node:
        """Добавить ход как дочерний узел к parent. Возвращает созданный узел."""
        mv = f"{color} {gtp_move}"
        node = Node(move=mv, props=props or {})
        parent.add_child(node)
        return node

    def attach_katago(self, node: Node, key: str, payload: Any) -> None:
        """Привязать данные KataGo к узлу (например key='analysis' или key=move_str)."""
        node.katago[key] = payload

    def iterate_mainline(self, start: Optional[Node] = None) -> Iterable[Node]:
        """Итератор по основной линии (первым детям) от start (root по умолчанию)."""
        if start is None:
            start = self.root
        node = start
        while node and node.children:
            node = node.children[0]
            yield node

    def export_moves(self, node: Optional[Node] = None) -> List[str]:
        """Экспортирует последовательность ходов (GTP) до node (или current)."""
        return self.get_node_path(node)

    def to_sgf(self) -> str:
        """Простейшая сериализация дерева в SGF (основная ветка и ветки)."""
        def node_to_sgf(n: Node) -> str:
            s = n.to_sgf_node()
            for child in n.children:
                if child is n.children[0]:
                    s += node_to_sgf(child)
                else:
                    s += "(" + node_to_sgf(child) + ")"
            return s
        body = ""
        for child in self.root.children:
            body += "(" + node_to_sgf(child) + ")"
        # add root properties if any
        root_props = ""
        for k, v in self.root.props.items():
            if isinstance(v, list):
                for item in v:
                    root_props += f"{k}[{escape_sgf_value(item)}]"
            else:
                root_props += f"{k}[{escape_sgf_value(v)}]"
        header = f"(;{root_props}"
        # if body already contains parentheses, just return header+body+')'
        if body:
            return header + body + ")"
        else:
            return header + ")"

# --- Вспомогательные функции для парсинга SGF узла ---

_SGF_PROP_RE = re.compile(r'([A-Za-z]+)\s*(\[(?:\\.|[^\]])*\])+')

def parse_sgf_node_props(s: str) -> Tuple[Dict[str, Any], int]:
    """
    Парсит свойства узла из начала строки s.
    Возвращает (props_dict, consumed_chars).
    Поддерживает несколько свойств подряд, значения в квадратных скобках.
    """
    props: Dict[str, Any] = {}
    pos = 0
    length = len(s)
    while pos < length:
        m = _SGF_PROP_RE.match(s[pos:])
        if not m:
            break
        key = m.group(1)
        vals_raw = m.group(2)
        # extract all [..] groups
        vals = re.findall(r'\[(?:\\.|[^\]])*\]', vals_raw)
        clean_vals = []
        for v in vals:
            inner = v[1:-1]
            inner = inner.replace("\\]", "]").replace("\\\\", "\\")
            clean_vals.append(inner)
        if len(clean_vals) == 1:
            props[key] = clean_vals
        else:
            props[key] = clean_vals
        pos += m.end()
    return props, pos

def tokenize_sgf(s: str) -> List[str]:
    """Очень простой токенайзер: возвращает список символов '(', ')', ';' и прочих строк (не используется в основной реализации)."""
    tokens = []
    i = 0
    while i < len(s):
        c = s[i]
        if c in '();':
            tokens.append(c)
            i += 1
        elif c.isspace():
            i += 1
        else:
            # read until next control char
            j = i
            while j < len(s) and s[j] not in '();':
                j += 1
            tokens.append(s[i:j].strip())
            i = j
    return tokens

# --- Примеры использования и тесты (микро) ---

if __name__ == "__main__":
    # Простой тест загрузки SGF (пример)
    sample = "(;GM[1]FF[4]SZ[19]KM[6.5];B[qd];W[dd];B[pq](;W[dp];B[pp])(;W[dc];B[oc]))"
    gt = GameTree()
    gt.load_sgf_simple(sample)
    print("Root children:", len(gt.root.children))
    # пройти по основной линии
    for n in gt.iterate_mainline():
        print("Mainline move:", n.move, "props:", n.props)
    # экспорт в SGF
    sgf_out = gt.to_sgf()
    print("Exported SGF:", sgf_out)
