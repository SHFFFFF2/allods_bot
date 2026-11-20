"""Шаг ротации, условия его применимости и настройки боя."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .protocol import GameState


@dataclass
class RotationStep:
    spell: int                       # номер умения в BOT_SPELLS аддона (с 1)
    key: str                         # клавиша на панели умений
    min_target_hp: int = 0           # применять, если здоровье цели >= …
    max_target_hp: int = 100         # … и <= …
    self_hp_below: Optional[int] = None   # только если своё здоровье ниже …
    needs_melee: bool = False        # только если цель в ближнем бою
    every: float = 0.0               # не чаще раза в столько секунд после принятого нажатия
                                     # (держать периодический урон, пока нет чтения эффектов)


def step_applies(step: RotationStep, st: GameState, heals: bool) -> bool:
    """Подходит ли шаг по здоровью и дистанции (готовность умения не смотрим)."""
    if (step.self_hp_below is not None) != heals:
        return False
    if heals:
        return st.hp is not None and st.hp < step.self_hp_below
    thp = st.target_hp if st.target_hp is not None else 100
    if not (step.min_target_hp <= thp <= step.max_target_hp):
        return False
    if step.needs_melee and not st.target_in_melee:
        return False
    return True


@dataclass
class CombatConfig:
    """Тайминг нажатий и ротация (раздел [combat] и [[rotation]] в config.toml)."""
    press_cooldown: float = 0.35     # дольше этого подтверждения нажатия умения не ждём, с
    confirm_seconds: float = 0.2     # ответ сервера на нажатие (начало ГКД) приходит
                                     # с задержкой — раньше этого результат не оцениваем
    confirm_frames: int = 2          # столько свежих кадров аддона после нажатия умения,
                                     # прежде чем решить, что нажатие не прошло
    gcd_lookahead: float = 0.06      # за столько до конца ГКД выбрать умение и ждать, с
    gcd_lead: float = 0.0            # нажать за столько до расчётного конца ГКД, с
    queue_during_cast: bool = True   # жать следующее умение во время каста: игра ставит
                                     # его в очередь и запускает сразу после каста
    cast_queue_after: float = 0.3    # но не раньше, чем через столько после начала каста, с
    rotation: list[RotationStep] = field(default_factory=list)
