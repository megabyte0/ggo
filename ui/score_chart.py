# ui/score_chart.py
import gi
from cairo import Context

from ggo.game_tree import Node
from ui.draggable_x_node_chart import DraggableXNodeChart

gi.require_version("Gtk", "4.0")
from gi.repository import PangoCairo
import math


class ScoreChart(DraggableXNodeChart):
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

        self.height = height
        self.margin_left = 44
        self.margin_right = 6
        self.margin_top = 8
        self.margin_bottom = 20

        self.axis_color = (0.45, 0.45, 0.45)
        self.font_color = (0.0, 0.0, 0.0)

        self._0_index_none_value = 0.0

    def _get_value_from_node(self, node: Node) -> float | None:
        v = None
        try:
            raw = (node.get_prop("GGBL") or [None])[0]
            if raw is not None:
                v = float(raw)
        except Exception:
            v = None
        return v

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

    def _draw_horizontal_axis(self, cr: Context, total_w: int):
        # draw horizontal axis line at 0
        cr.set_source_rgb(*self.axis_color)
        cr.move_to(self.margin_left, self.y_of(0))
        cr.line_to(total_w - self.margin_right, self.y_of(0))
        cr.stroke()

    def _draw_vertical_ticks_and_labels(self, cr: Context):
        # compute tick and label strategy
        tick_step, label_values, show_labels = self._compute_ticks_and_labels(self._min_y, self._max_y)

        # draw vertical tick marks (small ticks) across the inner area
        cr.set_source_rgb(*self.axis_color)
        cr.set_line_width(1.0)
        # find first tick >= mn
        first_tick = math.ceil(self._min_y / tick_step) * tick_step
        t = first_tick
        while t <= self._max_y + 1e-9:
            y = self.y_of(t)
            cr.move_to(self.margin_left - 6, y)
            cr.line_to(self.margin_left, y)
            cr.stroke()
            t += tick_step

        # draw numeric labels for label_values (if any)
        if show_labels and label_values:
            layout = self.create_pango_layout("")
            for val in label_values:
                y = self.y_of(val)
                layout.set_text(f"{int(val) if float(val).is_integer() else f'{val:.2f}'}")
                cr.set_source_rgb(*self.font_color)
                # align right inside margin
                cr.move_to(4, y - 8)
                PangoCairo.show_layout(cr, layout)

    def _set_min_and_max_value(self):
        # compute autoscale from valid numeric values
        numeric = [v for v in self.values if v is not None]
        if numeric:
            self._min_y = min(numeric)
            self._max_y = max(numeric)
        else:
            self._min_y, self._max_y = 0.0, 1.0

        # ensure some span
        if math.isclose(self._min_y, self._max_y):
            self._min_y -= 1.0
            self._max_y += 1.0

        # small padding
        pad = (self._max_y - self._min_y) * 0.05
        self._min_y -= pad
        self._max_y += pad
