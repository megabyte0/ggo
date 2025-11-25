# ui/controller.py
# Controller: связывает модель и view. Пока что использует простую in-memory model.
# Later: replace the simple model with ggo.goban_model and katago_client.

from typing import Optional

class Controller:
    def __init__(self, board_view, model=None):
        self.view = board_view
        self.model = model
        self.current_move = 0

        # wire view callbacks
        self.view.on_click(self.on_click)
        self.view.on_hover(self.on_hover)
        print("[Controller] initialized and callbacks registered, view id:", id(self.view))

    def on_click(self, r, c, button):
        print(f"[Controller] on_click called: r={r} c={c} button={button}")
        color = 'B'
        try:
            if self.model:
                self.model.play(color, (r,c))
                self.view.set_board(self.model.get_board())
            else:
                # copy board_state and set new stone
                board = [row[:] for row in self.view.board_state]
                board[r][c] = color
                self.view.set_board(board)
                print(f"[Controller] placed {color} at {(r,c)} and updated view")
        except Exception as e:
            print("[Controller] Illegal move or error:", e)

    def on_hover(self, r, c):
        print(f"[Controller] on_hover called: r={r} c={c}")
        # preview ghost stone as Black for test
        self.view.show_ghost((r,c), 'B')

    # navigation API
    def go_first(self):
        if self.model:
            self.model.goto_move(0)
            self.view.set_board(self.model.get_board())

    def go_last(self):
        if self.model:
            self.model.goto_move(self.model.move_count()-1)
            self.view.set_board(self.model.get_board())

    def step_forward(self):
        if self.model:
            self.model.goto_move(self.model.current_move+1)
            self.view.set_board(self.model.get_board())

    def step_back(self):
        if self.model:
            self.model.goto_move(self.model.current_move-1)
            self.view.set_board(self.model.get_board())
