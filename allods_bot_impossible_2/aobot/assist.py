"""Режим-помощник: по горячей клавише бьёт текущую цель ротацией, пока цель не
пропадёт, и делит игру на бои для журнала.

Играет пользователь; бот включается только по фронту нажатия горячей клавиши
и сам выключается, когда бой закончен (цель убита/потеряна, смерть, чат).
"""
from __future__ import annotations

from typing import Optional

from .actions import Action
from .executor import Executor
from .policy import Policy, legal_steps
from .protocol import GameState
from .rotation import CombatConfig

KILL_HP = 2   # цель пропала, а её последнее здоровье <= этого — бой считается убийством

STATUS_OFF = "выключен"
STATUS_NO_TARGET = "нет цели"
STATUS_NO_SPELLS = "умения не найдены"
STATUS_CHAT = "чат — бот выключен"
STATUS_FIGHT = "бой"
STATUS_WAIT = "ожидание"
STATUS_DEAD = "выключен: смерть"
STATUS_KILLED = "выключен: цель убита"
STATUS_LOST = "выключен: цель потеряна"


# При смене цели игра на кадр-другой показывает «цели нет» — столько ждём,
# прежде чем считать цель потерянной. Живую цель игра тоже иногда на кадр
# отмечает мёртвой — смерть засчитываем, только если она держится DEAD_GRACE.
LOST_GRACE = 0.4
DEAD_GRACE = 0.2


def _target_ok(st: GameState) -> bool:
    return st.has_target and not st.target_dead and st.target_attackable


class Assist:
    def __init__(self, cfg: CombatConfig, policy: Policy, recorder=None):
        self.cfg = cfg
        self.policy = policy
        self.recorder = recorder
        self.ex = Executor(cfg)
        self.active = False
        self.status = STATUS_OFF
        self._key_was_down = False
        self._fight_id: Optional[int] = None   # target_id открытого боя
        self._last_hp: Optional[int] = None    # последнее здоровье цели в бою
        self._kind = 0                         # записанный тип цели открытого боя
        self._last_rec: Optional[tuple] = None  # (seq, legal, выбор) последнего шага журнала
        self._lost_since: Optional[float] = None  # с какого момента цели нет

    # --- журнал --------------------------------------------------------------
    def _begin(self, st: GameState, now: float) -> None:
        self._fight_id = st.target_id
        self._last_hp = st.target_hp
        self._kind = st.target_kind
        self._last_rec = None
        if self.recorder is not None:
            self.recorder.begin(st.target_id, st.target_kind, self.policy.name, now)

    def _end(self, now: float, outcome: str) -> None:
        if self._fight_id is not None and self.recorder is not None:
            self.recorder.end(now, outcome)
        self._fight_id = None
        self._last_hp = None
        self._last_rec = None

    def _finish(self, now: float, outcome: str, status: str) -> None:
        self._lost_since = None
        self._end(now, outcome)
        self.active = False
        self.status = status

    def _was_low(self) -> bool:
        return self._last_hp is not None and self._last_hp <= KILL_HP

    def stop(self, now: float) -> None:
        """Выход из программы: закрыть открытый бой."""
        self._finish(now, "stopped", STATUS_OFF)

    # --- шаг -----------------------------------------------------------------
    def step(self, st: GameState, now: float, hotkey_down: bool,
             typing: bool = False) -> list[Action]:
        self.ex.observe(st, now)
        pressed = hotkey_down and not self._key_was_down
        self._key_was_down = hotkey_down

        if typing:
            # клавиши не должны уйти в чат: выключаемся до любого решения
            if self.active:
                self._finish(now, "stopped", STATUS_CHAT)
            return []

        if not self.active:
            if not pressed:
                return []
            if st.dead:
                self.status = STATUS_DEAD
                return []
            if not _target_ok(st):
                self.status = STATUS_NO_TARGET
                return []
            self.active = True
            self._begin(st, now)

        if st.dead:
            self._finish(now, "death", STATUS_DEAD)
            return []
        if not _target_ok(st):
            if self._lost_since is None:
                self._lost_since = now
            grace = DEAD_GRACE if st.target_dead else LOST_GRACE
            if now - self._lost_since < grace:
                self.status = STATUS_WAIT
                return []
        else:
            self._lost_since = None
        if st.has_target and st.target_id != self._fight_id:
            # исход старого боя — только по его последнему здоровью, а не по новой цели
            low = self._was_low()
            if not _target_ok(st):      # кликнули труп/неатакуемую цель: нового боя нет
                self._finish(now, "kill" if low else "switched",
                             STATUS_KILLED if low else STATUS_LOST)
                return []
            self._end(now, "kill" if low else "switched")
            self._begin(st, now)
        if not _target_ok(st):
            killed = st.target_dead or self._was_low()
            self._finish(now, "kill" if killed else "dropped",
                         STATUS_KILLED if killed else STATUS_LOST)
            return []
        if self._kind == 0 and st.target_kind and self.recorder is not None:
            self._kind = st.target_kind
            self.recorder.set_kind(st.target_kind)
        if st.target_hp is not None:
            self._last_hp = st.target_hp

        if st.spells_known == 0:
            self.status = STATUS_NO_SPELLS
            return []
        return self._decide(st, now)

    def _decide(self, st: GameState, now: float) -> list[Action]:
        self.status = STATUS_FIGHT
        slot = self.ex.slot(st, now)
        if slot is None:
            self.status = STATUS_WAIT
            return []
        legal = legal_steps(self.cfg.rotation, st, self.ex, now)
        choice = self.policy.choose(st, legal)
        if self.recorder is not None:
            keys = [s.key for s in legal]
            chosen = choice.key if choice else None
            mark = (st.seq, tuple(keys), chosen)
            if mark != self._last_rec:      # опрос идёт чаще кадров игры: повторы не пишем
                self._last_rec = mark
                self.recorder.step(now, st, keys, chosen)
        if choice is None or self.ex.queue_blocked(choice.key, slot):
            self.status = STATUS_WAIT
            return []
        return [self.ex.commit(choice.key, choice.spell - 1, slot, now)]
