"""Выбор умения: интерфейс модели и ротация по умолчанию."""
from __future__ import annotations

from typing import Optional, Protocol, Sequence

from .protocol import GameState
from .rotation import RotationStep, step_applies


class Policy(Protocol):
    name: str

    def choose(self, st: GameState,
               legal: Sequence[RotationStep]) -> Optional[RotationStep]:
        """Выбрать шаг из допустимых; None — ждать."""


class RotationPolicy:
    name = "rotation"

    def __init__(self, rotation: list[RotationStep]):
        self.rotation = rotation

    def choose(self, st: GameState,
               legal: Sequence[RotationStep]) -> Optional[RotationStep]:
        for heals in (True, False):
            for step in legal:
                if step_applies(step, st, heals):
                    return step
        return None


def legal_steps(rotation: list[RotationStep], st: GameState, ex,
                now: float) -> list[RotationStep]:
    """Умения, готовые по маске, не заблокированные неподтверждённым нажатием
    и не нажатые за последние every секунд."""
    used = getattr(ex, "used_at", {})
    return [s for s in rotation
            if st.spell_ready(s.spell - 1) and not ex.retry_blocked(s.key, now)
            and now - used.get(s.key, float("-inf")) >= s.every]
