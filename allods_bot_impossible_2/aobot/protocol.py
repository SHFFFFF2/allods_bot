"""Протокол «пиксельного моста» между аддоном BotBridge и ботом.

Аддон рисует в левом верхнем углу окна игры полоску из CELL_COUNT квадратных
ячеек. Каждая ячейка — три байта (R, G, B):

    ячейка 0  — SYNC, метка начала полосы;
    ячейка 1  — CALIB, контрольный цвет (по нему видно искажение цветов);
    ячейки 2… — PAYLOAD_LEN байт данных + 2 байта контрольной суммы + выравнивание.

Раскладка данных (все многобайтовые числа — big-endian):

    0      версия протокола (VERSION)
    1      счётчик кадров seq (0..255, растёт при каждой перерисовке)
    2      флаги 1: b0 аватар есть, b1 мёртв, b2 в бою, b3 кастует,
                    b4 есть цель, b5 цель мертва, b6 цель можно атаковать,
                    b7 цель — игрок
    3      флаги 2: b0 цель в ближнем бою, b1 цель враждебна,
                    b2 цель «помечена» другим игроком
    4      здоровье, %        (255 — неизвестно)
    5      мана, %            (255 — неизвестно)
    6      здоровье цели, %   (255 — неизвестно)
    7-8    дистанция до цели, дециметры (0xFFFF — неизвестно)
    9-10   остаток глобального кулдауна, мс / 10
    11-12  маска известных умений из списка BOT_SPELLS аддона
    13-14  маска умений, готовых к применению (без учёта ГКД)
    15-17  X, дециметры, знаковое 24 бита
    18-20  Y, то же
    21-23  Z, то же
    24-25  направление, радианы * 10000
    26-27  идентификатор цели (0 — нет цели, иначе 1..65535)
    28-29  вид цели: хэш названия (0 — неизвестно, иначе 1..65521)

Тот же формат реализован в addon/BotBridge/Scripts/Packer.lua — при изменении
меняйте оба файла (tests/test_lua_packer.py проверяет совпадение).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional

VERSION = 2
SYNC = (0xA5, 0x5A, 0xC3)
CALIB = (0x0F, 0x80, 0xF0)
PAYLOAD_LEN = 30
MAX_SPELLS = 16
_BODY_LEN = PAYLOAD_LEN + 2
_BODY_PADDED = _BODY_LEN + (-_BODY_LEN) % 3
CELL_COUNT = 2 + _BODY_PADDED // 3

UNKNOWN_BYTE = 255
UNKNOWN_U16 = 0xFFFF
SYNC_TOLERANCE = 6

Pixel = tuple[int, int, int]
GetPixel = Callable[[int, int], Pixel]


class DecodeError(ValueError):
    """Полоса прочитана, но данные повреждены или чужой версии."""


@dataclass(frozen=True)
class GameState:
    seq: int = 0
    avatar_exists: bool = False
    dead: bool = False
    in_combat: bool = False
    casting: bool = False
    has_target: bool = False
    target_dead: bool = False
    target_attackable: bool = False
    target_is_player: bool = False
    target_in_melee: bool = False
    target_enemy: bool = False
    target_tagged_other: bool = False
    hp: Optional[int] = None
    mana: Optional[int] = None
    target_hp: Optional[int] = None
    target_distance: Optional[float] = None
    gcd_ms: int = 0
    spells_known: int = 0
    spells_ready: int = 0
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    direction: float = 0.0
    target_id: int = 0
    target_kind: int = 0

    def spell_ready(self, index: int) -> bool:
        return bool(self.spells_ready >> index & 1)

    def spell_known(self, index: int) -> bool:
        return bool(self.spells_known >> index & 1)


def checksum(data: bytes) -> tuple[int, int]:
    """Fletcher-16 (модуль 255)."""
    s1 = s2 = 0
    for b in data:
        s1 = (s1 + b) % 255
        s2 = (s2 + s1) % 255
    return s1, s2


KIND_LOG_PREFIX = "BotBridge: вид цели "


def kind_hash(data: bytes) -> int:
    """Вид цели по байтам названия: 1..65521, для пустого названия 0.

    Та же формула в BotKind (Collect.lua)."""
    if not data:
        return 0
    h = 0
    for b in data:
        h = (h * 31 + b) % 65521
    return h + 1


def _round(v: float) -> int:
    """Округление как в Lua-упаковщике: math.floor(v + 0.5)."""
    return math.floor(v + 0.5)


def _bits(*flags: bool) -> int:
    return sum(1 << i for i, f in enumerate(flags) if f)


def _u16(v: int) -> bytes:
    return bytes(((v >> 8) & 0xFF, v & 0xFF))


def _s24(meters: float) -> bytes:
    v = max(-0x800000, min(0x7FFFFF, _round(meters * 10))) & 0xFFFFFF
    return bytes(((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF))


def _read_s24(b: bytes) -> float:
    v = b[0] << 16 | b[1] << 8 | b[2]
    if v & 0x800000:
        v -= 0x1000000
    return v / 10


def _opt_byte(v: Optional[int]) -> int:
    return UNKNOWN_BYTE if v is None else max(0, min(254, int(v)))


def encode_bytes(st: GameState) -> bytes:
    """Эталонная упаковка (используется в тестах и для сверки с Lua)."""
    dist = UNKNOWN_U16 if st.target_distance is None else max(
        0, min(UNKNOWN_U16 - 1, _round(st.target_distance * 10)))
    direction = _round(st.direction * 10000) % 62832
    payload = bytes((
        VERSION, st.seq & 0xFF,
        _bits(st.avatar_exists, st.dead, st.in_combat, st.casting,
              st.has_target, st.target_dead, st.target_attackable,
              st.target_is_player),
        _bits(st.target_in_melee, st.target_enemy, st.target_tagged_other),
        _opt_byte(st.hp), _opt_byte(st.mana), _opt_byte(st.target_hp),
    )) + _u16(dist) + _u16(min(UNKNOWN_U16, max(0, st.gcd_ms // 10))) \
        + _u16(st.spells_known & 0xFFFF) + _u16(st.spells_ready & 0xFFFF) \
        + _s24(st.x) + _s24(st.y) + _s24(st.z) + _u16(direction) \
        + _u16(st.target_id) + _u16(st.target_kind)
    assert len(payload) == PAYLOAD_LEN
    body = payload + bytes(checksum(payload))
    return body + bytes(_BODY_PADDED - len(body))


def decode_bytes(data: bytes) -> GameState:
    if len(data) < _BODY_LEN:
        raise DecodeError(f"мало данных: {len(data)} байт")
    payload = data[:PAYLOAD_LEN]
    if tuple(data[PAYLOAD_LEN:_BODY_LEN]) != checksum(payload):
        raise DecodeError("контрольная сумма не сошлась")
    if payload[0] != VERSION:
        raise DecodeError(f"версия протокола {payload[0]}, ожидалась {VERSION}")
    f1, f2 = payload[2], payload[3]

    def flag(byte, bit):
        return bool(byte >> bit & 1)

    def opt(b):
        return None if b == UNKNOWN_BYTE else b

    def u16(i):
        return payload[i] << 8 | payload[i + 1]

    dist = u16(7)
    return GameState(
        seq=payload[1],
        avatar_exists=flag(f1, 0), dead=flag(f1, 1), in_combat=flag(f1, 2),
        casting=flag(f1, 3), has_target=flag(f1, 4), target_dead=flag(f1, 5),
        target_attackable=flag(f1, 6), target_is_player=flag(f1, 7),
        target_in_melee=flag(f2, 0), target_enemy=flag(f2, 1),
        target_tagged_other=flag(f2, 2),
        hp=opt(payload[4]), mana=opt(payload[5]), target_hp=opt(payload[6]),
        target_distance=None if dist == UNKNOWN_U16 else dist / 10,
        gcd_ms=u16(9) * 10, spells_known=u16(11), spells_ready=u16(13),
        x=_read_s24(payload[15:18]), y=_read_s24(payload[18:21]),
        z=_read_s24(payload[21:24]), direction=u16(24) / 10000,
        target_id=u16(26), target_kind=u16(28),
    )


def encode_cells(st: GameState) -> list[Pixel]:
    body = encode_bytes(st)
    return [SYNC, CALIB] + [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]


def decode_cells(cells: list[Pixel]) -> GameState:
    return decode_bytes(bytes(c for cell in cells[2:] for c in cell))


# --- поиск полосы на изображении -------------------------------------------

@dataclass(frozen=True)
class StripGeometry:
    x: int      # левый край ячейки SYNC
    y: int      # верхний край
    cell: int   # размер ячейки, пиксели

    def center(self, i: int) -> tuple[int, int]:
        half = self.cell // 2
        return self.x + i * self.cell + half, self.y + half


def _close(p: Pixel, ref: Pixel, tol: int = SYNC_TOLERANCE) -> bool:
    return all(abs(a - b) <= tol for a, b in zip(p, ref))


def locate_strip(get: GetPixel, width: int, height: int,
                 scan: int = 64) -> Optional[StripGeometry]:
    """Ищет ячейку SYNC в левом верхнем углу и определяет размер ячеек."""
    for y in range(min(height, scan)):
        for x in range(min(width, scan)):
            if not _close(get(x, y), SYNC):
                continue
            run = 1
            while x + run < width and _close(get(x + run, y), SYNC):
                run += 1
            tall = 1
            while y + tall < height and _close(get(x, y + tall), SYNC):
                tall += 1
            cell = min(run, tall)
            if cell < 1 or x + cell * CELL_COUNT > width:
                continue
            geo = StripGeometry(x, y, cell)
            if _close(get(*geo.center(1)), CALIB):
                return geo
    return None


def read_strip(get: GetPixel, geo: StripGeometry) -> GameState:
    cells = [get(*geo.center(i)) for i in range(CELL_COUNT)]
    if not _close(cells[0], SYNC):
        raise DecodeError("метка SYNC не на месте — окно сдвинулось?")
    return decode_cells(cells)


def calib_error(get: GetPixel, geo: StripGeometry) -> int:
    """Максимальное отклонение контрольного цвета (0 — цвета передаются точно)."""
    got = get(*geo.center(1))
    return max(abs(a - b) for a, b in zip(got, CALIB))


__all__ = [
    "CALIB", "CELL_COUNT", "DecodeError", "GameState", "MAX_SPELLS", "SYNC",
    "StripGeometry", "calib_error", "decode_bytes", "decode_cells",
    "KIND_LOG_PREFIX", "encode_bytes", "encode_cells", "kind_hash", "locate_strip",
    "read_strip",
]
