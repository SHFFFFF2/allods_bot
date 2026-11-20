import unittest

from aobot.catalog import Catalog, game_key, keys_from_user_cfg, latest, parse_dumps

PFX = "[19:24:29][UserAddon/BotBridge: 1.0 (build 1)]Info: "


def esc(v):
    return v.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def dump(gen, *rows, session="100", count=None):
    lines = [f"BOTCAT\t{gen}\tBEGIN\tv=1\tsession={session}"]
    for tag, fields in rows:
        lines.append("\t".join(["BOTCAT", str(gen), tag] + [f"{k}={esc(v)}" for k, v in fields.items()]))
    n = len(rows) if count is None else count
    lines.append(f"BOTCAT\t{gen}\tEND\tcount={n}")
    return lines


SPELL = ("SPELL", {"name": "Вирус", "cd_ms": "0", "cast_ms": "0", "nogcd": "0", "params": "var0=23.1292",
                   "desc": "…каждую секунду в течение 9 сек."})
SLOT = ("SLOT", {"slot": "4", "kind": "spell", "name": "Вирус", "keys": "ALT+1"})

USER_CFG = """t_b mission_actions
t_b action_01
t_b 0
key=L"1"
t_e 0
t_e action_01
t_b action_13
t_b 0
key=L"ALT+1"
t_e 0
t_e action_13
t_e mission_actions
"""


class CatalogTest(unittest.TestCase):
    def test_parse_full_dump(self):
        cat = latest(dump(3, SPELL, SLOT, ("RES", {"name": "blood", "max": "5"})))
        self.assertEqual(cat.gen, 3)
        self.assertEqual(cat.session, "100")
        self.assertEqual(cat.spells["Вирус"].params, {"var0": 23.1292})
        self.assertEqual(cat.spells["Вирус"].cd_ms, 0)
        self.assertFalse(cat.spells["Вирус"].nogcd)
        self.assertEqual(cat.slots[4].key, "alt+1")
        self.assertEqual(cat.resource, ("blood", 5))

    def test_prefixed_lines_are_accepted(self):
        lines = [PFX + x for x in dump(1, SLOT)]
        self.assertEqual(latest(lines).gen, 1)

    def test_passives_and_talents(self):
        cat = latest(dump(1, ("PASSIVE", {"name": "П", "desc": "д"}),
                          ("TALENT", {"field": "1", "row": "2", "col": "3", "rank": "1",
                                      "name": "Т", "desc": "о", "src": "raw"})))
        self.assertEqual((cat.passives[0].name, cat.passives[0].desc), ("П", "д"))
        t = cat.talents[0]
        self.assertEqual((t.field, t.row, t.col, t.rank, t.name, t.src), (1, 2, 3, 1, "Т", "raw"))

    def test_cut_dump_is_ignored_and_previous_used(self):
        lines = dump(1, SLOT) + dump(2, SLOT)[:-1]
        self.assertEqual(latest(lines).gen, 1)

    def test_cut_dump_followed_by_new_begin(self):
        lines = dump(1, SLOT)[:-1] + dump(2, SLOT)
        self.assertEqual([c.gen for c in parse_dumps(lines)], [2])

    def test_count_mismatch_is_ignored(self):
        lines = dump(1, SLOT) + dump(2, SLOT, SPELL, count=1)
        self.assertEqual(latest(lines).gen, 1)

    def test_same_gen_from_older_session_loses_to_newer(self):
        lines = dump(1, SLOT, session="100") + dump(1, SLOT, session="200")
        self.assertEqual(latest(lines, gen=1).session, "200")
        self.assertEqual(latest(lines).session, "200")

    def test_latest_with_gen_and_none(self):
        lines = dump(1, SLOT) + dump(2, SLOT)
        self.assertEqual(latest(lines, gen=1).gen, 1)
        self.assertIsNone(latest(lines, gen=9))
        self.assertIsNone(latest([]))

    def test_unrelated_lines_ignored(self):
        lines = ["шум"] + dump(1, SLOT)[:1] + ["другое"] + dump(1, SLOT)[1:]
        self.assertEqual(latest(lines).gen, 1)

    def test_escaping_round_trip(self):
        desc = "a\tb\nc\\d\re"
        cat = latest(dump(1, ("SPELL", {"name": "X", "desc": desc})))
        self.assertEqual(cat.spells["X"].desc, desc)

    def test_game_key_names(self):
        self.assertEqual(game_key("1"), "1")
        self.assertEqual(game_key("ALT+-"), "alt+-")
        self.assertEqual(game_key("CTRL+="), "ctrl+=")
        self.assertEqual(game_key("NUM_ENTER"), "numenter")
        self.assertEqual(game_key("PG_UP"), "pageup")
        self.assertEqual(game_key("PG_DOWN"), "pagedown")
        self.assertEqual(game_key("NUM_5"), "num5")
        self.assertIsNone(game_key(""))
        self.assertIsNone(game_key("+ANY+MW"))

    def test_keys_from_user_cfg(self):
        keys = keys_from_user_cfg(USER_CFG)
        self.assertEqual(keys[13], "ALT+1")
        self.assertEqual(keys[1], "1")

    def test_json_round_trip(self):
        cat = latest(dump(3, SPELL, SLOT, ("PASSIVE", {"name": "П", "desc": "д"}),
                          ("RES", {"name": "blood", "max": "5"})))
        self.assertEqual(Catalog.from_json(cat.to_json()), cat)


if __name__ == "__main__":
    unittest.main()
