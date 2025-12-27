# ui/board_view.py
import math

import gi
from cairo import Context

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, PangoCairo, Gdk, GLib
import cairo
from typing import Optional, Dict, Tuple, Callable
from ggo.goban_gtk4_modular import (
    compute_layout,
    draw_panel,
    draw_dashed_rectangles,
    draw_grid,
    draw_hoshi,
    draw_labels,
    draw_stones,
    draw_text_cr,
    DEFAULT_STYLE,
    draw_stone,
    cell_center_coords,
)

HEAT_COLORS = {
    9: ("#59A80F", 0.8, 1.0),
    8: ("#59A80F", 0.7, 0.9),
    7: ("#4886D5", 0.8, 0.75),
    6: ("#4886D5", 0.8, 0.6),
    5: ("#4886D5", 0.7, 0.55),
    4: ("#92278F", 0.8, 0.5),
    3: ("#92278F", 0.7, 0.45),
    2: ("#F02311", 0.8, 0.4),
    1: ("#F02311", 0.7, 0.4),
}


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
        self._last_stone: Optional[Tuple[int, int, str]] = None

        # hover tracking
        self._last_hover = None

        # style defaults
        default_style = DEFAULT_STYLE
        default_style.update({
            "ghost_black_alpha": 0.35,
            "ghost_white_alpha": 0.85,
            'ghost_allowed': False,
            "last_stone_mark_radius": 0.345,
            "taken_variation_move_label": (0.15,0.15,0.15),
            "variation_label_size_ratio": 0.38,
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

        self.get_analysis_results: Callable[[], dict] = lambda: {}

        self.variation_delay = 0.5
        self._variation_sim = None
        self._variation_step = -1
        self._variation_sources = []
        self._variation_playing = False

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
        # ggo.goban_gtk4_modular.on_draw copy/paste -->
        self._layout = compute_layout(cr, self.board_size, width, height)
        self._get_origin_and_cell_from_layout()
        # Call modular draws in order
        draw_panel(cr, self.board_size, self._layout, width, height)
        draw_dashed_rectangles(cr, self._layout)

        # grid, hoshi, stones, coords
        draw_grid(cr, self.board_size, self._layout)
        draw_hoshi(cr, self.board_size, self._layout)
        draw_labels(cr, self.board_size, self._layout)
        if not self._variation_playing:
            self._draw_stones_from_state(cr, self.board_state)
        # <--
        if not self._variation_playing:
            self._draw_heatmap(cr)
            self._draw_analysis_overlay(cr)
            self._draw_last_stone_mark(cr)
            self._draw_ghost(cr)
        else:
            self._draw_variation_from_sim(cr)

        return

    def _draw_stones_from_state(self, cr: Context, board_state: list[list[str | None]]):
        recomputed_stones = [
            (row_n, column_n, color)
            for row_n, row in enumerate(board_state)
            for column_n, color in enumerate(row)
            if color is not None
        ]
        stones = recomputed_stones
        draw_stones(cr, self.board_size, self._layout, stones)

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

    def set_analysis_results_getter(self, get_results: Callable[[], dict]):
        """results: dict[str, list[tuple[str, dict]]]"""
        self.get_analysis_results = get_results
        # self.darea.queue_draw()

    def parse_point(self, s: str):
        # 'P16' -> (r,c) ; skip 'I' in columns
        if not s: return None
        col = s[0].upper()
        row = int(s[1:])
        # column index skipping 'I'
        ci = ord(col) - ord('A')
        if col > 'I': ci -= 1
        r = self.board_size - row
        c = ci
        if 0 <= r < self.board_size and 0 <= c < self.board_size:
            return r, c
        return None

    def _fmt_score_lead(self, val: float):
        sign = '+' if val >= 0 else '-'
        a = abs(float(val))
        # start with 3 decimals, then reduce to fit constraints
        for dec in (3, 2, 1, 0):
            s = f"{a:.{dec}f}"
            s = s.rstrip('0').rstrip('.') if '.' in s else s
            if len(s) <= 4:
                return f"{sign}{s}"
        s = f"{int(round(a))}"
        return f"{sign}{s}"

    def _fmt_visits(self, v):
        v = int(v)
        if v >= 1_000_000:
            s = f"{v / 1_000_000:.1f}m"
        elif v >= 1000:
            s = f"{v / 1000:.1f}k"
        else:
            s = str(v)
        if s.endswith('.0m') or s.endswith('.0k'):
            s = s.replace('.0', '')
        return s

    def _draw_analysis_overlay(self, cr: cairo.Context):
        if not getattr(self, 'get_analysis_results', lambda: None)():
            return
        grid_left, grid_top, grid_right, grid_bottom, cell, x0, y0, grid_span = self._layout['grid']
        font_px = max(0, int(cell * 0.28))
        shift_to_top = 0.35
        for key, lst in dict(self.get_analysis_results()).items():
            # key may be ignored; iterate entries
            for move_str, props in lst[:1]:
                pt = self.parse_point(move_str)
                if not pt: continue
                r, c = pt
                cx = x0 + c * cell
                cy = y0 + r * cell
                score = props.get('scoreLead') if props else None
                visits = props.get('visits') if props else None
                if score is None and visits is None:
                    continue
                top_text = self._fmt_score_lead(score) if score is not None else ''
                bot_text = self._fmt_visits(visits) if visits is not None else ''
                # draw white text with slight black shadow for readability
                cr.set_source_rgb(0, 0, 0)
                draw_text = lambda txt, dy: (
                    PangoCairo.create_layout(cr).set_text(txt, -1),
                    cr.set_source_rgb(0, 0, 0),
                    draw_text_cr(cr, cx + 1, cy + dy + 1, txt, font_px, align='center', valign='center',
                                 color=(0, 0, 0))
                )
                if top_text:
                    draw_text_cr(cr, cx, cy - cell * 0.18 - shift_to_top, top_text, font_px, align='center',
                                 valign='center',
                                 color=(1, 1, 1))
                if bot_text:
                    draw_text_cr(cr, cx, cy + cell * 0.18 - shift_to_top, bot_text, font_px, align='center',
                                 valign='center',
                                 color=(1, 1, 1))
        cr.new_path()

    def _hex_to_rgb(self, hx):
        hx = hx.lstrip('#')
        return tuple(int(hx[i:i + 2], 16) / 255.0 for i in (0, 2, 4))

    def _draw_heatmap(self, cr: cairo.Context):
        analysis = dict(self.get_analysis_results())
        # collect all variations into flat list
        variations = [i[0] for i in analysis.values()]
        if not variations:
            return
        # compute maxVisitsWin
        maxVisitsWin = max((v.get('visits', 0) * v.get('winrate', 0)) for move, v in variations)
        grid_left, grid_top, grid_right, grid_bottom, cell, x0, y0, grid_span = self._layout['grid']
        for move, var in variations:
            visits = var.get('visits', 0)
            winrate = var.get('winrate', 0.0)
            if not move:
                continue
            pt = self.parse_point(move)
            if not pt:
                continue
            strength = round((visits * winrate * 8) / maxVisitsWin) + 1
            strength = max(1, min(9, int(strength)))
            hexcol, center_alpha, halo_scale = HEAT_COLORS[strength]
            r, g, b = self._hex_to_rgb(hexcol)
            cx = x0 + pt[1] * cell
            cy = y0 + pt[0] * cell
            radius = cell * 0.6
            grad = cairo.RadialGradient(cx, cy, 0.0, cx, cy, radius)
            grad.add_color_stop_rgba(0.0, r, g, b, center_alpha)
            grad.add_color_stop_rgba(1.0, r, g, b, center_alpha * 0.12 * halo_scale)
            cr.set_source(grad)
            cr.arc(cx, cy, radius, 0, 2 * math.pi)
            cr.fill()
            cr.new_path()

    def stop_variation_playback(self):
        for src in list(self._variation_sources):
            try:
                GLib.source_remove(src)
            except Exception:
                pass
        self._variation_sources = []
        self._variation_sim = None
        self._variation_step = -1
        self._variation_playing = False
        try:
            self.darea.queue_draw()
        except Exception:
            pass

    def start_variation_playback_sim(self, sim):
        self.stop_variation_playback()
        if not sim: return
        self._variation_sim = sim
        self._variation_playing = True
        self._variation_step = 0
        try:
            self.darea.queue_draw()
        except Exception:
            pass
        steps = max(0, len(sim) - 1)
        for i in range(1, steps + 1):
            ms = int(self.variation_delay * 1000 * i)
            src = GLib.timeout_add(ms, self._variation_step_cb, i)
            self._variation_sources.append(src)

    def _variation_step_cb(self, idx):
        if not self._variation_playing or self._variation_sim is None: return False
        max_step = len(self._variation_sim) - 1
        self._variation_step = min(idx, max_step)
        try:
            self.darea.queue_draw()
        except Exception:
            pass
        return False

    def _draw_variation_from_sim(self, cr: cairo.Context):
        states = self._variation_sim
        if not states: return
        step = self._variation_step
        idx = min(step, len(states) - 1)
        state, rc_to_number = states[idx]
        self._draw_stones_from_state(cr, state)
        for (r, c), index in rc_to_number.items():
            text = str(index)
            color = {
                'B': self.style['stone_white'],
                'W': self.style['stone_black'],
                None: self.style['taken_variation_move_label'],
            }[state[r][c]]
            size = round(self.style['variation_label_size_ratio'] * self._cell)
            cx, cy, cell = cell_center_coords(self._layout, r, c)
            draw_text_cr(cr=cr, x=cx, y=cy, text=text, font_size=size, align="center", valign="center", color=color)
