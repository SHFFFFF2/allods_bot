import struct
import unittest
import zlib

from tools import make_addon_files as maf


class WhiteTexture(unittest.TestCase):
    def test_bin_matches_game_layout(self):
        # Формат подсмотрен у текстур из примеров игры:
        # zlib( 4 нулевых байта + длина данных uint32 LE + блоки DXT1 )
        raw = zlib.decompress(maf.white_texture_bin(8, 8))
        zero, size = struct.unpack("<II", raw[:8])
        self.assertEqual(zero, 0)
        self.assertEqual(size, len(raw) - 8)
        self.assertEqual(size, (8 // 4) * (8 // 4) * 8)

    def test_every_block_is_opaque_white(self):
        raw = zlib.decompress(maf.white_texture_bin(8, 8))[8:]
        for off in range(0, len(raw), 8):
            c0, c1, idx = struct.unpack("<HHI", raw[off:off + 8])
            self.assertEqual(c0, 0xFFFF)
            self.assertGreater(c0, c1)  # 4-цветный режим без прозрачности
            self.assertEqual(idx, 0)    # все пиксели берут цвет c0

    def test_tga_is_white_32bit(self):
        tga = maf.white_tga(8, 8)
        self.assertEqual(tga[2], 2)                       # несжатый truecolor
        self.assertEqual(struct.unpack("<HH", tga[12:16]), (8, 8))
        self.assertEqual(tga[16], 32)
        self.assertEqual(set(tga[18:]), {255})

    def test_utf16_text_has_bom(self):
        self.assertEqual(maf.utf16_text("Аб")[:2], b"\xff\xfe")
        self.assertEqual(maf.utf16_text("Аб")[2:].decode("utf-16-le"), "Аб")


if __name__ == "__main__":
    unittest.main()
