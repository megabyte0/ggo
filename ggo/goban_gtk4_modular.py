#!/usr/bin/env python3
# coding: utf-8
"""
goban_gtk4_modular.py

GTK4 Goban renderer with modular draw functions:
- draw_grid
- draw_hoshi
- draw_stones
- draw_coords
- draw_panel (outer areas and borders)

Configuration comes from goban.env via python-dotenv.

Run: python3 goban_gtk4_modular.py
"""
import itertools
import sys

import gi, os, math
from cairo import Context

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Pango, PangoCairo
import cairo
from dotenv import load_dotenv
from typing import List, Tuple, Any

DEFAULT_STYLE = {}
# Load env
DEFAULT_STYLE['env_path'] = os.path.join(os.path.dirname(__file__), "goban.env")
if os.path.exists(DEFAULT_STYLE['env_path']):
    load_dotenv(DEFAULT_STYLE['env_path'], override=False)
else:
    # Allow running without file for convenience
    pass


# Helpers to read env with defaults
def getf(name: str, default: float) -> float:
    v = os.getenv(name)
    return float(v) if v is not None else float(default)


def geti(name: str, default: int) -> int:
    v = os.getenv(name)
    return int(v) if v is not None else int(default)


def gets(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v is not None else default


def get_rgb(name: str, default: str) -> Tuple[float, float, float]:
    rgb = gets(name, default)
    rgb = rgb.strip().lstrip('#')
    assert len(rgb) == 6
    return tuple(
        i / 255
        for i in (
            int(rgb[j:j + 2], 16)
            for j in range(0, 6, 2)
        )
    )


# Configurable constants (from .env)
DEFAULT_STYLE['board_size'] = geti("BOARD_SIZE", 19)

DEFAULT_STYLE['outer_margin'] = getf("OUTER_MARGIN",
                    0)  # outer gap from window edge to viewport (user requested no white margin by default 0)
DEFAULT_STYLE['outer_border_dash'] = gets("OUTER_BORDER_DASH", "6,4")
DEFAULT_STYLE['label_margin'] = getf("LABEL_MARGIN", 8)  # margin between labels area and stone area
DEFAULT_STYLE['inset_labels_factor'] = getf("INSET_LABELS_FACTOR", 0.18)
DEFAULT_STYLE['min_cell'] = getf("MIN_CELL", 6.0)
DEFAULT_STYLE['outer_margin_relative'] = getf("OUTER_MARGIN_RELATIVE", 0)
DEFAULT_STYLE['outer_margin_fixed'] = getf("OUTER_MARGIN_FIXED", 3)
DEFAULT_STYLE['inner_padding_relative'] = getf("INNER_PADDING_RELATIVE", 0)
DEFAULT_STYLE['inner_padding_fixed'] = getf("INNER_PADDING_FIXED", 6)

DEFAULT_STYLE['font_scale'] = getf("FONT_SCALE", 0.34)
DEFAULT_STYLE['stone_radius_factor'] = getf("STONE_RADIUS_FACTOR", 0.46)
DEFAULT_STYLE['hoshi_radius_factor'] = getf("HOSHI_RADIUS_FACTOR", 0.12)
DEFAULT_STYLE['line_width_factor'] = getf("LINE_WIDTH_FACTOR", 0.03)

# Colors (r,g,b)
DEFAULT_STYLE['neutral_outside'] = tuple(float(x) for x in gets("NEUTRAL_OUTSIDE", "0.92,0.92,0.92").split(","))
# DEFAULT_STYLE['board_bg'] = tuple(float(x) / 100 for x in gets("BOARD_BG", "63.1,58.7,49.3").split(","))
DEFAULT_STYLE['board_bg'] = get_rgb("BOARD_BG",
                   # "#CB7324"
                   # "#B2611A"
                   "#C0742A"
                   # "#BA6B21"
                   # "#C68038"
                   # "#A55412"
                   )
DEFAULT_STYLE['line_color'] = tuple(float(x) for x in gets("LINE_COLOR", "0.08,0.08,0.08").split(","))
DEFAULT_STYLE['star_color'] = tuple(float(x) for x in gets("STAR_COLOR", "0.08,0.08,0.08").split(","))
DEFAULT_STYLE['stone_black'] = tuple(float(x) for x in gets("STONE_BLACK", "0.03,0.03,0.03").split(","))
DEFAULT_STYLE['stone_white'] = tuple(float(x) for x in gets("STONE_WHITE", "0.99,0.99,0.99").split(","))
DEFAULT_STYLE['border_color'] = tuple(float(x) for x in gets("BORDER_COLOR", "0.5,0.5,0.5").split(","))

DEFAULT_STYLE['font_family'] = gets("FONT_FAMILY", "Sans")


# Utility: column labels A.. (skip I)
def column_labels(n: int) -> List[str]:
    labels = []
    ch = ord('A')
    while len(labels) < n:
        c = chr(ch)
        if c == 'I':
            ch += 1
            continue
        labels.append(c)
        ch += 1
    return labels


# Pango helper
def create_layout(cr: cairo.Context, font_size: int, text: str):
    layout = PangoCairo.create_layout(cr)
    desc = Pango.font_description_from_string(f"{DEFAULT_STYLE['font_family']} {font_size}")
    layout.set_font_description(desc)
    layout.set_text(text, -1)
    return layout


def draw_text_cr(cr: cairo.Context, x: float, y: float, text: str,
                 font_size: int, align: str = "center", valign: str = "center", color=(0, 0, 0)):
    layout = create_layout(cr, font_size, text)
    w, h = layout.get_pixel_size()
    ox = x
    oy = y
    if align == "center":
        ox = x - w / 2.0
    elif align == "left":
        ox = x
    elif align == "right":
        ox = x - w
    if valign == "center":
        oy = y - h / 2.0
    elif valign == "top":
        oy = y
    elif valign == "bottom":
        oy = y - h
    cr.set_source_rgb(*color)
    cr.move_to(ox, oy)
    PangoCairo.show_layout(cr, layout)
    # if valign in ['top', 'bottom']:
    #     draw_dashed_rectangle(cr, ox, oy, w, h)


# Goban class
def increase_size(coords: Tuple[float, float, float, float], increase: Tuple[float, float],
                  increase_coeff: int = 1) -> Tuple[float, float, float, float]:
    return tuple(i + j * coeff * increase_coeff for i, j, coeff in zip(coords, increase * 2, (-1, -1, 2, 2)))


def shift(coords: Tuple[float, float, float, float], increase: Tuple[float, float],
          increase_coeff: int = 1) -> Tuple[float, float, float, float]:
    return tuple(i + j * increase_coeff for i, j in zip(coords, increase + (0, 0)))


def compute_font_size_from_cell(cell: float) -> int:
    # compute font size
    font_px = max(10, int(round(cell * DEFAULT_STYLE['font_scale'])))
    return font_px


def row_labels(size: int) -> list[str]:
    return [str(size - i) for i in range(size)]


def compute_text_sizes(cr: cairo.Context, board_size: int, font_size: int):
    layout = create_layout(cr, font_size, '')
    dimensions = []
    y_offset_top = None
    y_offset_bottom = None
    for texts, dimension_index in [
        (row_labels(board_size), 0),
        ([''.join(column_labels(board_size))], 1),
    ]:
        max_dimension = float('-inf')
        for text in texts:
            layout.set_text(text, -1)
            w, h = layout.get_pixel_size()
            if dimension_index == 0:
                # print([
                #     (i.x, i.y, i.width, i.height)
                #     for i in layout.get_pixel_extents()
                # ], file=sys.stderr)
                # print((w, h), text, file=sys.stderr)
                dimension = (w, h)[dimension_index]
            else:
                ink_rect = layout.get_pixel_extents().ink_rect
                dimension = ink_rect.height
                y_offset_top = ink_rect.y
                y_offset_bottom = h - (ink_rect.y + ink_rect.height)
            if dimension > max_dimension:
                max_dimension = dimension
        dimensions.append(max_dimension)
    return tuple(dimensions) + (y_offset_top, y_offset_bottom)


def compute_cell_size(cr: cairo.Context, board_size: int, width: int, height: int):
    # margin + margin + letters + (margin + margin + 19)*cell_size = w_h_size
    # letters = cell*font_size_ratio*letters_coeff
    letters_coefficients = [i / 100 for i in compute_text_sizes(cr, board_size, 100)[:2]]
    cell_size = min(
        (dimension - margin * 2 - padding * 2) / (
                board_size + margin_relative * 2 + padding_relative * 2 + letter_relative * 2)
        for dimension, margin, padding, margin_relative, padding_relative, letter_relative in (
            zip(
                [width, height],
                [DEFAULT_STYLE['outer_margin_fixed']] * 2,
                [DEFAULT_STYLE['inner_padding_fixed']] * 2,
                [DEFAULT_STYLE['outer_margin_relative']] * 2,
                [DEFAULT_STYLE['inner_padding_relative']] * 2,
                letters_coefficients,
            )
        )
    )
    font_size = compute_font_size_from_cell(cell_size)
    letters_dimensions = compute_text_sizes(cr, board_size, font_size)
    cell_size = min(
        (dimension - margin * 2 - padding * 2 - letters_dimension * 2) / (
                board_size + margin_relative * 2 + padding_relative * 2)
        for dimension, margin, padding, letters_dimension, margin_relative, padding_relative in (
            zip(
                [width, height],
                [DEFAULT_STYLE['outer_margin_fixed']] * 2,
                [DEFAULT_STYLE['inner_padding_fixed']] * 2,
                letters_dimensions[:2],
                [DEFAULT_STYLE['outer_margin_relative']] * 2,
                [DEFAULT_STYLE['inner_padding_relative']] * 2,
            )
        )
    )
    return cell_size, font_size, letters_dimensions


def grid_from_cell_and_stone_place(board_size: int, cell: float, stone_left: float, stone_top: float) -> tuple[
    float, float, float, float, float, float, float, float]:
    # grid intersections origin (top-left) is half-cell inside stone_area
    half = cell / 2.0
    x0 = stone_left + half
    y0 = stone_top + half
    grid_span = (board_size - 1) * cell
    grid_left = x0
    grid_top = y0
    grid_right = x0 + grid_span
    grid_bottom = y0 + grid_span
    grid = (grid_left, grid_top, grid_right, grid_bottom, cell, x0, y0, grid_span)
    return grid


def compute_layout(cr: cairo.Context, board_size: int, width: int, height: int):
    cell_size, font_size, letters_dimensions = compute_cell_size(cr, board_size, width, height)
    board = (0, 0, cell_size * board_size, cell_size * board_size)
    board_with_padding = increase_size(board, (DEFAULT_STYLE['inner_padding_fixed'] + DEFAULT_STYLE['inner_padding_relative'] * cell_size,) * 2)
    labels = increase_size(board_with_padding, letters_dimensions[:2])
    overall = increase_size(labels, (DEFAULT_STYLE['outer_margin_fixed'] + DEFAULT_STYLE['outer_margin_relative'] * cell_size,) * 2)
    start = tuple((i - j) / 2 for i, j in zip([width, height], overall[2:]))
    shift_back_amount: Tuple[float, float] = tuple(i - j for i, j in zip(start, overall[:2]))
    # print(board, board_with_padding, labels, overall, (width, height), start, file=sys.stderr, sep='\n')
    board_shifted = shift(board, shift_back_amount)
    return {
        "viewport": shift(overall, shift_back_amount),  # (vp_left, vp_top, vp_w, vp_h),
        "labels_area": shift(labels, shift_back_amount),  # (labels_left, labels_top, labels_w, labels_h),
        "stone_area": board_shifted,  # (stone_left, stone_top, stone_side, stone_side),
        "grid": grid_from_cell_and_stone_place(board_size, cell_size, *(board_shifted[:2])),
        "font_px": font_size,  # font_px,
        "letters_dimensions": letters_dimensions,
    }


def draw_dashed_rectangle(cr: cairo.Context, labels_left: float, labels_top: float, labels_w: float,
                          labels_h: float):
    cr.set_source_rgb(*DEFAULT_STYLE['border_color'])
    cr.set_line_width(1.0)
    cr.set_dash([4.0, 3.0])
    cr.rectangle(labels_left + 0.5, labels_top + 0.5, labels_w - 1.0, labels_h - 1.0)
    cr.stroke()
    cr.set_dash([])


# Modular draw functions

def draw_stones(cr: cairo.Context, board_size: int, layout, stones: List):
    grid_left, grid_top, grid_right, grid_bottom, cell, x0, y0, grid_span = layout["grid"]
    stone_r = cell * DEFAULT_STYLE['stone_radius_factor']
    line_width = max(1.0, cell * DEFAULT_STYLE['line_width_factor'])
    for r, c, color in stones:
        cx = x0 + c * cell
        cy = y0 + r * cell
        if color.lower() in ["black", "b"]:
            cr.set_source_rgb(*DEFAULT_STYLE['stone_black'])
            cr.arc(cx, cy, stone_r, 0, 2.0 * math.pi)
            cr.fill()
        else:
            cr.set_source_rgb(*DEFAULT_STYLE['stone_white'])
            cr.arc(cx, cy, stone_r, 0, 2.0 * math.pi)
            cr.fill_preserve()
            cr.set_source_rgb(0, 0, 0)
            cr.set_line_width(max(1.0, line_width * 0.9))
            cr.stroke()


def draw_labels(cr: cairo.Context, board_size: int, layout):
    grid_left, grid_top, grid_right, grid_bottom, cell, x0, y0, grid_span = layout["grid"]
    stone_left, stone_top, stone_side, _ = layout["stone_area"]
    labels_left, labels_top, labels_w, labels_h = layout["labels_area"]
    font_px = layout["font_px"]
    letters_width, letters_height, y_offset_top, y_offset_bottom = layout["letters_dimensions"]

    # row labels left/right inside stone area (inset)
    padding = DEFAULT_STYLE['inner_padding_fixed'] + DEFAULT_STYLE['inner_padding_relative'] * cell
    left_x = (stone_left + labels_left - padding) / 2
    right_x = left_x + (stone_side + labels_w) / 2 + padding
    row_centers = [y0 + i * cell for i in range(board_size)]
    for i, label in enumerate(row_labels(board_size)):
        ycenter = row_centers[i]
        draw_text_cr(cr, left_x, ycenter, label, font_px, align="center", valign="center")
        draw_text_cr(cr, right_x, ycenter, label, font_px, align="center", valign="center")

    # column labels top/bottom inside stone area
    top_y = labels_top - y_offset_top + 1
    bottom_y = labels_top + labels_h + y_offset_bottom
    col_centers = [x0 + i * cell for i in range(board_size)]
    for idx, lab in enumerate(column_labels(board_size)):
        xcenter = col_centers[idx]
        draw_text_cr(cr, xcenter, top_y, lab, font_px, align="center", valign="top")
        draw_text_cr(cr, xcenter, bottom_y, lab, font_px, align="center", valign="bottom")

    cr.new_path()


def draw_hoshi(cr: cairo.Context, board_size: int, layout):
    grid_left, grid_top, grid_right, grid_bottom, cell, x0, y0, grid_span = layout["grid"]
    if board_size == 19:
        hoshi_r = max(1.0, cell * DEFAULT_STYLE['hoshi_radius_factor'])
        cr.set_source_rgb(*DEFAULT_STYLE['star_color'])
        for r in (3, 9, 15):
            for c in (3, 9, 15):
                cx = x0 + c * cell
                cy = y0 + r * cell
                cr.arc(cx, cy, hoshi_r, 0, 2.0 * math.pi)
                cr.fill()


def draw_grid(cr: cairo.Context, board_size: int, layout):
    grid_left, grid_top, grid_right, grid_bottom, cell, x0, y0, grid_span = layout["grid"]
    # # stone area background
    # stone_left, stone_top, stone_side, _ = layout["stone_area"]
    # cr.set_source_rgb(*DEFAULT_STYLE['board_bg'])
    # cr.rectangle(stone_left, stone_top, stone_side, stone_side)
    # cr.fill()

    # grid lines
    line_width = max(1.0, cell * DEFAULT_STYLE['line_width_factor'])
    cr.set_source_rgb(*DEFAULT_STYLE['line_color'])
    cr.set_line_width(line_width)
    for i in range(board_size):
        xi = x0 + i * cell
        cr.move_to(xi, grid_top)
        cr.line_to(xi, grid_bottom)
    for j in range(board_size):
        yj = y0 + j * cell
        cr.move_to(grid_left, yj)
        cr.line_to(grid_right, yj)
    cr.stroke()


def draw_panel(cr: cairo.Context, board_size: int, layout, width: int, height: int):
    # fills outside neutral and draws outer dashed border (viewport)
    vp_left, vp_top, vp_w, vp_h = layout["viewport"]
    cr.set_source_rgb(*DEFAULT_STYLE['neutral_outside'])
    # cr.rectangle(0, 0, int(self.get_allocated_width()), int(self.get_allocated_height()))
    cr.rectangle(0, 0, width, height)
    cr.fill()

    # # outer dashed border
    # cr.set_source_rgb(*DEFAULT_STYLE['border_color'])
    # cr.set_line_width(1.0)
    # dash = [float(x) for x in DEFAULT_STYLE['outer_border_dash'].split(",")] if isinstance(DEFAULT_STYLE['outer_border_dash'], str) else [6.0, 4.0]
    # cr.set_dash(dash)
    # cr.rectangle(vp_left + 0.5, vp_top + 0.5, vp_w - 1.0, vp_h - 1.0)
    # cr.stroke()
    # cr.set_dash([])

    cr.set_source_rgb(*DEFAULT_STYLE['board_bg'])
    cr.rectangle(vp_left, vp_top, vp_w, vp_h)
    cr.fill()


def on_draw(cr: cairo.Context, board_size: int, width: int, height: int, stones: list[tuple[int, int, str]]):
    layout = compute_layout(cr, board_size, width, height)
    # Call modular draws in order
    draw_panel(cr, board_size, layout, width, height)
    draw_dashed_rectangles(cr, layout)

    # grid, hoshi, stones, coords
    draw_grid(cr, board_size, layout)
    draw_hoshi(cr, board_size, layout)
    draw_labels(cr, board_size, layout)
    draw_stones(cr, board_size, layout, stones)
    return layout


def draw_dashed_rectangles(cr: Context, layout: dict[
    str, tuple[float, float, float, float] | tuple[float, float, float, float, float, float, float, float] | int |
         tuple[Any, ...]]):
    # outer labels-area border (drawn here as dashed rectangle)
    labels_left, labels_top, labels_w, labels_h = layout["labels_area"]
    draw_dashed_rectangle(cr, labels_left, labels_top, labels_w, labels_h)

    # inner border around stone area
    cell = layout["grid"][4]
    padding = DEFAULT_STYLE['inner_padding_fixed'] + DEFAULT_STYLE['inner_padding_relative'] * cell
    stone_left, stone_top, stone_side, _ = increase_size(layout["stone_area"], (padding,) * 2)
    draw_dashed_rectangle(cr, stone_left, stone_top, stone_side, stone_side)


class Goban(Gtk.DrawingArea):
    def __init__(self, size=DEFAULT_STYLE['board_size']):
        super().__init__()
        self.set_draw_func(self.on_draw)
        self.size = size
        self.col_labels = column_labels(size)
        self.row_labels = row_labels(size)
        # demo stones (r,c,color)
        self.stones: List[Tuple[int, int, str]] = [
            (x, y, ['black', 'white'][n % 2])
            for n, (x, y) in enumerate(
                itertools.chain(
                    ((0, y) for y in range(18)),
                    ((x, 18) for x in range(18)),
                    ((18, 18 - y) for y in range(18)),
                    ((18 - x, 0) for x in range(18)),
                )
            )
        ]
        # self.stones = []

    # The main draw func
    def on_draw(self, area, cr: cairo.Context, width: int, height: int):
        board_size = self.size
        stones = self.stones
        on_draw(cr, board_size, width, height, stones)


# GTK App
class GobanApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=None)

    def do_activate(self):
        win = Gtk.ApplicationWindow(application=self)
        win.set_title("Goban GTK4 Modular")
        win.set_default_size(900, 800)
        goban = Goban(size=DEFAULT_STYLE['board_size'])
        win.set_child(goban)
        win.present()


def main():
    app = GobanApp()
    return app.run([])


if __name__ == "__main__":
    # attempt to import dotenv function, if missing user may install python-dotenv
    try:
        from dotenv import load_dotenv  # already used above
    except Exception:
        pass
    raise SystemExit(main())
