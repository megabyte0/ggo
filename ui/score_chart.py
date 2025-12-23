# ui/score_chart.py
import gi

from ggo.game_tree import Node

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, PangoCairo
import cairo
from typing import List, Optional
import math

class ScoreChart(Gtk.DrawingArea):
    """
    ScoreChart: points = list[Optional[float]] where None means not analyzed.
    Autoscale vertically (min/max from data, with small padding).
    Draw vertical tick marks and labels according to rules:
      - max_abs = max(mx, -mn)
      - if max_abs <= 5: ticks every 1, no numeric labels
      - elif max_abs <= 10: ticks every 1, numeric labels only for ±5 (if inside range)
      - else: ticks every 10; numeric labels step = 10 if max_abs <= 50 else 50
    1 move == 1 pixel horizontally.
    """
    __gtype_name__ = "ScoreChart"

    def __init__(self, height: int = 120):
        super().__init__()
        self.set_size_request(200, height)
        self.set_draw_func(self.on_draw, None)
        self.values: List[Optional[float]] = []
        self.current_point_index: Optional[int] = None
        self.height = height
        self.margin_left = 44
        self.margin_right = 6
        self.margin_top = 8
        self.margin_bottom = 20
        self.bg_color = (1.0, 1.0, 1.0)
        self.line_color = (0.15, 0.15, 0.15)
        self.dash_color = (0.15, 0.15, 0.15)
        self.axis_color = (0.45, 0.45, 0.45)
        self.vertical_color = (0.75, 0.75, 0.75)
        self.font_color = (0.0, 0.0, 0.0)

    def update_from_nodes(self, nodes: List[Node], current: Node):
        vals: List[Optional[float]] = []
        current_point_index = None
        for i, node in enumerate(nodes):
            v = None
            try:
                raw = (node.get_prop("GGBL") or [None])[0]
                if raw is not None:
                    v = float(raw)
            except Exception:
                v = None
            # index 0 None -> treat as 0.0 and valid
            if i == 0 and v is None:
                vals.append(0.0)
            else:
                vals.append(v)
            if node is current:
                current_point_index = i
        self.values = vals
        self.current_point_index = current_point_index
        w = max(1, len(self.values))
        # width includes left margin for labels
        self.set_size_request(w + self.margin_left + self.margin_right, self.height)
        GLib.idle_add(self.queue_draw)

    def _compute_ticks_and_labels(self, mn: float, mx: float):
        """
        Return (tick_step, label_values_list, show_numeric_labels_bool)
        tick_step: spacing between small tick marks (in score units)
        label_values_list: list of numeric values where to draw numeric labels
        show_numeric_labels_bool: whether to draw numeric labels at all (for small ranges we may skip)
        """
        max_abs = max(abs(mx), abs(mn))
        # choose tick_step and label step according to rules
        if max_abs <= 5:
            tick_step = 1
            # no numeric labels
            return tick_step, [], False
        if max_abs <= 10:
            tick_step = 1
            # numeric labels only for ±5 if they fall inside [mn, mx]
            labels = []
            for v in (5, -5):
                if mn <= v <= mx:
                    labels.append(v)
            return tick_step, sorted(labels, reverse=True), True if labels else False
        # max_abs > 10
        tick_step = 10
        label_step = 10 if max_abs <= 50 else 50
        # build label list: multiples of label_step within [mn, mx]
        # choose integer multiples
        start = math.floor(mn / label_step) * label_step
        end = math.ceil(mx / label_step) * label_step
        labels = []
        v = start
        while v <= end:
            if mn <= v <= mx:
                labels.append(v)
            v += label_step
        # sort descending for drawing top->bottom
        labels = sorted(labels, reverse=True)
        return tick_step, labels, True

    def on_draw(self, area, cr: cairo.Context, width: int, height: int, user_data):
        total_w = self.get_allocated_width()
        total_h = self.get_allocated_height()
        inner_x = self.margin_left
        inner_w = max(1, total_w - self.margin_left - self.margin_right)
        inner_y = self.margin_top
        inner_h = max(1, total_h - self.margin_top - self.margin_bottom)

        cr.set_source_rgb(*self.bg_color)
        cr.rectangle(0, 0, total_w, total_h)
        cr.fill()

        if not self.values:
            return

        # compute autoscale from valid numeric values
        numeric = [v for v in self.values if v is not None]
        if numeric:
            mn = min(numeric)
            mx = max(numeric)
        else:
            mn, mx = 0.0, 1.0

        # ensure some span
        if math.isclose(mn, mx):
            mn -= 1.0
            mx += 1.0

        # small padding
        pad = (mx - mn) * 0.05
        mn -= pad
        mx += pad

        # compute tick and label strategy
        tick_step, label_values, show_labels = self._compute_ticks_and_labels(mn, mx)
        span = mx - mn

        # helper to map value->y
        def y_of(v: float) -> float:
            return inner_y + (1.0 - (v - mn) / span) * inner_h

        # draw vertical tick marks (small ticks) across the inner area
        cr.set_source_rgb(*self.axis_color)
        cr.set_line_width(1.0)
        # find first tick >= mn
        first_tick = math.ceil(mn / tick_step) * tick_step
        t = first_tick
        while t <= mx + 1e-9:
            y = y_of(t)
            cr.move_to(inner_x - 6, y)
            cr.line_to(inner_x, y)
            cr.stroke()
            t += tick_step

        # draw numeric labels for label_values (if any)
        if show_labels and label_values:
            layout = self.create_pango_layout("")
            for val in label_values:
                y = y_of(val)
                layout.set_text(f"{int(val) if float(val).is_integer() else f'{val:.2f}'}")
                cr.set_source_rgb(*self.font_color)
                # align right inside margin
                cr.move_to(4, y - 8)
                PangoCairo.show_layout(cr, layout)

        # draw horizontal axis line at bottom
        cr.set_source_rgb(*self.axis_color)
        cr.move_to(inner_x, y_of(0))
        cr.line_to(inner_x + inner_w, y_of(0))
        cr.stroke()

        # draw solid polyline segments for contiguous valid points
        cr.set_line_width(1.0)
        n = len(self.values)
        last_valid_idx = None
        for i, v in enumerate(self.values):
            if v is not None:
                if last_valid_idx is None:
                    last_valid_idx = i
                else:
                    x1 = inner_x + last_valid_idx + 0.5
                    y1 = y_of(self.values[last_valid_idx])
                    x2 = inner_x + i + 0.5
                    y2 = y_of(v)
                    cr.set_source_rgb(*self.line_color)
                    cr.move_to(x1, y1)
                    cr.line_to(x2, y2)
                    cr.stroke()
                    last_valid_idx = i

        # dashed connectors across None gaps
        i = 0
        while i < n:
            if self.values[i] is None:
                left = i - 1
                while left >= 0 and self.values[left] is None:
                    left -= 1
                right = i
                while right < n and self.values[right] is None:
                    right += 1
                if left >= 0 and right < n:
                    x1 = inner_x + left + 0.5
                    y1 = y_of(self.values[left])
                    x2 = inner_x + right + 0.5
                    y2 = y_of(self.values[right])
                    cr.set_source_rgb(*self.dash_color)
                    cr.set_line_width(1.0)
                    cr.set_dash([6.0, 4.0], 0)
                    cr.move_to(x1, y1)
                    cr.line_to(x2, y2)
                    cr.stroke()
                    cr.set_dash([], 0)
                elif left < 0 and right < n:
                    # beginning gap: connect from default 0.0 to first valid
                    x2 = inner_x + right + 0.5
                    y2 = y_of(self.values[right])
                    cr.set_source_rgb(*self.dash_color)
                    cr.set_line_width(1.0)
                    cr.set_dash([6.0, 4.0], 0)
                    cr.move_to(inner_x + 0.5, y_of(0.0))
                    cr.line_to(x2, y2)
                    cr.stroke()
                    cr.set_dash([], 0)
                i = right
            else:
                i += 1

        if self.current_point_index is not None:
            cr.set_source_rgb(*self.vertical_color)
            cr.set_line_width(1.0)
            cr.move_to(inner_x + self.current_point_index + 0.5, self.margin_top)
            cr.line_to(inner_x + self.current_point_index + 0.5, total_h - self.margin_bottom)
            cr.stroke()

        # # draw small markers for valid points
        # cr.set_source_rgb(*self.line_color)
        # for i, v in enumerate(self.values):
        #     if v is not None:
        #         x = inner_x + i + 0.5
        #         y = y_of(v)
        #         cr.arc(x, y, 1.0, 0, 2 * 3.14159)
        #         cr.fill()

        return
