"""Чтение журнала игры mods.txt: смешанная кодировка, срез префикса, дочитывание хвоста."""
from __future__ import annotations

import re
from pathlib import Path

_PREFIX = re.compile(r"^\[[^\]]*\]\[[^\]]*\]\w+: ")


def decode_line(raw: bytes) -> str:
    """Строка лога: UTF-8, а если не выходит — cp1251."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1251", errors="replace")


def message(line: str) -> str:
    """Срезает префикс `[время][UserAddon/...]Info: `; строка без префикса остаётся как есть."""
    return _PREFIX.sub("", line, count=1)


def _lines(data: bytes) -> list[str]:
    return [message(decode_line(raw.rstrip(b"\r"))) for raw in data.split(b"\n")]


def read_lines(path) -> list[str]:
    try:
        data = Path(path).read_bytes()
    except OSError:
        return []
    out = _lines(data)
    if out and out[-1] == "":
        out.pop()
    return out


class LogTail:
    """Отдаёт только дописанное с прошлого вызова; если файл стал короче — читает с начала."""

    def __init__(self, path):
        self.path = Path(path)
        self._pos = 0

    def new_lines(self) -> list[str]:
        try:
            with open(self.path, "rb") as f:
                size = f.seek(0, 2)
                if size < self._pos:
                    self._pos = 0
                f.seek(self._pos)
                data = f.read()
        except OSError:
            return []
        end = data.rfind(b"\n")
        if end < 0:  # неполная последняя строка дочитается в следующий раз
            return []
        self._pos += end + 1
        return _lines(data[:end])
