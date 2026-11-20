"""Захват левого верхнего угла клиентской области окна игры (GDI, только чтение экрана)."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Optional

GAME_WINDOW_CLASS = "NIVAL_MMO_ENGINE"
GRAB_W, GRAB_H = 160, 64

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE,
                                   wintypes.DWORD]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int,
                         wintypes.DWORD]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]

SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def find_game_window() -> Optional[int]:
    hwnd = user32.FindWindowW(GAME_WINDOW_CLASS, None)
    return hwnd or None


def is_foreground(hwnd: int) -> bool:
    return user32.GetForegroundWindow() == hwnd


def focus_window(hwnd: int) -> bool:
    """Выводит окно на передний план. Windows разрешает это процессу, который
    недавно получал ввод, поэтому перед вызовом коротко «нажимаем» Alt."""
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.keybd_event(0x12, 0, 0, 0)       # Alt down
    user32.keybd_event(0x12, 0, 2, 0)       # Alt up
    user32.SetForegroundWindow(hwnd)
    return is_foreground(hwnd)


class ScreenGrabber:
    """Возвращает (get_pixel, w, h) для угла окна игры или None."""

    def __init__(self, width: int = GRAB_W, height: int = GRAB_H):
        self.w, self.h = width, height
        self.hwnd: Optional[int] = None
        self.mem_dc = gdi32.CreateCompatibleDC(None)
        bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height,
                               1, 32, 0, 0, 0, 0, 0, 0)
        self.bits = ctypes.c_void_p()
        self.bmp = gdi32.CreateDIBSection(self.mem_dc, ctypes.byref(bmi), 0,
                                          ctypes.byref(self.bits), None, 0)
        if not self.bmp:
            raise OSError("CreateDIBSection не сработал")
        gdi32.SelectObject(self.mem_dc, self.bmp)

    def window(self) -> Optional[int]:
        if not self.hwnd or not user32.IsWindow(self.hwnd):
            self.hwnd = find_game_window()
        return self.hwnd

    def __call__(self):
        hwnd = self.window()
        if not hwnd or user32.IsIconic(hwnd):
            return None
        rc = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rc))
        pt = wintypes.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(pt))
        w, h = min(self.w, rc.right), min(self.h, rc.bottom)
        if w <= 0 or h <= 0:
            return None
        screen = user32.GetDC(None)
        try:
            ok = gdi32.BitBlt(self.mem_dc, 0, 0, w, h, screen, pt.x, pt.y,
                              SRCCOPY | CAPTUREBLT)
        finally:
            user32.ReleaseDC(None, screen)
        if not ok:
            return None
        buf = ctypes.string_at(self.bits, self.w * self.h * 4)
        stride = self.w * 4

        def get_pixel(x: int, y: int):
            i = y * stride + x * 4
            return buf[i + 2], buf[i + 1], buf[i]
        return get_pixel, w, h

    def close(self):
        gdi32.DeleteObject(self.bmp)
        gdi32.DeleteDC(self.mem_dc)
