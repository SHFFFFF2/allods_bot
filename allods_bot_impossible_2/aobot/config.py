"""Чтение config.toml."""
from __future__ import annotations

import dataclasses
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .inputs import MOUSE_BACKENDS
from .keys import parse_combo
from .protocol import MAX_SPELLS
from .rotation import CombatConfig, RotationStep


class ConfigError(ValueError):
    pass


@dataclass
class AppConfig:
    combat: CombatConfig = field(default_factory=CombatConfig)
    stop_key: str = "f12"        # остановить бота
    stale_seconds: float = 1.0   # данные старше — бот замирает
    poll_seconds: float = 0.005  # как часто смотреть на экран, с
    window_title: str = "Аллоды Онлайн"
    assist_key: str = "f9"       # включить режим-помощник
    chat_keys: list[str] = field(default_factory=lambda: ["enter", "backspace"])  # открывают чат
    chat_close_keys: list[str] = field(default_factory=lambda: ["enter", "esc"])  # закрывают чат
    input: InputConfig = field(default_factory=lambda: InputConfig())


@dataclass
class InputConfig:
    # клавиши всегда идут через PS/2 (InpOut), настраивается только мышь
    mouse: str = "sendinput"     # sendinput (курсор, без кликов) | ps2 (нужна PS/2-мышь)
    mouse_packet: int = 3        # mouse = "ps2": размер пакета, 3 — обычная, 4 — с колесом


def _check_key(value, where):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(f"{where}: ожидалась строка с клавишей, получено {value!r}")
    try:
        parse_combo(value)
    except KeyError:
        raise ConfigError(f"{where}: неизвестная клавиша {value!r}") from None
    return value


def _check_single_key(value, where):
    """Клавиша для опроса is_down: ровно одна, без сочетаний (в нижнем регистре)."""
    _check_key(value, where)
    if "+" in value:
        raise ConfigError(f"{where}: {value!r} — должна быть одной клавишей, без сочетаний")
    return value.strip().lower()


def _apply(obj, data: dict, where: str, allowed: set[str]):
    for k, v in data.items():
        if k not in allowed:
            raise ConfigError(f"[{where}]: неизвестный параметр {k!r}")
        setattr(obj, k, v)


def parse_config(text: str) -> AppConfig:
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"ошибка синтаксиса TOML: {e}") from None

    app = AppConfig()
    b = app.combat
    if "keys" in raw:
        raise ConfigError("раздел [keys]: бот-фармер удалён, уберите [keys] из config.toml")
    unknown = set(raw) - {"combat", "safety", "rotation", "input", "assist"}
    if unknown:
        raise ConfigError(f"неизвестные разделы: {sorted(unknown)}")

    combat_fields = {f.name for f in dataclasses.fields(CombatConfig)} - {"rotation"}
    _apply(b, raw.get("combat", {}), "combat", combat_fields)

    safety = raw.get("safety", {})
    if "pause_key" in safety:
        raise ConfigError("[safety].pause_key: бот-фармер удалён, уберите pause_key")
    _apply(app, safety, "safety",
           {"stop_key", "stale_seconds", "poll_seconds", "window_title"})
    app.stop_key = _check_single_key(app.stop_key, "[safety].stop_key")

    _apply(app.input, raw.get("input", {}), "input",
           {f.name for f in dataclasses.fields(InputConfig)})
    if app.input.mouse not in MOUSE_BACKENDS:
        raise ConfigError(f"[input].mouse: {app.input.mouse!r}, допустимо: {', '.join(MOUSE_BACKENDS)}")
    if app.input.mouse_packet not in (3, 4):
        raise ConfigError("[input].mouse_packet: 3 или 4")

    assist = dict(raw.get("assist", {}))
    for k in assist:
        if k not in ("key", "chat_keys", "chat_close_keys"):
            raise ConfigError(f"[assist]: неизвестный параметр {k!r}")
    if "key" in assist:
        app.assist_key = assist["key"]
    if "chat_keys" in assist:
        app.chat_keys = assist["chat_keys"]
    if "chat_close_keys" in assist:
        app.chat_close_keys = assist["chat_close_keys"]
    app.assist_key = _check_single_key(app.assist_key, "[assist].key")
    for name in ("chat_keys", "chat_close_keys"):
        value = getattr(app, name)
        if not isinstance(value, list):
            raise ConfigError(f"[assist].{name}: ожидался список клавиш")
        setattr(app, name, [_check_single_key(k, f"[assist].{name}") for k in value])

    step_fields = {f.name for f in dataclasses.fields(RotationStep)}
    b.rotation = []
    for i, item in enumerate(raw.get("rotation", []), 1):
        extra = set(item) - step_fields
        if extra:
            raise ConfigError(f"[[rotation]] #{i}: неизвестные параметры {sorted(extra)}")
        try:
            step = RotationStep(**item)
        except TypeError as e:
            raise ConfigError(f"[[rotation]] #{i}: {e}") from None
        if not 1 <= step.spell <= MAX_SPELLS:
            raise ConfigError(f"[[rotation]] #{i}: spell должен быть от 1 до {MAX_SPELLS}")
        _check_key(step.key, f"[[rotation]] #{i}.key")
        b.rotation.append(step)

    if app.assist_key == app.stop_key:
        raise ConfigError(f"[assist].key совпадает со [safety].stop_key ({app.stop_key!r})")
    busy = {app.assist_key: "[assist].key", app.stop_key: "[safety].stop_key"}
    for step in b.rotation:      # сочетание "ctrl+1" занимает и ctrl, и 1
        for part in parse_combo(step.key) if step.key else []:
            if part in (app.assist_key, app.stop_key):
                raise ConfigError(f"[[rotation]]: клавиша {part!r} занята ({busy[part]}) — "
                                  "нажатие ротации выключило бы бота или закрыло программу")
            busy.setdefault(part, "[[rotation]]")
    for name in ("chat_keys", "chat_close_keys"):
        for k in getattr(app, name):
            if k in busy:
                raise ConfigError(f"[assist].{name}: клавиша {k!r} уже занята ({busy[k]}) — "
                                  "бот путал бы свои нажатия с чатом")
    return app


def load_config(path: Path | str) -> AppConfig:
    path = Path(path)
    try:
        return parse_config(path.read_text(encoding="utf-8"))
    except ConfigError as e:
        raise ConfigError(f"{path}: {e}") from None
