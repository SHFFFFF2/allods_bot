"""Исполнитель: когда можно нажимать умение (ГКД, каст, подтверждение нажатий).

Не знает, какое умение выбрать — только отвечает, можно ли жать сейчас,
и ведёт учёт нажатий. Не зависит от режима (модель или ротация помощника).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .actions import Press
from .protocol import GameState


@dataclass(frozen=True)
class Slot:
    at: Optional[float]   # когда нажать (time.monotonic); None — сейчас
    queued: bool          # нажатие во время каста


class Executor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.last_seq: Optional[int] = None
        self.gcd_end: Optional[float] = None   # расчётный конец ГКД
        self.spell_at: Optional[float] = None  # когда нажато последнее умение
        self.frames_after_spell = 0
        self.spell_retry: dict[str, float] = {}  # клавиша умения -> когда снова можно
        self.cast_since: Optional[float] = None    # когда начался текущий каст
        # проверка последнего нажатия умения: (клавиша, индекс умения, во время каста)
        self.pending: Optional[tuple[str, int, bool]] = None
        self.pending_ok = False
        self.queue_fails: dict[str, int] = {}
        self.no_queue: set[str] = set()   # умения, которые игра не ставит в очередь каста
        self.used_at: dict[str, float] = {}  # клавиша -> когда игра приняла нажатие

    # --- наблюдение ----------------------------------------------------------
    def observe(self, st: GameState, now: float) -> None:
        fresh = st.seq != self.last_seq
        self.last_seq = st.seq
        after_press = self.spell_at is not None and now > self.spell_at
        if fresh and after_press:
            self.frames_after_spell += 1
        new_gcd = self._track_gcd(st, now)
        if self.pending and after_press:
            key, idx, queued = self.pending
            if new_gcd or not st.spell_ready(idx):
                if not self.pending_ok:
                    self.used_at[key] = self.spell_at
                self.pending_ok = True
            if self._confirmed(now):
                self._settle(key, queued)
        if st.casting:
            if self.cast_since is None:
                self.cast_since = now
        else:
            self.cast_since = None

    def _settle(self, key: str, queued: bool) -> None:
        """Запоминаем умения, которые во время каста нажимаются впустую."""
        self.pending = None
        if not queued:
            return
        if self.pending_ok:
            self.queue_fails[key] = 0
            return
        self.queue_fails[key] = self.queue_fails.get(key, 0) + 1
        if self.queue_fails[key] >= 3:
            self.no_queue.add(key)

    def _track_gcd(self, st: GameState, now: float) -> bool:
        """Обновляет расчётный конец ГКД; True — если виден новый ГКД."""
        if st.gcd_ms <= 0:
            self.gcd_end = None
            return False
        # аддон округляет остаток вниз до 10 мс — берём середину интервала.
        # Кадр мы видим позже, чем аддон его снял, поэтому каждая оценка
        # запаздывает; самая ранняя из оценок одного ГКД — самая точная.
        est = now + (st.gcd_ms + 5) / 1000
        if self.gcd_end is None or est > self.gcd_end + 0.1:
            self.gcd_end = est          # начался новый ГКД
            return True
        self.gcd_end = min(self.gcd_end, est)
        return False

    def _spell_press_allowed(self, now: float) -> bool:
        """После нажатия умения ждём, пока игра покажет результат: иначе на
        следующем кадре, где ГКД ещё не виден, бот нажмёт второе умение."""
        c = self.cfg
        if self.spell_at is None:
            return True
        if now < self.spell_at:
            return False
        return self._confirmed(now) or now - self.spell_at >= c.press_cooldown

    def _confirmed(self, now: float) -> bool:
        c = self.cfg
        return (self.frames_after_spell >= c.confirm_frames
                and now - self.spell_at >= c.confirm_seconds)

    # --- решения -------------------------------------------------------------
    def slot(self, st: GameState, now: float) -> Optional[Slot]:
        c = self.cfg
        queued = bool(st.casting)
        if queued:
            if not c.queue_during_cast or self.cast_since is None:
                return None
            if now - self.cast_since < c.cast_queue_after:
                return None
        at = None
        if st.gcd_ms > 0:
            # умение выбираем заранее и нажимаем ровно к концу ГКД
            if self.gcd_end is None or self.gcd_end - now > c.gcd_lookahead:
                return None
            at = max(now, self.gcd_end - c.gcd_lead)
        if not self._spell_press_allowed(now):
            return None
        return Slot(at, queued)

    def retry_blocked(self, key: str, now: float) -> bool:
        """Нажатие, которое игра не приняла (умение «готово», но не
        срабатывает), не должно запирать выбор: такая клавиша ждёт
        press_cooldown, а выбирающий берёт следующее умение."""
        return now < self.spell_retry.get(key, float("-inf"))

    def queue_blocked(self, key: str, slot: Slot) -> bool:
        return slot.queued and key in self.no_queue

    def commit(self, key: str, spell_index: int, slot: Slot, now: float) -> Press:
        when = now if slot.at is None else slot.at
        # нажатие к концу ГКД могло прийти чуть раньше срока — его разрешаем
        # повторить сразу, как только кадры покажут, что оно не прошло
        self.spell_retry[key] = when if slot.at is not None else when + self.cfg.press_cooldown
        self.spell_at = when
        self.frames_after_spell = 0
        self.pending = (key, spell_index, slot.queued)
        self.pending_ok = False
        return Press(key, slot.at)
