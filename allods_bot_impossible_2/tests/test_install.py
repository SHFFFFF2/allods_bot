import tempfile
import unittest
from pathlib import Path

from aobot.install import install_addon

ROOT = Path(__file__).resolve().parent.parent


class Install(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.game = Path(self.tmp.name)
        (self.game / "data" / "Mods" / "Addons").mkdir(parents=True)
        self.dst = self.game / "data" / "Mods" / "Addons" / "BotBridge"

    def tearDown(self):
        self.tmp.cleanup()

    def test_lua_is_transcoded_to_game_encoding(self):
        install_addon(self.game)
        raw = (self.dst / "Scripts" / "Main.lua").read_bytes()
        self.assertIn("запущен".encode("cp1251"), raw)
        self.assertNotIn("запущен".encode("utf-8"), raw)

    def test_non_lua_files_copied_as_is(self):
        install_addon(self.game)
        src = ROOT / "addon" / "BotBridge" / "Textures" / "White.(UITexture).bin"
        self.assertEqual((self.dst / "Textures" / "White.(UITexture).bin").read_bytes(),
                         src.read_bytes())

    def test_users_config_in_game_is_kept(self):
        install_addon(self.game)
        mine = 'Global( "BOT_SPELLS", { "Атака" } )\n'.encode("cp1251")
        (self.dst / "Scripts" / "Config.lua").write_bytes(mine)
        install_addon(self.game)
        self.assertEqual((self.dst / "Scripts" / "Config.lua").read_bytes(), mine)

    def test_overwrite_config_on_request(self):
        install_addon(self.game)
        (self.dst / "Scripts" / "Config.lua").write_bytes(b"old")
        install_addon(self.game, overwrite_config=True)
        self.assertNotEqual((self.dst / "Scripts" / "Config.lua").read_bytes(), b"old")

    def test_missing_game_folder_raises(self):
        with self.assertRaises(FileNotFoundError):
            install_addon(self.game / "nope")


if __name__ == "__main__":
    unittest.main()
