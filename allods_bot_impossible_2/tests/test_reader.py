import unittest

from aobot import protocol
from aobot.reader import StateReader
from tests.test_protocol import render, sample_state


class FakeScreen:
    def __init__(self):
        self.frame = None

    def show(self, st, cell_px=4, offset=(0, 0)):
        self.frame = render(protocol.encode_cells(st), cell_px, offset)

    def grab(self):
        return self.frame


class Reader(unittest.TestCase):
    def setUp(self):
        self.screen = FakeScreen()
        self.reader = StateReader(self.screen.grab, stale_seconds=1.0)

    def test_no_window(self):
        st, why = self.reader.read(0.0)
        self.assertIsNone(st)
        self.assertIn("окно", why)

    def test_no_strip(self):
        self.screen.frame = render([], 4)
        st, why = self.reader.read(0.0)
        self.assertIsNone(st)
        self.assertIn("полос", why)

    def test_reads_state(self):
        self.screen.show(sample_state(seq=1))
        st, why = self.reader.read(0.0)
        self.assertEqual(st, sample_state(seq=1))

    def test_frozen_counter_becomes_stale(self):
        self.screen.show(sample_state(seq=1))
        self.reader.read(0.0)
        self.assertIsNotNone(self.reader.read(0.5)[0])
        st, why = self.reader.read(1.6)
        self.assertIsNone(st)
        self.assertIn("не обновля", why)

    def test_counter_change_keeps_fresh(self):
        for i in range(5):
            self.screen.show(sample_state(seq=i))
            self.assertIsNotNone(self.reader.read(i * 0.6)[0])

    def test_relocates_when_window_moves(self):
        self.screen.show(sample_state(seq=1))
        self.reader.read(0.0)
        self.screen.show(sample_state(seq=2), offset=(3, 2))
        st, _ = self.reader.read(0.1)
        self.assertEqual(st.seq, 2)

    def test_corrupt_frame_reports_reason(self):
        cells = protocol.encode_cells(sample_state(seq=1))
        cells[5] = (cells[5][0] ^ 1, cells[5][1], cells[5][2])
        self.screen.frame = render(cells, 4)
        st, why = self.reader.read(0.0)
        self.assertIsNone(st)
        self.assertIn("сумма", why)


if __name__ == "__main__":
    unittest.main()
