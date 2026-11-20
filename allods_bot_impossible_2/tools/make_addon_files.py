"""Генерирует двоичные/служебные файлы аддона BotBridge.

    python -m tools.make_addon_files

Создаёт белую текстуру для ячеек (в формате, который используют текстуры
из примеров игры) и тексты имени/описания в UTF-16LE.
Если игра не примет сгенерированную текстуру, её можно пересобрать штатной
утилитой Mods\\UITextureConvertEditor.exe из White.tga (тип UISingleTexture).
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

ADDON = Path(__file__).resolve().parent.parent / "addon" / "BotBridge"
SIZE = 8


def white_texture_bin(width: int, height: int) -> bytes:
    # DXT1-блок 4x4: c0 = белый (565), c1 = чёрный, все индексы 0 -> c0
    block = struct.pack("<HHI", 0xFFFF, 0x0000, 0)
    data = block * ((width // 4) * (height // 4))
    return zlib.compress(struct.pack("<II", 0, len(data)) + data, 9)


def white_tga(width: int, height: int) -> bytes:
    header = struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0,
                         width, height, 32, 8)
    return header + b"\xff" * (width * height * 4)


def utf16_text(s: str) -> bytes:
    return b"\xff\xfe" + s.encode("utf-16-le")


UITEXTURE_XDB = """<?xml version="1.0" encoding="UTF-8" ?>
<UITexture>
	<mipSW>-1</mipSW>
	<mipsNumber>1</mipsNumber>
	<generateMipChain>false</generateMipChain>
	<type>DXT1</type>
	<width>{w}</width>
	<height>{h}</height>
	<realWidth>{w}</realWidth>
	<realHeight>{h}</realHeight>
	<disableLODControl>false</disableLODControl>
	<alphaTex>false</alphaTex>
	<binaryFileSize>{size}</binaryFileSize>
	<binaryFile href="White.(UITexture).bin" />
	<wrap>false</wrap>
</UITexture>
"""


def main() -> None:
    tex = ADDON / "Textures"
    tex.mkdir(parents=True, exist_ok=True)
    binary = white_texture_bin(SIZE, SIZE)
    (tex / "White.(UITexture).bin").write_bytes(binary)
    (tex / "White.(UITexture).xdb").write_text(
        UITEXTURE_XDB.format(w=SIZE, h=SIZE, size=len(binary)), encoding="utf-8")
    (tex / "White.tga").write_bytes(white_tga(SIZE, SIZE))
    (ADDON / "AddonName.txt").write_bytes(utf16_text("BotBridge"))
    (ADDON / "AddonDescription.txt").write_bytes(utf16_text(
        "Выводит состояние персонажа цветными пикселями в левом верхнем углу экрана."))
    print("готово:", ADDON)


if __name__ == "__main__":
    main()
