"""Сверяет Lua-упаковщик аддона с эталоном aobot.protocol.encode_bytes."""
import dataclasses
import subprocess
import unittest
from pathlib import Path

from aobot import protocol
from tests.test_protocol import sample_state

ROOT = Path(__file__).resolve().parent.parent
LUAJIT = ROOT / "tools" / "luajit" / "luajit.exe"
PACKER = ROOT / "addon" / "BotBridge" / "Scripts" / "Packer.lua"


def lua_value(v):
    if v is None:
        return "nil"
    if isinstance(v, bool):
        return "true" if v else "false"
    return repr(v)


def lua_pack(state, omit_false=False):
    fields = ", ".join(f"{k} = {lua_value(v)}"
                       for k, v in dataclasses.asdict(state).items()
                       if v is not None and not (omit_false and v is False))
    code = (
        "Global = function(n, v) _G[n] = v end\n"
        f"dofile([[{PACKER}]])\n"
        f"local out = BotPack({{ {fields} }})\n"
        "io.write(table.concat(out, ','))\n"
    )
    res = subprocess.run([str(LUAJIT), "-e", code], capture_output=True,
                         text=True, timeout=20)
    if res.returncode:
        raise AssertionError(res.stderr)
    return bytes(int(b) for b in res.stdout.split(","))


@unittest.skipUnless(LUAJIT.exists(), "нет tools/luajit/luajit.exe")
class LuaPackerMatchesPython(unittest.TestCase):
    def check(self, st):
        self.assertEqual(lua_pack(st), protocol.encode_bytes(st))

    def test_typical_combat_state(self):
        self.check(sample_state())

    def test_unknowns_and_no_target(self):
        self.check(sample_state(hp=None, target_hp=None, target_distance=None,
                                has_target=False, mana=None))

    def test_negative_coordinates_and_wrapped_direction(self):
        self.check(sample_state(x=-0.05, y=-99999.9, z=-3.0, direction=7.0))

    def test_clamping_of_large_values(self):
        self.check(sample_state(gcd_ms=10**7, target_distance=1e6, seq=300,
                                hp=300, x=1e9))

    def test_missing_flags_count_as_false(self):
        st = sample_state(avatar_exists=True, dead=False, in_combat=False,
                          casting=False, has_target=False, target_dead=False,
                          target_attackable=False, target_is_player=True,
                          target_in_melee=False, target_enemy=False,
                          target_tagged_other=True)
        self.assertEqual(lua_pack(st, omit_false=True), protocol.encode_bytes(st))

    def test_target_identity_matches_python(self):
        self.check(sample_state(target_id=4321, target_kind=777))

    def test_missing_identity_packs_as_zero(self):
        code = ("Global = function(n, v) _G[n] = v end\n"
                f"dofile([[{PACKER}]])\n"
                "local out = BotPack({ seq = 1 })\n"
                "io.write(out[27], ',', out[28], ',', out[29], ',', out[30])\n")
        res = subprocess.run([str(LUAJIT), "-e", code], capture_output=True, text=True, timeout=20)
        self.assertEqual(res.stdout, "0,0,0,0")                   # байты 26–29, в Lua индексы с 1

    def test_lua_cells_start_with_sync_and_calib(self):
        code = ("Global = function(n, v) _G[n] = v end\n"
                f"dofile([[{PACKER}]])\n"
                "io.write(BOT_CELL_COUNT, ';', table.concat(BOT_SYNC, ','), ';',"
                " table.concat(BOT_CALIB, ','))")
        out = subprocess.run([str(LUAJIT), "-e", code], capture_output=True,
                             text=True, timeout=20).stdout
        count, sync, calib = out.split(";")
        self.assertEqual(int(count), protocol.CELL_COUNT)
        self.assertEqual(tuple(map(int, sync.split(","))), protocol.SYNC)
        self.assertEqual(tuple(map(int, calib.split(","))), protocol.CALIB)


if __name__ == "__main__":
    unittest.main()
