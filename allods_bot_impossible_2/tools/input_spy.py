"""Шпион ввода: пишет, какие события мыши и клавиатуры видит система и с каким флагом.

    python tools/input_spy.py [секунд] [файл-лога]

Для каждого события из WH_MOUSE_LL / WH_KEYBOARD_LL печатает injected (программный ввод)
или нет. Отдельно отмечает сдвиги курсора без события мыши — так выглядит SetCursorPos.
Нужен, чтобы узнать, как другая программа (например, Clickermann) отправляет ввод.
"""
from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

u = ctypes.WinDLL("user32", use_last_error=True)
LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
u.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
u.SetWindowsHookExW.restype = wintypes.HHOOK
u.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
u.CallNextHookEx.restype = LRESULT
u.PeekMessageW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.UINT,
                           wintypes.UINT]
u.SetProcessDPIAware()


class MSLL(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("data", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("extra", ctypes.c_size_t)]


class KBLL(ctypes.Structure):
    _fields_ = [("vk", wintypes.DWORD), ("scan", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("extra", ctypes.c_size_t)]


MOUSE_MSG = {0x200: "move", 0x201: "L down", 0x202: "L up", 0x204: "R down", 0x205: "R up",
             0x207: "M down", 0x208: "M up", 0x20A: "wheel"}
lines: list[str] = []
t0 = time.perf_counter()
last_hook_pt = [None]


def log(s: str) -> None:
    line = f"{time.perf_counter() - t0:8.3f} {s}"
    lines.append(line)
    print(line, flush=True)


@HOOKPROC
def mouse_proc(code, wp, lp):
    m = ctypes.cast(lp, ctypes.POINTER(MSLL)).contents
    inj = "INJECTED" if m.flags & 0x01 else "настоящее"
    last_hook_pt[0] = (m.pt.x, m.pt.y)
    log(f"мышь {MOUSE_MSG.get(wp, hex(wp)):7s} ({m.pt.x},{m.pt.y}) {inj} extra=0x{m.extra:x}")
    return u.CallNextHookEx(None, code, wp, lp)


@HOOKPROC
def kbd_proc(code, wp, lp):
    k = ctypes.cast(lp, ctypes.POINTER(KBLL)).contents
    inj = "INJECTED" if k.flags & 0x10 else "настоящее"
    log(f"клав vk=0x{k.vk:02x} scan=0x{k.scan:02x} {'up  ' if k.flags & 0x80 else 'down'} {inj}")
    return u.CallNextHookEx(None, code, wp, lp)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 60
    out = sys.argv[2] if len(sys.argv) > 2 else None
    hm = u.SetWindowsHookExW(14, mouse_proc, None, 0)
    hk = u.SetWindowsHookExW(13, kbd_proc, None, 0)
    log(f"слушаю {seconds:.0f} с")
    msg = wintypes.MSG()
    pt = wintypes.POINT()
    prev = None
    end = time.perf_counter() + seconds
    try:
        while time.perf_counter() < end:
            while u.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                pass
            u.GetCursorPos(ctypes.byref(pt))
            cur = (pt.x, pt.y)
            if prev is not None and cur != prev and cur != last_hook_pt[0]:
                log(f"курсор {prev} -> {cur} БЕЗ события мыши (похоже на SetCursorPos)")
                last_hook_pt[0] = cur
            prev = cur
            time.sleep(0.002)
    finally:
        u.UnhookWindowsHookEx(hm)
        u.UnhookWindowsHookEx(hk)
        if out:
            with open(out, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
