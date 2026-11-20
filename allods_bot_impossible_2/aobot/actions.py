"""Действия, которые бот просит выполнить: нажать, удерживать, остановиться."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union


@dataclass(frozen=True)
class Press:
    key: str
    at: Optional[float] = None   # нажать не раньше этого момента (time.monotonic)


@dataclass(frozen=True)
class Hold:
    key: str
    seconds: float


@dataclass(frozen=True)
class Stop:
    reason: str


Action = Union[Press, Hold, Stop]
