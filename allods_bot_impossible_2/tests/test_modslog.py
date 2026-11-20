import tempfile
import unittest
from pathlib import Path

from aobot.modslog import LogTail, decode_line, message, read_lines

PFX = "[19:24:29][UserAddon/BotBridge: 1.0 (build 1)]Info: "


class ModsLogTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "mods.txt"

    def test_decode_line_utf8_and_cp1251(self):
        self.assertEqual(decode_line("умение".encode("utf-8")), "умение")
        self.assertEqual(decode_line("Атака".encode("cp1251")), "Атака")

    def test_message_strips_prefix(self):
        line = PFX + "BOTCAT\t1\tEND\tcount=0"
        self.assertEqual(message(line), "BOTCAT\t1\tEND\tcount=0")

    def test_message_keeps_line_without_prefix(self):
        self.assertEqual(message("просто текст"), "просто текст")

    def test_read_lines_mixed_encoding_and_missing_file(self):
        self.path.write_bytes(("a " + "умение").encode("utf-8") + b"\r\n" + "Атака".encode("cp1251") + b"\n")
        self.assertEqual(read_lines(self.path), ["a умение", "Атака"])
        self.assertEqual(read_lines(Path(self._tmp.name) / "нет.txt"), [])

    def test_read_lines_strips_prefix(self):
        self.path.write_bytes((PFX + "x\n").encode("utf-8"))
        self.assertEqual(read_lines(self.path), ["x"])

    def test_log_tail_reads_only_new_and_restarts_on_truncate(self):
        tail = LogTail(self.path)
        self.assertEqual(tail.new_lines(), [])  # файла ещё нет
        self.path.write_bytes(b"one\ntwo\n")
        self.assertEqual(tail.new_lines(), ["one", "two"])
        self.assertEqual(tail.new_lines(), [])
        with open(self.path, "ab") as f:
            f.write(b"three\n")
        self.assertEqual(tail.new_lines(), ["three"])
        self.path.write_bytes(b"x\n")
        self.assertEqual(tail.new_lines(), ["x"])

    def test_log_tail_waits_for_complete_line(self):
        tail = LogTail(self.path)
        self.path.write_bytes(b"one\ntw")
        self.assertEqual(tail.new_lines(), ["one"])
        with open(self.path, "ab") as f:
            f.write(b"o\n")
        self.assertEqual(tail.new_lines(), ["two"])


if __name__ == "__main__":
    unittest.main()
