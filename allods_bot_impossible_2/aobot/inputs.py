"""Отправка ввода в игру.

Клавиши — только через PS/2: скан-коды пишутся прямо в контроллер клавиатуры i8042
через драйвер InpOut (так работает «режим PS/2» Clickermann). Обычный SendInput и
драйвер Interception игра не принимает (проверено 17.11.2026), поэтому их нет.

Мышь — отдельно, [input].mouse:
- sendinput — SendInput с абсолютными координатами, как MOVE в Clickermann:
              курсор в игре двигается, клики игра не принимает;
- ps2       — пакеты PS/2-мыши, как #ps2_mouse в Clickermann: клики проходят,
              но нужна живая PS/2-мышь (тачпад ноутбука).
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

from .keys import SCANCODES, parse_combo

MOUSE_BACKENDS = ("sendinput", "ps2")
BUTTONS = ("left", "right", "middle")


class InputError(RuntimeError):
    pass


def check_button(button: str) -> None:
    if button not in BUTTONS:
        raise InputError(f"неизвестная кнопка мыши {button!r}, есть: {', '.join(BUTTONS)}")


def cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


class Backend:
    name = "?"

    # --- клавиши ---
    def down(self, key: str) -> None:
        raise InputError(f"{self.name} не умеет клавиши")

    def up(self, key: str) -> None:
        raise InputError(f"{self.name} не умеет клавиши")

    def press(self, combo: str, hold: float = 0.05) -> None:
        parts = parse_combo(combo)
        for p in parts:
            self.down(p)
        try:
            time.sleep(hold)
        finally:
            for p in reversed(parts):
                self.up(p)

    # --- мышь ---
    def move(self, dx: int, dy: int) -> None:
        """Сдвинуть мышь на dx, dy (как физическая мышь: с учётом чувствительности Windows)."""
        raise InputError(f"{self.name} не умеет мышь")

    def mouse_down(self, button: str = "left") -> None:
        raise InputError(f"{self.name} не умеет мышь")

    def mouse_up(self, button: str = "left") -> None:
        raise InputError(f"{self.name} не умеет мышь")

    def click(self, button: str = "left", hold: float = 0.05) -> None:
        check_button(button)
        self.mouse_down(button)
        try:
            time.sleep(hold)
        finally:
            self.mouse_up(button)

    def move_to(self, x: int, y: int, *, tolerance: int = 1, step: int = 60,
                timeout: float = 2.0) -> bool:
        """Довести курсор до точки экрана (x, y) относительными сдвигами.

        Сдвиг физической мыши Windows ускоряет («повышенная точность»), поэтому идём
        короткими шагами и сверяемся с GetCursorPos. Возвращает False, если не дошли.
        """
        end = time.monotonic() + timeout
        while True:
            cx, cy = cursor_pos()
            ex, ey = x - cx, y - cy
            if abs(ex) <= tolerance and abs(ey) <= tolerance:
                return True
            if time.monotonic() > end:
                return False
            # к цели — с запасом вниз, чтобы ускорение не уносило дальше
            sx = max(-step, min(step, ex if abs(ex) < 4 else ex // 2))
            sy = max(-step, min(step, ey if abs(ey) < 4 else ey // 2))
            self.move(sx, sy)
            time.sleep(0.008)

    def release_all(self) -> None:
        pass

    def close(self) -> None:
        self.release_all()


# --- мышь через SendInput -----------------------------------------------------
ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _KEYBDINPUT(ctypes.Structure):   # только для правильного размера INPUT
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", _KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class SendInputMouse(Backend):
    """Мышь через SendInput, как MOVE/LCLICK обычного режима Clickermann.
    Курсор игра принимает, клики — нет."""
    name = "sendinput"
    _FLAGS = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010),
              "middle": (0x0020, 0x0040)}

    def __init__(self):
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        u.SendInput.restype = wintypes.UINT
        u.SetProcessDPIAware()
        self._u = u

    def _send(self, flags: int, dx: int = 0, dy: int = 0) -> None:
        inp = INPUT(type=0)  # INPUT_MOUSE
        inp.u.mi = MOUSEINPUT(dx, dy, 0, flags, 0, 0)
        if self._u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) != 1:
            raise InputError(f"SendInput (мышь) не сработал, код {ctypes.get_last_error()}")

    def move(self, dx, dy):
        self._send(0x0001, int(dx), int(dy))  # MOUSEEVENTF_MOVE

    def move_to(self, x, y, **_):
        """Одним абсолютным сдвигом, как MOVE в Clickermann."""
        w, h = self._u.GetSystemMetrics(0), self._u.GetSystemMetrics(1)  # основной монитор
        ax = (int(x) * 65535 + (w - 1) // 2) // max(w - 1, 1)
        ay = (int(y) * 65535 + (h - 1) // 2) // max(h - 1, 1)
        target = (int(x), int(y))
        # Windows переставляет курсор не мгновенно (в игре — до десятков мс),
        # поэтому ждём и при необходимости повторяем сдвиг.
        for _ in range(3):
            self._send(0x0001 | 0x8000, ax, ay)  # MOVE | ABSOLUTE
            end = time.monotonic() + 0.05
            while time.monotonic() < end:
                if cursor_pos() == target:
                    return True
                time.sleep(0.002)
        return False

    def mouse_down(self, button="left"):
        check_button(button)
        self._send(self._FLAGS[button][0])

    def mouse_up(self, button="left"):
        check_button(button)
        self._send(self._FLAGS[button][1])


# --- PS/2 через InpOut (как «режим PS/2» в Clickermann) ----------------------
# Драйвер inpoutx64.sys даёт доступ к портам ввода-вывода. Контроллеру клавиатуры
# i8042 отдаётся команда 0xD2 «записать в выходной буфер клавиатуры» (порт 0x64),
# затем байт скан-кода (порт 0x60): контроллер выдаёт прерывание, и i8042prt.sys
# принимает байт так, будто его прислала физическая PS/2-клавиатура.
_IOCTL_READ_PORT_UCHAR = (40000 << 16) | (0x801 << 2)
_IOCTL_WRITE_PORT_UCHAR = (40000 << 16) | (0x802 << 2)
_KBC_DATA, _KBC_CMD = 0x60, 0x64
_KBC_WRITE_KBD_BUFFER = 0xD2
_KBC_WRITE_AUX_BUFFER = 0xD3
_STATUS_OBF, _STATUS_IBF = 0x01, 0x02


class PS2Backend(Backend):
    name = "ps2"

    def __init__(self, mouse_packet: int = 3, allow_mouse: bool = False):
        if mouse_packet not in (3, 4):
            raise InputError("mouse_packet: 3 (обычная PS/2-мышь) или 4 (с колесом)")
        self.mouse_packet = mouse_packet
        self.allow_mouse = allow_mouse
        self._buttons = 0
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateFileW.restype = wintypes.HANDLE
        k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.HANDLE]
        k.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
                                      wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        self._k = k
        h = k.CreateFileW("\\\\.\\inpoutx64", 0xC0000000, 0, None, 3, 0x80, None)
        if h == wintypes.HANDLE(-1).value:
            raise InputError(
                f"драйвер InpOut (inpoutx64) не открывается, ошибка {ctypes.get_last_error()}. "
                "Он ставится вместе с Clickermann при первом запуске PS/2-режима "
                "от администратора (или отдельно: InpOut32 с highrez.co.uk, InstallDriver.exe)")
        self._h = h
        self._held: set[str] = set()
        if self._read(_KBC_CMD) == 0xFF:
            self.close()
            raise InputError("PS/2-контроллер (i8042) не найден — у этого компьютера нет PS/2")

    def _read(self, port: int) -> int:
        buf = (ctypes.c_ubyte * 2)(port & 0xFF, port >> 8)
        got = wintypes.DWORD()
        if not self._k.DeviceIoControl(self._h, _IOCTL_READ_PORT_UCHAR, buf, 2, buf, 2,
                                       ctypes.byref(got), None):
            raise InputError(f"чтение порта 0x{port:02x} не удалось")
        return buf[0]

    def _write(self, port: int, value: int) -> None:
        buf = (ctypes.c_ubyte * 3)(port & 0xFF, port >> 8, value)
        got = wintypes.DWORD()
        if not self._k.DeviceIoControl(self._h, _IOCTL_WRITE_PORT_UCHAR, buf, 3, None, 0,
                                       ctypes.byref(got), None):
            raise InputError(f"запись в порт 0x{port:02x} не удалась")

    def _wait(self, mask: int, timeout: float = 0.05) -> None:
        end = time.perf_counter() + timeout
        while self._read(_KBC_CMD) & mask:
            if time.perf_counter() > end:
                return  # контроллер занят — пишем всё равно, как Clickermann
            time.sleep(0)

    def _unjam(self) -> None:
        """Байт висит в выходном буфере, и его никто не забирает (так бывает, если PS/2-мыши
        нет или её драйвер отверг пакет): пока он там, контроллер молчит, вся PS/2 — и
        встроенная клавиатура тоже — «замерзает». Настоящий драйвер забирает байт за
        микросекунды, так что после ожидания он ничей — вычитываем сами."""
        for _ in range(16):
            if not self._read(_KBC_CMD) & _STATUS_OBF:
                return
            self._read(_KBC_DATA)

    def _byte(self, value: int, cmd: int = _KBC_WRITE_KBD_BUFFER) -> None:
        self._wait(_STATUS_IBF | _STATUS_OBF)   # контроллер свободен, прошлый байт забран
        if self._read(_KBC_CMD) & _STATUS_OBF:
            self._unjam()
        self._write(_KBC_CMD, cmd)
        self._wait(_STATUS_IBF)
        self._write(_KBC_DATA, value)
        self._wait(_STATUS_OBF)                 # i8042prt забрал байт
        if cmd == _KBC_WRITE_AUX_BUFFER and self._read(_KBC_CMD) & _STATUS_OBF:
            self._unjam()                       # драйвер мыши байт не взял — не оставлять

    # --- клавиши ---
    def _stroke(self, key: str, up: bool) -> None:
        code, ext = SCANCODES[key]
        if ext:
            self._byte(0xE0)
        self._byte(code | (0x80 if up else 0))

    def down(self, key):
        self._stroke(key, up=False)
        self._held.add(key)

    def up(self, key):
        self._stroke(key, up=True)
        self._held.discard(key)

    # --- мышь: пакеты PS/2-мыши через вспомогательный порт (команда 0xD3) ---
    # Пакет: [кнопки и знаки, dx, dy (+ колесо, если мышь в режиме IntelliMouse)].
    # Байт 0: бит0 левая, бит1 правая, бит2 средняя, бит3 всегда 1, бит4 знак dx, бит5 знак dy.
    # dy у PS/2 растёт вверх, на экране — вниз, поэтому знак меняется.
    _BUTTON_BITS = {"left": 0x01, "right": 0x02, "middle": 0x04}

    def _packet(self, dx: int, dy: int) -> None:
        if not self.allow_mouse:
            raise InputError('PS/2-мышь выключена: задайте [input].mouse = "ps2" явно. '
                             "Нужна живая PS/2-мышь или тачпад на PS/2-порту")
        b0 = 0x08 | self._buttons | (0x10 if dx < 0 else 0) | (0x20 if dy < 0 else 0)
        data = [b0, dx & 0xFF, dy & 0xFF] + [0] * (self.mouse_packet - 3)
        for b in data:
            self._byte(b, _KBC_WRITE_AUX_BUFFER)

    def move(self, dx, dy):
        dx, dy = int(dx), -int(dy)
        while True:
            sx, sy = max(-255, min(255, dx)), max(-255, min(255, dy))
            self._packet(sx, sy)
            dx, dy = dx - sx, dy - sy
            if not dx and not dy:
                return

    def mouse_down(self, button="left"):
        check_button(button)
        self._buttons |= self._BUTTON_BITS[button]
        self._packet(0, 0)

    def mouse_up(self, button="left"):
        check_button(button)
        self._buttons &= ~self._BUTTON_BITS[button]
        self._packet(0, 0)

    def release_all(self):
        for k in list(self._held):
            self.up(k)
        if self._buttons and self.allow_mouse:
            self._buttons = 0
            self._packet(0, 0)

    def close(self):
        if getattr(self, "_h", None):
            try:
                super().close()
            finally:
                self._k.CloseHandle(self._h)
                self._h = None


class SplitBackend(Backend):
    """Клавиши через PS/2, мышь — через SendInput (как #ps2_keyboard без #ps2_mouse
    в Clickermann)."""

    def __init__(self, keyboard: Backend, mouse: Backend):
        self.keyboard, self.mouse = keyboard, mouse
        self.name = f"{keyboard.name}, мышь {mouse.name}"

    def down(self, key):
        self.keyboard.down(key)

    def up(self, key):
        self.keyboard.up(key)

    def move(self, dx, dy):
        self.mouse.move(dx, dy)

    def move_to(self, x, y, **kw):
        return self.mouse.move_to(x, y, **kw)

    def mouse_down(self, button="left"):
        self.mouse.mouse_down(button)

    def mouse_up(self, button="left"):
        self.mouse.mouse_up(button)

    def release_all(self):
        self.keyboard.release_all()
        self.mouse.release_all()

    def close(self):
        try:
            self.keyboard.close()
        finally:
            self.mouse.close()


def make_backend(*, mouse: str = "sendinput", mouse_packet: int = 3) -> Backend:
    """Клавиши — PS/2; мышь — sendinput (по умолчанию) или ps2."""
    if mouse not in MOUSE_BACKENDS:
        raise InputError(f"неизвестный способ для мыши {mouse!r}, есть: {', '.join(MOUSE_BACKENDS)}")
    kb = PS2Backend(mouse_packet, allow_mouse=mouse == "ps2")
    if mouse == "ps2":
        return kb
    try:
        return SplitBackend(kb, SendInputMouse())
    except Exception:
        kb.close()
        raise
