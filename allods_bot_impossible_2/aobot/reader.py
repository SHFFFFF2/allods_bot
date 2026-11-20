"""Чтение состояния с экрана: поиск полосы, декодирование, контроль свежести."""
from __future__ import annotations

from typing import Callable, Optional

from . import protocol
from .protocol import DecodeError, GameState, StripGeometry

Frame = tuple  # (get_pixel, width, height)


class StateReader:
    def __init__(self, grab: Callable[[], Optional[Frame]], stale_seconds: float = 1.0):
        self.grab = grab
        self.stale_seconds = stale_seconds
        self.geo: Optional[StripGeometry] = None
        self.last_seq: Optional[int] = None
        self.fresh_at = 0.0

    def read(self, now: float) -> tuple[Optional[GameState], str]:
        frame = self.grab()
        if frame is None:
            return None, "окно игры не найдено или свёрнуто"
        get, w, h = frame

        st = None
        err = "полоса аддона не видна (аддон не включён или окно перекрыто)"
        for attempt in range(2):
            if self.geo is None:
                self.geo = protocol.locate_strip(get, w, h)
                if self.geo is None:
                    return None, err
            try:
                st = protocol.read_strip(get, self.geo)
                break
            except DecodeError as e:
                err = f"ошибка данных: {e}"
                self.geo = None  # окно могло сдвинуться — ищем заново
        if st is None:
            return None, err

        if st.seq != self.last_seq:
            self.last_seq = st.seq
            self.fresh_at = now
        elif now - self.fresh_at > self.stale_seconds:
            return None, "данные не обновляются (игра зависла или аддон остановился)"
        return st, "ok"
