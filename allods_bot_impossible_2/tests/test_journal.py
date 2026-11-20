import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from aobot.journal import FightRecorder
from aobot.protocol import GameState

CLOCK = lambda: datetime(2026, 11, 17, 19, 30)


class FightRecorderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.d = Path(self._tmp.name)

    def test_writes_one_json_line_per_fight(self):
        d = self.d
        rec = FightRecorder(d, wall_clock=CLOCK)
        rec.begin(51, 777, "rotation", 10.0)
        rec.step(10.5, GameState(avatar_exists=True, target_hp=80), ["1", "3"], "3")
        out = rec.end(14.0, "kill")
        lines = (d / "fights-2026-11-17.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        rec_json = json.loads(lines[0])
        self.assertEqual(rec_json, out)
        self.assertEqual((rec_json["outcome"], rec_json["duration"], rec_json["target_kind"]), ("kill", 4.0, 777))
        self.assertEqual(rec_json["steps"][0], {"t": 0.5, "s": rec_json["steps"][0]["s"], "legal": ["1", "3"], "a": "3"})
        self.assertEqual(rec_json["steps"][0]["s"]["target_hp"], 80)
        self.assertEqual((rec_json["v"], rec_json["policy"], rec_json["target_id"]), (1, "rotation", 51))
        self.assertEqual(rec_json["started"], "2026-11-17T19:30:00")

    def test_two_fights_append(self):
        rec = FightRecorder(self.d, wall_clock=CLOCK)
        for _ in range(2):
            rec.begin(1, 0, "rotation", 0.0)
            rec.end(1.0, "dropped")
        lines = (self.d / "fights-2026-11-17.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)

    def test_end_without_begin_returns_none(self):
        self.assertIsNone(FightRecorder(self.d).end(1.0, "kill"))

    def test_rejects_unknown_outcome(self):
        rec = FightRecorder(self.d)
        rec.begin(1, 0, "rotation", 0.0)
        with self.assertRaises(ValueError):
            rec.end(1.0, "won")
        self.assertIsNotNone(rec.end(1.0, "kill"))

    def test_serialisation_failure_warns_once_and_continues(self):
        rec = FightRecorder(self.d, wall_clock=CLOCK)
        with mock.patch("aobot.journal.json.dumps", side_effect=TypeError("bad")):
            with contextlib.redirect_stderr(io.StringIO()) as err:
                for _ in range(2):
                    rec.begin(1, 0, "rotation", 0.0)
                    self.assertIsNotNone(rec.end(1.0, "kill"))
        self.assertEqual(err.getvalue().count("журнал"), 1)

    def test_begin_closes_open_fight_as_stopped(self):
        rec = FightRecorder(self.d, wall_clock=CLOCK)
        rec.begin(1, 0, "rotation", 0.0)
        rec.begin(2, 0, "rotation", 3.0)
        rec.end(5.0, "kill")
        lines = (self.d / "fights-2026-11-17.jsonl").read_text(encoding="utf-8").splitlines()
        first, second = (json.loads(x) for x in lines)
        self.assertEqual((first["target_id"], first["outcome"], first["duration"]), (1, "stopped", 3.0))
        self.assertEqual((second["target_id"], second["outcome"]), (2, "kill"))

    def test_unwritable_directory_warns_once_and_continues(self):
        blocker = self.d / "file"
        blocker.write_text("x")
        rec = FightRecorder(blocker / "fights", wall_clock=CLOCK)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            for _ in range(2):
                rec.begin(1, 0, "rotation", 0.0)
                self.assertIsNotNone(rec.end(1.0, "kill"))
        self.assertEqual(err.getvalue().count("журнал"), 1)

    def test_set_kind_updates_open_fight(self):
        rec = FightRecorder(self.d, wall_clock=CLOCK)
        rec.begin(1, 0, "rotation", 0.0)
        rec.set_kind(7)
        rec.end(1.0, "kill")
        line = (self.d / "fights-2026-11-17.jsonl").read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(json.loads(line)["target_kind"], 7)

    def test_set_kind_without_open_fight_is_noop(self):
        rec = FightRecorder(self.d, wall_clock=CLOCK)
        rec.set_kind(7)
        self.assertIsNone(rec.end(1.0, "kill"))


if __name__ == "__main__":
    unittest.main()
