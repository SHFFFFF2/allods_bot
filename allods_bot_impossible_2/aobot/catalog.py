"""Разбор выгрузки каталога умений (строки BOTCAT в mods.txt)."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Optional

from .keys import SCANCODES
from .modslog import message

_PREFIX = "BOTCAT\t"
_UNESC = {"\\": "\\", "t": "\t", "n": "\n", "r": "\r"}
_RENAMES = {"num_enter": "numenter", "pg_up": "pageup", "pg_down": "pagedown"}


@dataclass(frozen=True)
class SpellInfo:
    name: str
    sys: str
    desc: str
    params: dict[str, float]
    cd_ms: int
    cast_ms: int
    channel: bool
    harmful: bool
    helpful: bool
    target: int
    range: float
    nogcd: bool


@dataclass(frozen=True)
class SlotInfo:
    slot: int
    kind: str
    name: str
    keys: str
    key: Optional[str]


@dataclass(frozen=True)
class PassiveInfo:
    name: str
    desc: str


@dataclass(frozen=True)
class TalentInfo:
    field: int
    row: int
    col: int
    rank: int
    name: str
    desc: str
    src: str


@dataclass(frozen=True)
class Catalog:
    gen: int
    session: str
    spells: dict[str, SpellInfo] = field(default_factory=dict)
    slots: dict[int, SlotInfo] = field(default_factory=dict)
    passives: list = field(default_factory=list)
    talents: list = field(default_factory=list)
    resource: Optional[tuple[str, int]] = None

    def to_json(self) -> str:
        d = asdict(self)
        d["slots"] = {str(k): v for k, v in d["slots"].items()}
        return json.dumps(d, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "Catalog":
        d = json.loads(text)
        res = d.get("resource")
        return cls(
            gen=d["gen"], session=d["session"],
            spells={k: SpellInfo(**v) for k, v in d["spells"].items()},
            slots={int(k): SlotInfo(**v) for k, v in d["slots"].items()},
            passives=[PassiveInfo(**p) for p in d["passives"]],
            talents=[TalentInfo(**t) for t in d["talents"]],
            resource=(res[0], res[1]) if res else None,
        )


def _unescape(s: str) -> str:
    return re.sub(r"\\(.)", lambda m: _UNESC.get(m.group(1), m.group(0)), s)


def game_key(keys: str) -> Optional[str]:
    """Имя клавиши игры (`ALT+1`, `NUM_ENTER`) -> имя aobot.keys; None, если это не клавиша."""
    if not keys:
        return None
    out = []
    for part in keys.split("+"):
        p = part.strip().lower()
        p = _RENAMES.get(p, p)
        if p.startswith("num_") and p[4:].isdigit():
            p = "num" + p[4:]
        if p not in SCANCODES:
            return None
        out.append(p)
    return "+".join(out)


def keys_from_user_cfg(text: str) -> dict[int, str]:
    """Слот -> клавиши из блока mission_actions файла user.cfg (запасной источник)."""
    out: dict[int, str] = {}
    in_block = False
    slot: Optional[int] = None
    for raw in text.splitlines():
        line = raw.strip()
        if line == "t_b mission_actions":
            in_block = True
        elif line == "t_e mission_actions":
            break
        elif in_block:
            m = re.fullmatch(r"t_b action_(\d+)", line)
            if m:
                slot = int(m.group(1))
                continue
            m = re.fullmatch(r'key=L"(.*)"', line)
            if m and slot is not None and slot not in out:
                out[slot] = m.group(1)
            elif line.startswith("t_e action_"):
                slot = None
    return out


def _fields(parts: list[str]) -> dict[str, str]:
    out = {}
    for p in parts:
        k, _, v = p.partition("=")
        out[k] = _unescape(v)
    return out


def _params(s: str) -> dict[str, float]:
    out = {}
    for item in s.split(";"):
        k, sep, v = item.partition("=")
        if sep:
            try:
                out[k] = float(v)
            except ValueError:
                pass
    return out


def _flag(f: dict, key: str) -> bool:
    return f.get(key, "0") not in ("", "0")


def _num(f: dict, key: str, cast=int, default=0):
    try:
        return cast(f.get(key, default))
    except ValueError:
        return default


def _build(gen: int, session: str, rows: list[tuple[str, dict]]) -> Catalog:
    spells, slots, passives, talents = {}, {}, [], []
    resource = None
    for tag, f in rows:
        if tag == "SPELL":
            spells[f["name"]] = SpellInfo(
                name=f["name"], sys=f.get("sys", ""), desc=f.get("desc", ""),
                params=_params(f.get("params", "")), cd_ms=_num(f, "cd_ms"), cast_ms=_num(f, "cast_ms"),
                channel=_flag(f, "channel"), harmful=_flag(f, "harmful"), helpful=_flag(f, "helpful"),
                target=_num(f, "target"), range=_num(f, "range", float, 0.0), nogcd=_flag(f, "nogcd"))
        elif tag == "SLOT":
            n = _num(f, "slot")
            keys = f.get("keys", "")
            slots[n] = SlotInfo(n, f.get("kind", "other"), f.get("name", ""), keys, game_key(keys))
        elif tag == "PASSIVE":
            passives.append(PassiveInfo(f.get("name", ""), f.get("desc", "")))
        elif tag == "TALENT":
            talents.append(TalentInfo(_num(f, "field"), _num(f, "row"), _num(f, "col"), _num(f, "rank"),
                                      f.get("name", ""), f.get("desc", ""), f.get("src", "raw")))
        elif tag == "RES":
            resource = (f.get("name", ""), _num(f, "max"))
    return Catalog(gen, session, spells, slots, passives, talents, resource)


def parse_dumps(lines: list[str]) -> list[Catalog]:
    """Только полные выгрузки (BEGIN..END с верным count), в порядке файла."""
    result: list[Catalog] = []
    cur: Optional[dict] = None
    for raw in lines:
        line = message(raw)
        if not line.startswith(_PREFIX):
            continue
        parts = line.split("\t")
        if len(parts) < 3 or not parts[1].isdigit():
            continue
        gen, tag, rest = int(parts[1]), parts[2], parts[3:]
        if tag == "BEGIN":
            cur = {"gen": gen, "session": _fields(rest).get("session", ""), "rows": []}
        elif cur is None or cur["gen"] != gen:
            cur = None
        elif tag == "END":
            if _fields(rest).get("count") == str(len(cur["rows"])):
                result.append(_build(gen, cur["session"], cur["rows"]))
            cur = None
        else:
            cur["rows"].append((tag, _fields(rest)))
    return result


def latest(lines: list[str], gen: Optional[int] = None) -> Optional[Catalog]:
    """Последняя полная выгрузка (при gen — последняя с этим номером)."""
    for cat in reversed(parse_dumps(lines)):
        if gen is None or cat.gen == gen:
            return cat
    return None
