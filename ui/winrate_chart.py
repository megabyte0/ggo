# ui/winrate_chart.py
import gi

from ggo.game_tree import Node
from ui.draggable_x_node_chart import DraggableXNodeChart

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, GObject
import cairo
from typing import List, Optional, Any


class WinrateChart(DraggableXNodeChart):
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

        self._0_index_none_value = 0.5
        self._min_y, self._max_y = 0.0, 1.0

    def _get_value_from_node(self, node: Node) -> float | None:
        v = None
        try:
            raw = (node.get_prop("SBKV") or [None])[0]
            if raw is not None:
                v = float(raw) / 100.0
        except Exception:
            v = None
        return v

    def _set_min_and_max_value(self) -> None:
        self._min_y, self._max_y = 0.0, 1.0
