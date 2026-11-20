"""Статистика боёв по журналу: python -m aobot stats."""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .modslog import read_lines
from .protocol import KIND_LOG_PREFIX


@dataclass(frozen=True)
class Row:
    kind: int
    name: str
    policy: str
    fights: int
    kills: int
    deaths: int
    median_kill_s: Optional[float]


def _valid(rec) -> bool:
    return (isinstance(rec, dict) and isinstance(rec.get("target_kind"), int)
            and not isinstance(rec.get("target_kind"), bool)
            and isinstance(rec.get("outcome"), str)
            and isinstance(rec.get("policy"), str)
            and isinstance(rec.get("duration"), (int, float))
            and not isinstance(rec.get("duration"), bool))


def load_fights(directory: Path) -> tuple[list[dict], int]:
    """Записи из всех fights-*.jsonl и число битых строк (они пропускаются)."""
    fights: list[dict] = []
    bad = 0
    directory = Path(directory)
    if not directory.is_dir():
        return fights, bad
    for path in sorted(directory.glob("fights-*.jsonl")):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    bad += 1
                    continue
                if _valid(rec):
                    fights.append(rec)
                else:
                    bad += 1
    return fights, bad


def kind_names(log_path: Path) -> dict[int, str]:
    """Названия видов из mods.txt (cp1251); при повторе побеждает последняя строка."""
    names: dict[int, str] = {}
    for line in read_lines(log_path):
        i = line.find(KIND_LOG_PREFIX)
        if i < 0:
            continue
        num, sep, name = line[i + len(KIND_LOG_PREFIX):].partition("=")
        num = num.strip()
        if sep and num.isdigit() and name.strip():
            names[int(num)] = name.strip()
    return names


def summarize(fights: list[dict], names: dict[int, str]) -> list[Row]:
    groups: dict[tuple[int, str], list[dict]] = {}
    for f in fights:
        groups.setdefault((f["target_kind"], f["policy"]), []).append(f)
    rows = []
    for (kind, policy), items in groups.items():
        kills = [float(f["duration"]) for f in items if f["outcome"] == "kill"]
        rows.append(Row(kind, names.get(kind, f"вид {kind}"), policy, len(items), len(kills),
                        sum(1 for f in items if f["outcome"] == "death"),
                        statistics.median(kills) if kills else None))
    rows.sort(key=lambda r: -r.fights)
    return rows


def format_rows(rows: list[Row]) -> str:
    head = ("Цель", "Политика", "Боёв", "Убито", "Смертей", "Медиана убийства, с")
    body = [(r.name, r.policy, str(r.fights), str(r.kills), str(r.deaths),
             "-" if r.median_kill_s is None else f"{r.median_kill_s:.1f}") for r in rows]
    widths = [max(len(x[i]) for x in [head] + body) for i in range(len(head))]
    def line(cells):
        return "  ".join(c.ljust(w) if i < 2 else c.rjust(w)
                         for i, (c, w) in enumerate(zip(cells, widths))).rstrip()
    return "\n".join([line(head)] + [line(b) for b in body])
