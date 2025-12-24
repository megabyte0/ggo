import cairo
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib
from typing import List, Optional, Callable, Tuple
from ggo.game_tree import Node, GameTree


class DraggableXNodeChart(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.values: List[Optional[float]] = []
        self._nodes: List[Node] = []
        self._dragging: bool = False
        self._0_index_none_value = 0.0
        self._min_y, self._max_y = 0.0, 1.0

        # контроллер кликов (нажатие/отпускание)
        self._gesture = Gtk.GestureClick.new()
        self._gesture.connect("pressed", self._on_pressed)
        self._gesture.connect("released", self._on_released)
        self.add_controller(self._gesture)
        # контроллер движения мыши (для drag)
        self._motion = Gtk.EventControllerMotion()
        self._motion.connect("motion", self._on_motion)
        self.add_controller(self._motion)

        self._get_game_tree: Optional[Callable[[], GameTree]] = None
        self.current_point_index: Optional[int] = None

        self.height: int = 0
        self.margin_left: int = 0
        self.margin_right: int = 0
        self.margin_top: int = 0
        self.margin_bottom: int = 0
        self._inner_h: int = 0

        self.bg_color: Tuple[float, float, float] = (1.0, 1.0, 1.0)
        self.line_color: Tuple[float, float, float] = (0.15, 0.15, 0.15)
        self.dash_color: Tuple[float, float, float] = (0.15, 0.15, 0.15)
        self.vertical_color: Tuple[float, float, float] = (0.75, 0.75, 0.75)

    def set_game_tree_getter(self, get_game_tree: Callable[[], GameTree]):
        self._get_game_tree = get_game_tree

    def _set_current_by_index(self, idx):
        if not self._nodes:
            return
        node = self._nodes[idx]
        # безопасно для GUI: выполнить в idle
        GLib.idle_add(lambda: setattr(self._get_game_tree(), "current", node))
        self.current_point_index = idx
        self.queue_draw()

    def _set_current_by_x(self, x):
        # ScoreChart: idx = int(x - self.margin_left)
        # WinrateChart: idx = int(x)
        try:
            margin = getattr(self, "margin_left", 0)
        except Exception:
            margin = 0
        idx = int(x - margin)
        idx = max(0, min(len(self._nodes) - 1, idx))
        self._set_current_by_index(idx)

    def _on_pressed(self, gesture, n_press, x, y):
        self._dragging = True
        self._set_current_by_x(x)

    def _on_released(self, gesture, n_press, x, y):
        self._dragging = False
        self._set_current_by_x(x)

    def _on_motion(self, controller, x, y):
        if self._dragging:
            self._set_current_by_x(x)

    def update_from_nodes(self, nodes: List[Node], current: Node):
        vals: List[Optional[float]] = []
        current_point_index = None
        for i, node in enumerate(nodes):
            v = self._get_value_from_node(node)
            # index 0 None -> treat as 0.0 and valid
            if i == 0 and v is None:
                vals.append(self._0_index_none_value)
            else:
                vals.append(v)
            if node is current:
                current_point_index = i
        self.values = vals
        self.current_point_index = current_point_index
        self._nodes = nodes
        w = max(1, len(self.values))
        # width includes left margin for labels
        self.set_size_request(w + self.margin_left + self.margin_right, self.height)
        GLib.idle_add(self.queue_draw)

    def _get_value_from_node(self, node: Node) -> float | None:
        raise NotImplementedError

    def _draw_vertical_current_line(self, cr: cairo.Context, total_h: int):
        if self.current_point_index is not None:
            cr.set_source_rgb(*self.vertical_color)
            cr.set_line_width(1.0)
            x = self.margin_left + self.current_point_index + 0.5
            cr.move_to(x, self.margin_top)
            cr.line_to(x, total_h - self.margin_bottom)
            cr.stroke()

    def y_of(self, v: float) -> float:
        # helper to map value->y
        return self.margin_top + (1.0 - (v - self._min_y) / (self._max_y - self._min_y)) * self._inner_h

    def _draw_horizontal_axis(self, cr: cairo.Context, total_w: int) -> None:
        pass

    def on_draw(self, area, cr: cairo.Context, width: int, height: int, user_data) -> None:
        total_w = self.get_allocated_width()
        total_h = self.get_allocated_height()
        self._inner_h = max(1, total_h - self.margin_top - self.margin_bottom)

        cr.set_source_rgb(*self.bg_color)
        cr.rectangle(0, 0, total_w, total_h)
        cr.fill()

        if not self.values:
            return

        self._set_min_and_max_value()
        self._draw_vertical_ticks_and_labels(cr)
        self._draw_horizontal_axis(cr, total_w)
        self._draw_graph(cr)
        self._draw_vertical_current_line(cr, total_h)

        # # draw small markers for valid points
        # cr.set_source_rgb(*self.line_color)
        # for i, v in enumerate(self.values):
        #     if v is not None:
        #         x = inner_x + i + 0.5
        #         y = self.y_of(v)
        #         cr.arc(x, y, 1.0, 0, 2 * 3.14159)
        #         cr.fill()

        return

    def _draw_vertical_ticks_and_labels(self, cr: cairo.Context) -> None:
        pass

    def _draw_graph(self, cr: cairo.Context):
        # draw solid polyline segments for contiguous valid points
        cr.set_line_width(1.0)
        # draw solid polyline segments
        last_valid_idx = None
        for i, val in enumerate(self.values):
            if val is not None:
                if last_valid_idx is None:
                    last_valid_idx = i
                else:
                    # draw line from last_valid_idx to i (solid)
                    x1 = self.margin_left + last_valid_idx + 0.5
                    y1 = self.y_of(self.values[last_valid_idx])
                    x2 = self.margin_left + i + 0.5
                    y2 = self.y_of(val)
                    cr.set_source_rgb(*self.line_color)
                    cr.move_to(x1, y1)
                    cr.line_to(x2, y2)
                    cr.stroke()
                    last_valid_idx = i
            # if val is None: skip, will be handled as dashed between valid neighbors

        # draw dashed connectors across None gaps
        # find pairs (left_idx, right_idx) where there is a gap between them
        i = 0
        n = len(self.values)
        while i < n:
            if self.values[i] is None:
                # find left valid
                left = i - 1
                while left >= 0 and self.values[left] is None:
                    left -= 1
                # find right valid
                right = i
                while right < n and self.values[right] is None:
                    right += 1
                if left >= 0 and right < n:
                    # draw dashed line from left to right using values at left and right
                    x1 = self.margin_left + left + 0.5
                    y1 = self.y_of(self.values[left])
                    x2 = self.margin_left + right + 0.5
                    y2 = self.y_of(self.values[right])
                    cr.set_source_rgb(*self.dash_color)
                    cr.set_line_width(1.0)
                    cr.set_dash([6.0, 4.0], 0)
                    cr.move_to(x1, y1)
                    cr.line_to(x2, y2)
                    cr.stroke()
                    cr.set_dash([], 0)
                elif left < 0 and right < n:
                    # gap at beginning: if index 0 was None, we treated it as 0.5 already,
                    # so this branch rarely happens. If it does, draw dashed from x=0
                    x2 = self.margin_left + right + 0.5
                    y2 = self.y_of(self.values[right])
                    cr.set_source_rgb(*self.dash_color)
                    cr.set_line_width(1.0)
                    cr.set_dash([6.0, 4.0], 0)
                    cr.move_to(self.margin_left + 0.5, self.y_of(self._0_index_none_value))
                    cr.line_to(x2, y2)
                    cr.stroke()
                    cr.set_dash([], 0)
                # skip past gap
                i = right
            else:
                i += 1

    def _set_min_and_max_value(self) -> None:
        raise NotImplementedError
