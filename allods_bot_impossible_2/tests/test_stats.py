import json
import tempfile
import unittest
from pathlib import Path

from aobot.stats import Row, format_rows, kind_names, load_fights, summarize


def fight(kind, outcome, duration, policy="rotation"):
    return {"v": 1, "target_kind": kind, "outcome": outcome, "duration": duration, "policy": policy}


class StatsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.d = Path(self._tmp.name)

    def test_median_kill_time_per_kind_and_policy(self):
        rows = summarize([fight(7, "kill", 10), fight(7, "kill", 20), fight(7, "kill", 40)], {7: "Краб"})
        self.assertEqual(rows, [Row(7, "Краб", "rotation", 3, 3, 0, 20.0)])

    def test_counts_deaths_and_other_outcomes(self):
        rows = summarize([fight(7, "kill", 10), fight(7, "death", 5), fight(7, "dropped", 3)], {})
        self.assertEqual((rows[0].fights, rows[0].kills, rows[0].deaths, rows[0].name), (3, 1, 1, "вид 7"))

    def test_sorted_by_fights_and_no_kills_gives_none(self):
        rows = summarize([fight(1, "death", 5), fight(2, "kill", 4), fight(2, "kill", 6)], {})
        self.assertEqual([r.kind for r in rows], [2, 1])
        self.assertIsNone(rows[1].median_kill_s)

    def test_skips_broken_lines(self):
        d = self.d
        (d / "fights-2026-11-17.jsonl").write_text(
            json.dumps(fight(7, "kill", 10)) + "\n{\"v\": 1, \"outc\n[1, 2]\n", encoding="utf-8")
        fights, bad = load_fights(d)
        self.assertEqual((len(fights), bad), (1, 2))

    def test_records_missing_fields_count_as_broken(self):
        d = self.d
        (d / "fights-2026-11-17.jsonl").write_text(
            json.dumps({"v": 1, "outcome": "kill"}) + "\n" + json.dumps(fight(7, "kill", 10)) + "\n",
            encoding="utf-8")
        fights, bad = load_fights(d)
        self.assertEqual((len(fights), bad), (1, 1))

    def test_missing_dir_gives_nothing(self):
        self.assertEqual(load_fights(self.d / "нет"), ([], 0))

    def test_kind_names_from_cp1251_log(self):
        d = self.d
        line = "[19:08:16][UserAddon/BotBridge: 1.0 (build 1)]Info: BotBridge: вид цели 777 = Береговой краб\r\n"
        (d / "mods.txt").write_bytes(("мусор\r\n" + line).encode("cp1251"))
        self.assertEqual(kind_names(d / "mods.txt"), {777: "Береговой краб"})

    def test_kind_names_last_wins(self):
        d = self.d
        (d / "mods.txt").write_bytes(
            "BotBridge: вид цели 5 = Старое\r\nBotBridge: вид цели 5 = Новое\r\n".encode("cp1251"))
        self.assertEqual(kind_names(d / "mods.txt"), {5: "Новое"})

    def test_missing_log_gives_no_names(self):
        self.assertEqual(kind_names(self.d / "нет.txt"), {})

    def test_format_rows_has_name_and_median(self):
        text = format_rows([Row(7, "Краб", "rotation", 3, 3, 0, 20.0)])
        self.assertIn("Краб", text)
        self.assertIn("20.0", text)
