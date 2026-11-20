import unittest
from pathlib import Path

from aobot.config import ConfigError, load_config, parse_config
from aobot.rotation import RotationStep

ROOT = Path(__file__).resolve().parent.parent


class Config(unittest.TestCase):
    def test_parses_combat_timing_and_rotation(self):
        cfg = parse_config("""
            [combat]
            confirm_frames = 3
            [[rotation]]
            spell = 2
            key = "2"
            max_target_hp = 25
        """)
        self.assertEqual(cfg.combat.confirm_frames, 3)
        self.assertEqual(cfg.combat.rotation,
                         [RotationStep(spell=2, key="2", max_target_hp=25)])

    def test_keys_section_is_rejected_with_hint(self):
        with self.assertRaisesRegex(ConfigError, "фармер"):
            parse_config('[keys]\ntarget = "tab"\n')

    def test_pause_key_is_rejected_with_hint(self):
        with self.assertRaisesRegex(ConfigError, "фармер"):
            parse_config('[safety]\npause_key = "f10"\n')

    def test_timing_fields_go_to_combat_config(self):
        self.assertEqual(parse_config('[combat]\ngcd_lookahead = 0.08\n').combat.gcd_lookahead, 0.08)

    def test_farm_fields_in_combat_are_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config('[combat]\nrest_below = 40\n')
    def test_unknown_option_is_an_error(self):
        with self.assertRaises(ConfigError):
            parse_config('[[rotation]]\nspell = 1\nkey = "1"\ncolour = 3\n')

    def test_spell_number_must_fit_addon_limit(self):
        with self.assertRaises(ConfigError):
            parse_config('[[rotation]]\nspell = 17\nkey = "1"\n')

    def test_safety_defaults(self):
        cfg = parse_config("")
        self.assertEqual(cfg.stop_key, "f12")
        self.assertGreater(cfg.stale_seconds, 0)

    def test_example_config_loads(self):
        cfg = load_config(ROOT / "config.example.toml")
        self.assertTrue(cfg.combat.rotation)

    def test_mouse_defaults_to_sendinput(self):
        self.assertEqual(parse_config("").input.mouse, "sendinput")

    def test_old_backend_option_is_an_error(self):
        with self.assertRaises(ConfigError):
            parse_config('[input]\nbackend = "ps2"\n')

    def test_unknown_mouse_is_an_error(self):
        with self.assertRaises(ConfigError):
            parse_config('[input]\nmouse = "usb3"\n')


    def test_assist_key_default_f9(self):
        self.assertEqual(parse_config("").assist_key, "f9")

    def test_assist_key_from_config(self):
        self.assertEqual(parse_config('[assist]\nkey = "f8"\n').assist_key, "f8")

    def test_assist_unknown_param_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config('[assist]\nbutton = "f8"\n')

    def test_assist_key_same_as_stop_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config('[assist]\nkey = "f12"\n')

    def test_chat_keys_default_without_slash(self):
        self.assertEqual(parse_config("").chat_keys, ["enter", "backspace"])

    def test_chat_close_keys_default(self):
        self.assertEqual(parse_config("").chat_close_keys, ["enter", "esc"])

    def test_letter_assist_key_allowed(self):
        self.assertEqual(parse_config('[assist]\nkey = "e"\n').assist_key, "e")

    def test_chat_close_key_collisions_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config('[assist]\nchat_close_keys = ["f9"]\n')
        with self.assertRaises(ConfigError):
            parse_config('[assist]\nchat_close_keys = ["esc"]\n[[rotation]]\nspell = 1\nkey = "esc"\n')
        with self.assertRaisesRegex(ConfigError, "одной клавишей"):
            parse_config('[assist]\nchat_close_keys = ["shift+esc"]\n')
        with self.assertRaises(ConfigError):
            parse_config('[assist]\nchat_close_keys = "esc"\n')

    def test_chat_key_used_by_rotation_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config('[assist]\nchat_keys = ["enter", "/"]\n[[rotation]]\nspell = 1\nkey = "/"\n')

    def test_chat_key_same_as_assist_or_stop_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config('[assist]\nchat_keys = ["f9"]\n')
        with self.assertRaises(ConfigError):
            parse_config('[assist]\nchat_keys = ["f12"]\n')

    def test_assist_unknown_key_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config('[assist]\nkey = "nope"\n')
        with self.assertRaises(ConfigError):
            parse_config('[assist]\nchat_keys = "enter"\n')

    def test_combo_stop_key_rejected(self):
        with self.assertRaisesRegex(ConfigError, "одной клавишей"):
            parse_config('[safety]\nstop_key = "ctrl+1"\n')

    def test_combo_assist_key_rejected(self):
        with self.assertRaisesRegex(ConfigError, "одной клавишей"):
            parse_config('[assist]\nkey = "ctrl+1"\n')

    def test_combo_chat_key_rejected(self):
        with self.assertRaisesRegex(ConfigError, "одной клавишей"):
            parse_config('[assist]\nchat_keys = ["enter", "shift+1"]\n')

    def test_rotation_combo_still_allowed(self):
        cfg = parse_config('[[rotation]]\nspell = 1\nkey = "ctrl+1"\n')
        self.assertEqual(cfg.combat.rotation[0].key, "ctrl+1")

    def test_chat_key_collides_with_rotation_combo_part(self):
        with self.assertRaises(ConfigError):
            parse_config('[assist]\nchat_keys = ["1"]\n[[rotation]]\nspell = 1\nkey = "ctrl+1"\n')

    def test_rotation_key_equal_stop_or_assist_rejected(self):
        with self.assertRaisesRegex(ConfigError, "занята"):
            parse_config('[[rotation]]\nspell = 1\nkey = "f12"\n')
        with self.assertRaisesRegex(ConfigError, "занята"):
            parse_config('[[rotation]]\nspell = 1\nkey = "f9"\n')

    def test_rotation_combo_part_equal_stop_or_assist_rejected(self):
        with self.assertRaisesRegex(ConfigError, "занята"):
            parse_config('[[rotation]]\nspell = 1\nkey = "ctrl+f12"\n')
        with self.assertRaisesRegex(ConfigError, "занята"):
            parse_config('[assist]\nkey = "f8"\n[[rotation]]\nspell = 1\nkey = "shift+f8"\n')

if __name__ == "__main__":
    unittest.main()
