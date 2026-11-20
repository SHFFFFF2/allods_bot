"""Открыт ли чат игры — по нажатиям клавиш.

Аддон не видит строку ввода чата, поэтому бот следит за клавишами сам:
клавиша из open_keys открывает чат, клавиша из close_keys его закрывает
(Enter — в обоих списках: открывает, а повторный Enter отправляет сообщение
и закрывает чат). Клик мышью чат не закрывает. Пока чат открыт, горячая
клавиша помощника не действует — иначе буква в сообщении включила бы бота,
и его нажатия напечатались бы в чат.
"""
from __future__ import annotations

from typing import Iterable


class ChatGuard:
    def __init__(self, open_keys: Iterable[str], close_keys: Iterable[str]):
        self.open_keys = set(open_keys)
        self.close_keys = set(close_keys)
        self.keys = self.open_keys | self.close_keys
        self.is_open = False
        self._down: set[str] = set()

    def update(self, down: set[str]) -> bool:
        """down — какие из self.keys нажаты сейчас; возвращает «чат открыт»."""
        pressed = set(down) - self._down
        self._down = set(down)
        if self.is_open:
            if pressed & self.close_keys:
                self.is_open = False
        elif pressed & self.open_keys:
            self.is_open = True
        return self.is_open

    def reset(self) -> None:
        self.is_open = False
