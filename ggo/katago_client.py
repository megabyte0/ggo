# katago_client.py
import threading
import random
from typing import Dict, Tuple, List, Callable

# Тип результата: move -> (winrate_percent, score, visits, pv_list)
# heatmap: {(r,c): score_value}
KatagoResult = Dict[Tuple[int,int], Tuple[float, float, int, List[Tuple[int,int]]]]

def analyze_position_async(board_state, to_move, callback: Callable[[KatagoResult, dict], None]):
    """
    Запускает анализ в фоне и вызывает callback(result, meta) в главном потоке через GLib.idle_add.
    Здесь — stub: возвращает случайные данные. Замените реальным вызовом katago.
    """
    def worker():
        # простая имитация: для нескольких случайных точек
        size = len(board_state)
        result = {}
        for _ in range(min(30, size*size)):
            r = random.randrange(size)
            c = random.randrange(size)
            if board_state[r][c] is not None:
                continue
            win = random.uniform(30, 70)  # %
            score = random.uniform(-10, 10)  # points
            visits = random.randint(1, 2000)
            # pv: sequence of moves (r,c)
            pv = [(r,c)]
            for _ in range(4):
                rr = random.randrange(size); cc = random.randrange(size)
                pv.append((rr,cc))
            result[(r,c)] = (win, score, visits, pv)
        meta = {
            'best_win': max((v[0] for v in result.values()), default=None),
            'best_score': None
        }
        callback(result, meta)
    t = threading.Thread(target=worker, daemon=True)
    t.start()
