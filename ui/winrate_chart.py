# ui/winrate_chart.py
import gi

from ggo.game_tree import Node

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, GObject
import cairo
from typing import List, Optional

class WinrateChart(Gtk.DrawingArea):
    """
    WinrateChart: points = list[Optional[float]] where values in [0,1] or None.
    Index 0 with None is treated as 0.5 (valid).
    1 move == 1 pixel horizontally: widget requests width = len(points).
    """
    __gtype_name__ = "WinrateChart"

    def __init__(self, height: int = 80):
        super().__init__()
        self.set_size_request(100, height)
        self.set_draw_func(self.on_draw, None)

        self.values: List[Optional[float]] = []
        self.current_point_index: Optional[int] = None

        self.height = height
        self.margin_top = 4
        self.margin_bottom = 4
        self.margin_left = 0
        self.margin_right = 0
        self._inner_h: int = 0

        self.bg_color = (1.0, 1.0, 1.0)
        self.line_color = (0.15, 0.15, 0.15)
        self.dash_color = (0.15, 0.15, 0.15)
        self.vertical_color = (0.75, 0.75, 0.75)

        self._0_index_none_value = 0.5
        self._min_y, self._max_y = 0.0, 1.0

    def update_from_nodes(self, nodes: List[Node], current: Node):
        pts: List[Optional[float]] = []
        current_point_index = None
        for i, node in enumerate(nodes):
            v = None
            try:
                raw = (node.get_prop("SBKV") or [None])[0]
                if raw is not None:
                    v = float(raw) / 100.0
            except Exception:
                v = None
            # special rule: index 0 None -> treat as 0.5 and mark as valid
            if i == 0 and v is None:
                pts.append(0.5)
            else:
                pts.append(v)
            if node is current:
                current_point_index = i
        self.values = pts
        self.current_point_index = current_point_index
        # request width = number of moves (1px per move)
        w = max(1, len(self.values))
        self.set_size_request(w, self.height)
        GLib.idle_add(self.queue_draw)

    # vertical mapping: value 0 -> bottom, 1 -> top (no autoscale)
    def y_of(self, v: float) -> float:
        # inner_h = h - (self.margin_top + self.margin_bottom)
        return self.margin_top + (1.0 - v) * self._inner_h

    def on_draw(self, area, cr: cairo.Context, width: int, height: int, user_data):
        total_w = self.get_allocated_width()
        total_h = self.get_allocated_height()
        self._inner_h = max(1, total_h - self.margin_top - self.margin_bottom)
        cr.set_source_rgb(*self.bg_color)
        cr.rectangle(0, 0, total_w, total_h)
        cr.fill()

        if not self.values:
            return

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

        if self.current_point_index is not None:
            cr.set_source_rgb(*self.vertical_color)
            cr.set_line_width(1.0)
            cr.move_to(self.current_point_index + 0.5, self.y_of(0.0))
            cr.line_to(self.current_point_index + 0.5, self.y_of(1.0))
            cr.stroke()

        # # draw small circles for valid points (optional)
        # cr.set_source_rgb(*self.line_color)
        # for i, v in enumerate(self.points):
        #     if v is not None:
        #         cr.arc(i + 0.5, self.y_of(v), 1.0, 0, 2 * 3.14159)
        #         cr.fill()

        return
