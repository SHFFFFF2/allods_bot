"""Журнал боёв: один бой (одна цель) -- одна строка JSON."""
from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from .protocol import GameState

OUTCOMES = ("kill", "switched", "dropped", "death", "stopped")


class FightRecorder:
    def __init__(self, directory: Path, wall_clock: Callable[[], datetime] = datetime.now):
        self._dir = Path(directory)
        self._clock = wall_clock
        self._warned = False
        self._open: Optional[dict] = None
        self._t0 = 0.0
        self._started: Optional[datetime] = None

    def begin(self, target_id: int, target_kind: int, policy: str, now: float) -> None:
        if self._open is not None:
            self.end(now, "stopped")
        self._started = self._clock()
        self._t0 = now
        self._open = {
            "v": 1,
            "started": self._started.isoformat(timespec="seconds"),
            "duration": 0.0,
            "policy": policy,
            "target_id": target_id,
            "target_kind": target_kind,
            "outcome": "",
            "steps": [],
        }

    def set_kind(self, kind: int) -> None:
        """Уточнить тип цели открытого боя (имя могло появиться не с первого кадра)."""
        if self._open is not None:
            self._open["target_kind"] = kind

    def step(self, now: float, st: GameState, legal: list[str], chosen: Optional[str]) -> None:
        if self._open is None:
            return
        self._open["steps"].append({
            "t": round(now - self._t0, 3),
            "s": dataclasses.asdict(st),
            "legal": list(legal),
            "a": chosen,
        })

    def end(self, now: float, outcome: str) -> Optional[dict]:
        """Закрыть бой и дописать строку в журнал.

        Неизвестный исход -> ValueError; бой при этом остаётся открытым,
        ничего не пишется.
        """
        if outcome not in OUTCOMES:
            raise ValueError(f"неизвестный исход боя: {outcome!r}")
        if self._open is None:
            return None
        rec = self._open
        rec["duration"] = round(now - self._t0, 3)
        rec["outcome"] = outcome
        started = self._started
        self._open = None
        self._write(rec, started)
        return rec

    def _write(self, rec: dict, started: datetime) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            path = self._dir / f"fights-{started:%Y-%m-%d}.jsonl"
            line = json.dumps(rec, ensure_ascii=False) + "\n"
            with open(path, "a", encoding="utf-8", newline="") as f:
                f.write(line)
        except (OSError, TypeError, ValueError) as e:
            if not self._warned:
                self._warned = True
                print(f"предупреждение: журнал боёв недоступен для записи ({e})", file=sys.stderr)
