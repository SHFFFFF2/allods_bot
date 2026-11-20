"""Установка аддона в игру.

Lua-файлы в репозитории хранятся в UTF-8, а клиент работает со строками в
кодировке Windows (cp1251 у русского клиента): названия умений из API
приходят именно в ней. Поэтому при установке .lua перекодируются.
"""
from __future__ import annotations

import shutil
from pathlib import Path

ADDON_SRC = Path(__file__).resolve().parent.parent / "addon" / "BotBridge"
GAME_ENCODING = "cp1251"


def install_addon(game: Path, overwrite_config: bool = False,
                  encoding: str = GAME_ENCODING) -> Path:
    addons = Path(game) / "data" / "Mods" / "Addons"
    if not addons.parent.exists():
        raise FileNotFoundError(f"нет папки {addons.parent}")
    addons.mkdir(exist_ok=True)
    dst = addons / "BotBridge"
    user_cfg = dst / "Scripts" / "Config.lua"
    kept = user_cfg.read_bytes() if user_cfg.exists() and not overwrite_config else None

    if dst.exists():
        shutil.rmtree(dst)
    for src in ADDON_SRC.rglob("*"):
        target = dst / src.relative_to(ADDON_SRC)
        if src.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix == ".lua":
            target.write_bytes(src.read_text(encoding="utf-8").encode(encoding))
        else:
            shutil.copyfile(src, target)
    if kept is not None:
        user_cfg.write_bytes(kept)
    return dst
