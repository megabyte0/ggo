# ui/tree_canvas.py
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango, PangoCairo, GLib
import cairo
import math
from typing import Optional, Tuple, Dict, Any, List

class _DrawNode:
    def __init__(self, node_obj, x: float, y: float, radius: float):
        self.node = node_obj
        self.x = x
        self.y = y
        self.radius = radius

class TreeCanvas(Gtk.DrawingArea):
    def __init__(self, node_radius: int = 6, level_vgap: int = 80, sibling_hgap: int = 24):
        super().__init__()
        self.set_draw_func(self._on_draw, None)
        self.set_hexpand(True)
        self.set_vexpand(True)

        # layout params
        self.node_radius = node_radius
        self.level_vgap = level_vgap
        self.sibling_hgap = sibling_hgap

        # tree data (GameTree root node)
        self.root = None

        # computed layout: list of _DrawNode and edges (parent_idx, child_idx)
        self._draw_nodes: List[_DrawNode] = []
        self._edges: List[Tuple[int,int]] = []

        # selection: selected_node highlighted by outline (not by fill)
        self.selected_node = None

        # hit test map: index -> node
        self._hit_map: Dict[int, Any] = {}

        # mouse events
        click = Gtk.GestureClick.new()
        click.connect("pressed", self._on_click)
        self.add_controller(click)

    # Public API
    def set_tree_root(self, root_node):
        """Передать корень GameTree (Node)."""
        self.root = root_node
        self._recompute_layout()
        # если доска пустая (корень без детей), выделяем корень
        if self.root is not None and not getattr(self.root, 'children', None):
            self.selected_node = self.root
        self.queue_draw()

    def clear(self):
        self.root = None
        self._draw_nodes = []
        self._edges = []
        self.selected_node = None
        self._hit_map = {}
        self.queue_draw()

    def select_node(self, node_obj):
        self.selected_node = node_obj
        self.queue_draw()

    def get_selected(self):
        return self.selected_node

    # Layout algorithm: include root as a real node at top
    def _recompute_layout(self):
        self._draw_nodes = []
        self._edges = []
        self._hit_map = {}
        if self.root is None:
            return

        def build_levels(node, depth, levels):
            if len(levels) <= depth:
                levels.append([])
            levels[depth].append(node)
            for child in getattr(node, 'children', []):
                build_levels(child, depth+1, levels)

        levels: List[List[Any]] = []
        # start from root so root becomes level 0
        build_levels(self.root, 0, levels)

        # compute widths per level
        level_widths = []
        for lvl in levels:
            w = len(lvl) * (2*self.node_radius) + max(0, (len(lvl)-1))*self.sibling_hgap
            level_widths.append(w)

        canvas_w = max(level_widths) if level_widths else 0
        y0 = self.node_radius + 8
        node_positions = {}
        for depth, lvl in enumerate(levels):
            w = level_widths[depth]
            x_start = self.node_radius + 8
            if canvas_w > w:
                x_start += (canvas_w - w) / 2.0
            x = x_start
            for i, node in enumerate(lvl):
                cx = x + self.node_radius
                cy = y0 + depth * self.level_vgap
                node_positions[node] = (cx, cy)
                x += 2*self.node_radius + self.sibling_hgap

        # create draw nodes in a deterministic traversal (preorder)
        index_map = {}
        self._draw_nodes = []
        idx = 0
        def add_nodes_recursive(node):
            nonlocal idx
            if node not in node_positions:
                for ch in getattr(node, 'children', []):
                    add_nodes_recursive(ch)
                return
            x,y = node_positions[node]
            dn = _DrawNode(node, x, y, self.node_radius)
            index_map[node] = idx
            self._draw_nodes.append(dn)
            idx += 1
            for ch in getattr(node, 'children', []):
                add_nodes_recursive(ch)
        add_nodes_recursive(self.root)

        # build edges using index_map
        self._edges = []
        def add_edges(node):
            if node not in index_map:
                for ch in getattr(node, 'children', []):
                    add_edges(ch)
                return
            pidx = index_map[node]
            for ch in getattr(node, 'children', []):
                if ch in index_map:
                    cidx = index_map[ch]
                    self._edges.append((pidx, cidx))
                add_edges(ch)
        add_edges(self.root)

        # store hit map
        self._hit_map = {i: dn.node for i, dn in enumerate(self._draw_nodes)}

    # helper: draw root diamond at given _DrawNode
    def _draw_diamond(self, cr: cairo.Context, cx: float, cy: float, size: float,
                      fill_color=(1.0, 1.0, 1.0), stroke_color=(0.2,0.2,0.2), stroke_width=1.0):
        cr.save()
        cr.translate(cx, cy)
        cr.rotate(math.pi / 4.0)
        side = size * math.sqrt(2)  # сторона квадрата, чтобы диагональ = 2*size
        half = side / 2.0
        cr.new_path()
        cr.rectangle(-half, -half, side, side)
        cr.set_source_rgb(*fill_color)
        cr.fill_preserve()
        cr.set_line_width(stroke_width)
        cr.set_source_rgb(*stroke_color)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.stroke()
        cr.restore()

    # Drawing
    def _on_draw(self, area, cr: cairo.Context, width: int, height: int, user_data):
        # background
        cr.set_source_rgb(1,1,1)
        cr.paint()

        if not self._draw_nodes:
            cr.set_source_rgb(0.6,0.6,0.6)
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            cr.set_font_size(12)
            cr.move_to(10, 20)
            cr.show_text("Tree is empty")
            return

        # draw edges (simple grey lines)
        cr.set_line_width(1.0)
        cr.set_source_rgb(0.75, 0.75, 0.75)
        for pidx, cidx in self._edges:
            # guard indices
            if not (0 <= pidx < len(self._draw_nodes) and 0 <= cidx < len(self._draw_nodes)):
                continue
            p = self._draw_nodes[pidx]
            c = self._draw_nodes[cidx]
            # if parent is root and drawn as diamond, approximate bottom point by radius
            cr.move_to(p.x, p.y + p.radius)
            cr.line_to(c.x, c.y - c.radius)
            cr.stroke()

        # draw nodes: filled small circles, except root drawn as diamond
        cr.new_path()  # clear any leftover path to avoid artifacts
        for dn in self._draw_nodes:
            is_root = (dn.node is self.root)
            selected = (dn.node is self.selected_node)

            if is_root:
                # diamond fill color and stroke
                fill_col = (0.98, 0.98, 0.98)
                stroke_col = (0.2, 0.2, 0.2)
                # if selected, change fill slightly and draw highlight
                if selected:
                    fill_col = (0.9, 0.95, 1.0)  # subtle highlight tint
                self._draw_diamond(cr, dn.x, dn.y, dn.radius, fill_color=fill_col, stroke_color=stroke_col, stroke_width=1.0)

                # outline highlight if selected
                if selected:
                    cr.set_line_width(1.5)
                    cr.set_source_rgb(0.05, 0.5, 0.95)
                    # draw a slightly larger diamond outline
                    self._draw_diamond(cr, dn.x, dn.y, dn.radius + 2.0, fill_color=fill_col, stroke_color=(0.05,0.5,0.95), stroke_width=1.5)
            else:
                # normal circular node
                cr.set_source_rgb(0.15, 0.15, 0.15)  # dark filled nodes
                cr.arc(dn.x, dn.y, dn.radius, 0, 2*math.pi)
                cr.fill()

                # outline: if selected node -> draw thicker outline (highlight)
                if selected:
                    cr.set_line_width(1.5)
                    cr.set_source_rgb(0.05, 0.5, 0.95)  # highlight outline color (blue)
                    cr.arc(dn.x, dn.y, dn.radius + 2.0, 0, 2*math.pi)
                    cr.stroke()
                else:
                    # thin neutral border
                    cr.set_line_width(1.0)
                    cr.set_source_rgb(0.2, 0.2, 0.2)
                    cr.arc(dn.x, dn.y, dn.radius, 0, 2*math.pi)
                    cr.stroke()

    # Hit testing
    def _hit_test(self, x: float, y: float) -> Optional[Any]:
        # For diamond root, distance test still uses radius circle approximation.
        for dn in self._draw_nodes:
            dx = x - dn.x
            dy = y - dn.y
            if dx*dx + dy*dy <= (dn.radius + 2.0)**2:
                return dn.node
        return None

    # Click handler
    def _on_click(self, gesture, n_press, x, y):
        node = self._hit_test(x, y)
        if node:
            self.selected_node = node
            cb = getattr(self, "_on_node_selected_cb", None)
            if cb:
                cb(node)
            self.queue_draw()

    def set_on_node_selected(self, callback):
        self._on_node_selected_cb = callback
