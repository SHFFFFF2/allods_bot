"""Скан-коды клавиш (набор 1, как у PS/2) и опрос горячих клавиш.

Сами нажатия отправляет aobot.inputs (через PS/2)."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

# Скан-коды набора 1. (код, расширенная клавиша)
_LETTERS_ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm"]
_ROW_START = [0x10, 0x1E, 0x2C]

SCANCODES: dict[str, tuple[int, bool]] = {
    "esc": (0x01, False), "tab": (0x0F, False), "enter": (0x1C, False),
    "space": (0x39, False), "backspace": (0x0E, False),
    "shift": (0x2A, False), "ctrl": (0x1D, False), "alt": (0x38, False),
    "-": (0x0C, False), "=": (0x0D, False), "[": (0x1A, False), "]": (0x1B, False),
    ";": (0x27, False), "'": (0x28, False), "`": (0x29, False), "\\": (0x2B, False),
    ",": (0x33, False), ".": (0x34, False), "/": (0x35, False),
    "up": (0x48, True), "down": (0x50, True), "left": (0x4B, True), "right": (0x4D, True),
    "insert": (0x52, True), "delete": (0x53, True), "home": (0x47, True),
    "end": (0x4F, True), "pageup": (0x49, True), "pagedown": (0x51, True),
    "f11": (0x57, False), "f12": (0x58, False),
    # цифровой блок (нужен, например, для «управления указателем с клавиатуры»)
    "numlock": (0x45, False), "num/": (0x35, True), "num*": (0x37, False),
    "num-": (0x4A, False), "num+": (0x4E, False), "numenter": (0x1C, True),
    "num.": (0x53, False),
    "num7": (0x47, False), "num8": (0x48, False), "num9": (0x49, False),
    "num4": (0x4B, False), "num5": (0x4C, False), "num6": (0x4D, False),
    "num1": (0x4F, False), "num2": (0x50, False), "num3": (0x51, False),
    "num0": (0x52, False),
}
for _i, _d in enumerate("1234567890"):
    SCANCODES[_d] = (0x02 + _i, False)
for _row, _start in zip(_LETTERS_ROWS, _ROW_START):
    for _i, _ch in enumerate(_row):
        SCANCODES[_ch] = (_start + _i, False)
for _i in range(10):
    SCANCODES[f"f{_i + 1}"] = (0x3B + _i, False)


def parse_combo(combo: str) -> list[str]:
    """'ctrl+1' -> ['ctrl', '1']; бросает KeyError для неизвестных клавиш."""
    parts = [p.strip().lower() for p in combo.split("+")] if combo else []
    if not parts or any(p not in SCANCODES for p in parts):
        raise KeyError(combo)
    return parts


# --- Win32: опрос горячих клавиш (стоп/пауза) -------------------------------
_user32 = None


def _u32():
    global _user32
    if _user32 is None:
        _user32 = ctypes.WinDLL("user32", use_last_error=True)
        _user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
        _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        _user32.GetAsyncKeyState.restype = ctypes.c_short
    return _user32


def is_down(name: str) -> bool:
    """Нажата ли клавиша сейчас (для горячих клавиш стоп/пауза)."""
    code, _ = SCANCODES[name]
    vk = _u32().MapVirtualKeyW(code, 1)  # MAPVK_VSC_TO_VK
    return bool(_u32().GetAsyncKeyState(vk) & 0x8000)
