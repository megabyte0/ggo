# ui/board_view.py
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, cairo

class BoardView(Gtk.Box):
    def __init__(self, board_size=19, base_margin=20):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.board_size = board_size
        self.base_margin = base_margin  # logical margin, scaled to allocation
        # dynamic layout values (updated on draw)
        self._alloc_w = None
        self._alloc_h = None
        self._cell = None
        self._margin = None

        self.board_state = [[None]*board_size for _ in range(board_size)]
        self.ghost = None
        self.heatmap = None

        self.darea = Gtk.DrawingArea()
        self.darea.set_hexpand(True)
        self.darea.set_vexpand(True)
        self.darea.set_draw_func(self.on_draw, None)

        # controllers
        click = Gtk.GestureClick.new()
        click.connect("pressed", self._on_pressed)
        self.darea.add_controller(click)

        motion = Gtk.EventControllerMotion.new()
        motion.connect("motion", self._on_motion)
        self.darea.add_controller(motion)

        self.append(self.darea)

        self._click_cb = None
        self._hover_cb = None
        self._last_hover = None

    # Public API
    def set_board(self, board_state):
        # expect a full new matrix; copy defensively
        self.board_state = [row[:] for row in board_state]
        self.darea.queue_draw()

    def on_click(self, callback):
        self._click_cb = callback

    def on_hover(self, callback):
        self._hover_cb = callback

    def show_ghost(self, point, color):
        self.ghost = (point, color)
        self.darea.queue_draw()

    def show_heatmap(self, data):
        self.heatmap = data
        self.darea.queue_draw()

    def draw(self):
        self.darea.queue_draw()

    def clear_ghost(self):
        if self.ghost is not None:
            self.ghost = None
            self.darea.queue_draw()


    # Layout helpers (use current allocation)
    def _update_layout(self, width, height):
        # compute usable square area and scale margin/cell accordingly
        size = min(width, height)
        # margin scaled from base_margin relative to size (so margin adapts)
        margin = max(8, int(self.base_margin * (size / 600.0)))
        # cell spacing across board_size-1 intervals
        cell = (size - 2*margin) / (self.board_size - 1)
        # store values
        self._alloc_w = width
        self._alloc_h = height
        self._cell = cell
        self._margin = margin
        # compute board origin (centered)
        self._board_origin_x = (width - (self._margin*2 + self._cell*(self.board_size-1))) / 2 + self._margin
        self._board_origin_y = (height - (self._margin*2 + self._cell*(self.board_size-1))) / 2 + self._margin

    def _point_to_coords(self, r, c):
        x = self._board_origin_x + c * self._cell
        y = self._board_origin_y + r * self._cell
        return x, y

    def _coords_to_point(self, x, y):
        # map widget coords to board indices using current layout
        if self._cell is None:
            return None
        # convert to local board coordinates
        lx = (x - self._board_origin_x) / self._cell
        ly = (y - self._board_origin_y) / self._cell
        c = int(round(lx))
        r = int(round(ly))
        if 0 <= r < self.board_size and 0 <= c < self.board_size:
            return r, c
        return None

    # Event handlers
    def _on_pressed(self, gesture, n_press, x, y):
        print(f"[BoardView] _on_pressed: n_press={n_press} x={x:.1f} y={y:.1f}")
        pt = self._coords_to_point(x, y)
        if pt:
            print(f"[BoardView] clicked at point {pt}")
            if self._click_cb:
                try:
                    self._click_cb(pt[0], pt[1], 1)
                except Exception as e:
                    print("[BoardView] click callback error:", e)
        else:
            print("[BoardView] click outside board")

    def _on_motion(self, controller, x, y):
        pt = self._coords_to_point(x, y)
        # debug
        print(f"[BoardView] motion at x={x:.1f} y={y:.1f} -> pt={pt}")

        # If pointer is over a board cell
        if pt:
            # call hover only when cell changed
            if self._last_hover != pt:
                self._last_hover = pt
                if self._hover_cb:
                    try:
                        self._hover_cb(pt[0], pt[1])
                    except Exception as e:
                        print("[BoardView] hover callback error:", e)
        else:
            # pointer outside board: clear last hover and ghost
            if self._last_hover is not None:
                self._last_hover = None
                # notify controller that pointer left (optional)
                # if you want controller to know about leave, you can add a callback
                # here; for now just clear ghost in view
                self.clear_ghost()
        return False

    # GTK4 draw func: (area, cr, width, height, user_data)
    def on_draw(self, area, cr, width, height, user_data):
        # update layout based on current allocation
        self._update_layout(width, height)

        # background
        cr.set_source_rgb(0.95, 0.9, 0.8)
        cr.paint()

        # draw grid lines using computed origin and cell
        cr.set_source_rgb(0, 0, 0)
        cr.set_line_width(1)
        for i in range(self.board_size):
            y = self._board_origin_y + i * self._cell
            x0 = self._board_origin_x
            x1 = self._board_origin_x + (self.board_size-1) * self._cell
            cr.move_to(x0, y); cr.line_to(x1, y); cr.stroke()

            x = self._board_origin_x + i * self._cell
            y0 = self._board_origin_y
            y1 = self._board_origin_y + (self.board_size-1) * self._cell
            cr.move_to(x, y0); cr.line_to(x, y1); cr.stroke()

        # heatmap (if any)
        if self.heatmap:
            for (r,c), val in self.heatmap.items():
                x,y = self._point_to_coords(r,c)
                alpha = min(0.8, max(0.05, val))
                cr.set_source_rgba(1, 0, 0, alpha)
                cr.arc(x, y, self._cell*0.45, 0, 2*3.14159)
                cr.fill()

        # stones
        for r in range(self.board_size):
            for c in range(self.board_size):
                v = self.board_state[r][c]
                if v:
                    x,y = self._point_to_coords(r,c)
                    if v == 'B':
                        cr.set_source_rgb(0,0,0)
                    else:
                        cr.set_source_rgb(1,1,1)
                    cr.arc(x, y, self._cell*0.45, 0, 2*3.14159)
                    cr.fill_preserve()
                    cr.set_source_rgb(0,0,0)
                    cr.set_line_width(1)
                    cr.stroke()

        # ghost (draw after stones so it's visible)
        if self.ghost:
            (r,c), color = self.ghost
            x,y = self._point_to_coords(r,c)
            # make ghost bright for visibility; later tune alpha/color
            if color == 'B':
                cr.set_source_rgba(0,0,0,0.45)
            else:
                cr.set_source_rgba(1,0.9,0.2,0.9)  # bright yellow for white ghost test
            cr.arc(x, y, self._cell*0.45, 0, 2*3.14159)
            cr.fill()

        return
