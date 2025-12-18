# ui/board_view.py
import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Pango, PangoCairo, Gdk
import cairo
from typing import Optional, Dict, Tuple
from ggo.goban_gtk4_modular import (
    on_draw, compute_layout, draw_panel, draw_dashed_rectangles, draw_grid, draw_hoshi, draw_labels, draw_stones,
    DEFAULT_STYLE)


class BoardView(Gtk.Box):
    def __init__(self, board_size: int = 19, base_margin: int = 20, style: Optional[Dict] = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        # board geometry
        self.board_size = board_size
        self.base_margin = base_margin

        # dynamic layout values (computed each draw)
        self._alloc_w = 0
        self._alloc_h = 0
        self._cell = 0.0
        self._board_origin_x = 0.0
        self._board_origin_y = 0.0
        self._layout = {}

        # state
        self.board_state = [[None] * board_size for _ in range(board_size)]
        self.ghost = None
        self.heatmap = None
        self._last_stone : Optional[Tuple[int, int, str]] = None

        # hover tracking
        self._last_hover = None

        # style defaults
        default_style = DEFAULT_STYLE
        default_style.update({
            "ghost_black_alpha": 0.35,
            "ghost_white_alpha": 0.85,
            'ghost_allowed': False,
            "last_stone_mark_radius": 0.345,
        })
        self.style = default_style if style is None else {**default_style, **style}

        # drawing area
        self.darea = Gtk.DrawingArea()
        self.darea.set_hexpand(True)
        self.darea.set_vexpand(True)
        self.darea.set_draw_func(self.on_draw, None)

        # input controllers
        click = Gtk.GestureClick.new()
        click.connect("pressed", self._on_pressed)
        self.darea.add_controller(click)

        motion = Gtk.EventControllerMotion.new()
        motion.connect("motion", self._on_motion)
        self.darea.add_controller(motion)

        self.append(self.darea)

        # callbacks
        self._click_cb = None
        self._hover_cb = None
        self._leave_cb = None
        self._ctrl_click_cb = None

    # Public API
    def set_board(self, board_state):
        self.board_state = [row[:] for row in board_state]
        self.darea.queue_draw()

    def on_click(self, callback):
        self._click_cb = callback

    def on_ctrl_click(self, callback):
        self._ctrl_click_cb = callback

    def on_hover(self, callback):
        self._hover_cb = callback

    def on_leave(self, callback):
        self._leave_cb = callback

    def show_ghost(self, point: Tuple[int, int], color: str):
        self.ghost = (point, color)
        self.darea.queue_draw()

    def clear_ghost(self):
        if self.ghost is not None:
            self.ghost = None
            self.darea.queue_draw()

    def set_last_stone(self, coords: Optional[Tuple[int, int, str]]):
        # print("[BoardView] set_last_stone", coords)
        self._last_stone = coords

    def show_heatmap(self, data: Dict[Tuple[int, int], float]):
        self.heatmap = data
        self.darea.queue_draw()

    def set_style(self, style_updates: Dict):
        self.style.update(style_updates)
        self.darea.queue_draw()

    def draw(self):
        self.darea.queue_draw()

    def set_ghost_allowed(self, allowed: bool):
        """Optional: allow view to render ghost differently if move illegal."""
        self.style['ghost_allowed'] = bool(allowed)
        self.darea.queue_draw()

    def set_katago_stats(self, stats: dict):
        """stats: {(r,c): (win_percent, score, visits, pv_list)}"""
        self._katago_stats = stats or {}
        self.darea.queue_draw()

    def set_top_winrate(self, win_percent: float):
        self._top_winrate = win_percent
        self.darea.queue_draw()

    # Coordinate conversions
    def _point_to_coords(self, r: int, c: int):
        x = self._board_origin_x + c * self._cell
        y = self._board_origin_y + r * self._cell
        return x, y

    def _coords_to_point(self, x: float, y: float):
        if self._cell is None or self._cell <= 0:
            return None
        lx = (x - self._board_origin_x) / self._cell
        ly = (y - self._board_origin_y) / self._cell
        c = int(round(lx))
        r = int(round(ly))
        if 0 <= r < self.board_size and 0 <= c < self.board_size:
            return r, c
        return None

    # Events
    def _on_pressed(self, gesture, n_press, x, y):
        pt = self._coords_to_point(x, y)
        # print(f"[BoardView] _on_pressed: n_press={n_press} x={x:.1f} y={y:.1f} -> pt={pt}")
        if pt is None:
            return
        ev = gesture.get_current_event()
        ctrl = False
        button = None
        if ev is not None:
            # print("[BoardView] dir(ev):", dir(ev))
            state = ev.get_modifier_state()
            button = ev.get_button()
            if state is not None:
                ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        # else:
        # print("[BoardView] ev is None")
        print("[BoardView] click ctrl is", ctrl, "button is", button)
        if not ctrl:
            if self._click_cb:
                try:
                    self._click_cb(pt[0], pt[1], button)
                except Exception as e:
                    print("[BoardView] click callback error:", e)
        else:
            if button == 1 and self._ctrl_click_cb:
                try:
                    self._ctrl_click_cb(pt[0], pt[1])
                except Exception as e:
                    print("[BoardView] ctrl-click callback error:", e)

    def _on_motion(self, controller, x, y):
        pt = self._coords_to_point(x, y)
        if pt:
            if self._last_hover != pt:
                self._last_hover = pt
                if self._hover_cb:
                    try:
                        self._hover_cb(pt[0], pt[1])
                    except Exception as e:
                        print("[BoardView] hover callback error:", e)
        else:
            if self._last_hover is not None:
                self._last_hover = None
                if self._leave_cb:
                    try:
                        self._leave_cb()
                    except Exception as e:
                        print("[BoardView] leave callback error:", e)
                self.clear_ghost()
        return False

    # Drawing
    def on_draw(self, area, cr: cairo.Context, width: int, height: int, user_data):
        self._alloc_w = width
        self._alloc_h = height
        recomputed_stones = [
            (row_n, column_n, color)
            for row_n, row in enumerate(self.board_state)
            for column_n, color in enumerate(row)
            if color is not None
        ]
        board_size = self.board_size
        stones = recomputed_stones
        # ggo.goban_gtk4_modular.on_draw copy/paste -->
        self._layout = layout = compute_layout(cr, board_size, width, height)
        # Call modular draws in order
        draw_panel(cr, board_size, layout, width, height)
        draw_dashed_rectangles(cr, layout)

        # grid, hoshi, stones, coords
        draw_grid(cr, board_size, layout)
        draw_hoshi(cr, board_size, layout)
        draw_labels(cr, board_size, layout)
        draw_stones(cr, board_size, layout, stones)
        # <--
        self._draw_last_stone_mark(cr)

        self._get_origin_and_cell_from_layout()
        self._draw_ghost(cr)
        return

    def _get_origin_and_cell_from_layout(self):
        layout_grid = self._layout['grid']
        (grid_left, grid_top, grid_right, grid_bottom, cell, x0, y0, grid_span) = layout_grid
        self._cell = cell
        self._board_origin_x = x0
        self._board_origin_y = y0

    # Drawing helpers
    def _draw_ghost(self, cr: cairo.Context):
        if not self.ghost:
            return
        (r, c), color = self.ghost
        x, y = self._point_to_coords(r, c)
        radius = self._cell * 0.45
        if color == 'B':
            cr.set_source_rgba(0, 0, 0, self.style["ghost_black_alpha"])
        else:
            cr.set_source_rgba(1, 1, 1, self.style["ghost_white_alpha"])
        cr.arc(x, y, radius, 0, 2 * 3.14159)
        cr.fill()

    def _draw_last_stone_mark(self, cr: cairo.Context):
        if self._last_stone is None:
            return
        grid_left, grid_top, grid_right, grid_bottom, cell, x0, y0, grid_span = self._layout["grid"]
        stone_r = cell * self.style['stone_radius_factor']
        mark_r = stone_r * self.style['last_stone_mark_radius']
        r, c, color = self._last_stone
        color_rgb = self.style[['stone_black', 'stone_white'][color.lower() in ["black", "b"]]]
        cx = x0 + c * cell
        cy = y0 + r * cell
        cr.set_source_rgb(*color_rgb)
        cr.arc(cx, cy, mark_r, 0, 2.0 * math.pi)
        cr.fill()

