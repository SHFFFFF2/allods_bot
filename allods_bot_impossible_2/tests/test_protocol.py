import unittest

from aobot import protocol
from aobot.protocol import DecodeError, GameState


def sample_state(**over):
    base = dict(
        seq=7, avatar_exists=True, dead=False, in_combat=True, casting=False,
        has_target=True, target_dead=False, target_attackable=True,
        target_is_player=False, target_in_melee=True, target_enemy=True,
        target_tagged_other=False, hp=87, mana=None, target_hp=42,
        target_distance=3.4, gcd_ms=1250, spells_known=0b1011,
        spells_ready=0b0001, x=-1234.5, y=20345.7, z=12.3, direction=1.5708,
    )
    base.update(over)
    return GameState(**base)


class RoundTrip(unittest.TestCase):
    def test_encode_then_decode_returns_same_state(self):
        st = sample_state()
        self.assertEqual(protocol.decode_bytes(protocol.encode_bytes(st)), st)

    def test_unknown_distance_and_hp_survive(self):
        st = sample_state(target_distance=None, target_hp=None, has_target=False)
        self.assertEqual(protocol.decode_bytes(protocol.encode_bytes(st)), st)

    def test_spell_ready_reads_mask_bits(self):
        st = sample_state(spells_ready=0b0100)
        self.assertTrue(st.spell_ready(2))
        self.assertFalse(st.spell_ready(0))

    def test_encoded_length_fills_whole_cells(self):
        data = protocol.encode_bytes(sample_state())
        self.assertEqual(len(data) % 3, 0)
        self.assertEqual(len(data) // 3 + 2, protocol.CELL_COUNT)

    def test_target_identity_round_trip(self):
        st = sample_state(target_id=4321, target_kind=777)
        self.assertEqual(protocol.decode_bytes(protocol.encode_bytes(st)), st)

    def test_v2_layout(self):
        self.assertEqual((protocol.VERSION, protocol.PAYLOAD_LEN, protocol.CELL_COUNT), (2, 30, 13))

    def test_kind_hash(self):
        self.assertEqual(protocol.kind_hash(b""), 0)
        self.assertEqual(protocol.kind_hash(b"A"), 66)          # (0*31+65) % 65521 + 1
        self.assertTrue(1 <= protocol.kind_hash("Краб".encode("cp1251")) <= 65521)


class Corruption(unittest.TestCase):
    def test_flipped_byte_is_rejected(self):
        data = bytearray(protocol.encode_bytes(sample_state()))
        data[4] ^= 0x01
        with self.assertRaises(DecodeError):
            protocol.decode_bytes(bytes(data))

    def test_wrong_version_is_rejected(self):
        data = bytearray(protocol.encode_bytes(sample_state()))
        data[0] = 99
        with self.assertRaises(DecodeError):
            protocol.decode_bytes(bytes(data))


def render(cells, cell_px, offset=(0, 0), size=(80, 20), bg=(10, 20, 30)):
    """Синтетический «скриншот»: функция get_pixel(x, y) -> (r, g, b)."""
    ox, oy = offset

    def get_pixel(x, y):
        if oy <= y < oy + cell_px:
            i = (x - ox) // cell_px
            if x >= ox and i < len(cells):
                return cells[i]
        return bg
    return get_pixel, size[0], size[1]


class Strip(unittest.TestCase):
    def cells(self, st=None):
        return protocol.encode_cells(st or sample_state())

    def test_locate_and_decode_from_pixels(self):
        get, w, h = render(self.cells(), cell_px=4)
        geo = protocol.locate_strip(get, w, h)
        self.assertEqual(protocol.read_strip(get, geo), sample_state())

    def test_locate_with_offset_and_other_cell_size(self):
        get, w, h = render(self.cells(), cell_px=3, offset=(2, 5), size=(60, 20))
        geo = protocol.locate_strip(get, w, h)
        self.assertEqual((geo.x, geo.y, geo.cell), (2, 5, 3))
        self.assertEqual(protocol.read_strip(get, geo), sample_state())

    def test_small_color_drift_on_sync_is_tolerated(self):
        cells = self.cells()
        r, g, b = cells[0]
        cells[0] = (r - 1, g + 1, b)
        get, w, h = render(cells, cell_px=4)
        self.assertIsNotNone(protocol.locate_strip(get, w, h))

    def test_missing_strip_returns_none(self):
        get, w, h = render([], cell_px=4)
        self.assertIsNone(protocol.locate_strip(get, w, h))


if __name__ == "__main__":
    unittest.main()
