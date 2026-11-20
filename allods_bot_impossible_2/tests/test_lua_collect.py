"""Сборщик состояния аддона (Collect.lua) на заглушках игрового API."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from aobot import protocol

ROOT = Path(__file__).resolve().parent.parent
LUAJIT = ROOT / "tools" / "luajit" / "luajit.exe"
COLLECT = ROOT / "addon" / "BotBridge" / "Scripts" / "Collect.lua"

# Заглушки API. ME = 1, моб = 50. Поведение настраивается таблицей W.
FAKE_API = r"""
Global = function(n, v) _G[n] = v end
W = { exists = true, target = 50, targetExists = true, tagged = false,
      taggedByMe = false, gcd = 400, brokenMana = false }
avatar = {
  IsExist = function() return W.exists end,
  GetId = function() return 1 end,
  GetPos = function() return { posX = 10.5, posY = -20.25, posZ = 3 } end,
  GetDir = function() return 1.25 end,
  GetGlobalCooldown = function() return { durationMs = 1500, remainingMs = W.gcd } end,
  GetTarget = function() return W.target end,
  IsTargetInMeleeRange = function() return true end,
  GetSpellBook = function() return { 101, 102, 103 } end,
}
object = {
  IsExist = function(id) return id ~= 50 or W.targetExists end,
  IsDead = function(id) return false end,
  IsInCombat = function(id) return id == 1 end,
  GetHealthInfo = function(id)
    if id == 1 then return { valuePercents = 77 } end
    return { valuePercents = 35 }
  end,
  CanAttack = function(id) return id == 50 end,
  IsEnemy = function(id) return id == 50 end,
  GetDistance = function(id) return 4.5 end,
}
unit = {
  GetManaPercentage = function(id)
    if W.brokenMana then error("no such function") end
    return 60
  end,
  IsPlayer = function(id) return false end,
  IsTagged = function(id) return W.tagged end,
  IsTaggedByMainPlayer = function(id) return W.taggedByMe end,
}
local CD = { [101] = 0, [102] = 400, [103] = 5000 }
local NAMES = { [101] = { "Удар", "spellStrike" }, [102] = { "Рывок", "spellCharge" },
                [103] = { "Щит", "spellShield" } }
spellLib = {
  GetCooldown = function(id) return { remainingMs = CD[id], durationMs = 1 } end,
  CanRunAvatar = function(id) return true end,
  GetDescription = function(id)
    return { name = { w = NAMES[id][1] }, sysName = NAMES[id][2] }
  end,
}
userMods = { FromWString = function(w) return w.w end }
"""

DUMP = r"""
local keys = {}
for k in pairs(st) do keys[#keys + 1] = k end
table.sort(keys)
for _, k in ipairs(keys) do io.write(k, '=', tostring(st[k]), '\n') end
"""


def run(setup="", call="st = BotCollect(5, false, BOT_IDS)"):
    code = (FAKE_API + f"dofile([[{COLLECT}]])\n" + setup + "\n"
            + "BOT_IDS = BotResolveSpells({ 'Удар', 'spellCharge', 'Щит', 'Нет такого' })\n"
            + call + "\n" + DUMP)
    # через файл: кириллица в аргументах командной строки до LuaJIT не доходит
    with tempfile.NamedTemporaryFile("w", suffix=".lua", encoding="utf-8",
                                     delete=False) as f:
        f.write(code)
    try:
        res = subprocess.run([str(LUAJIT), f.name], capture_output=True,
                             timeout=20, encoding="utf-8")
    finally:
        os.unlink(f.name)
    if res.returncode:
        raise AssertionError(res.stderr)
    return dict(line.split("=", 1) for line in res.stdout.splitlines())


@unittest.skipUnless(LUAJIT.exists(), "нет tools/luajit/luajit.exe")
class Collect(unittest.TestCase):
    def test_avatar_fields(self):
        st = run()
        self.assertEqual(st["avatar_exists"], "true")
        self.assertEqual(st["hp"], "77")
        self.assertEqual(st["mana"], "60")
        self.assertEqual(st["in_combat"], "true")
        self.assertEqual((st["x"], st["y"], st["z"]), ("10.5", "-20.25", "3"))
        self.assertEqual(st["direction"], "1.25")
        self.assertEqual(st["gcd_ms"], "400")
        self.assertEqual(st["seq"], "5")

    def test_gcd_from_event_when_api_is_silent(self):
        st = run(setup=("W.gcd = 0; T = 1000; common = { GetAbsTimeMs = function() return T end }; "
                        "BotOnGlobalCooldown({ effect = 1, remaining = 700, duration = 1500 }); "
                        "T = 1200"))
        self.assertEqual(st["gcd_ms"], "500")

    def test_gcd_event_finished_clears(self):
        st = run(setup=("W.gcd = 0; EFFECT_TYPE_COOLDOWN_FINISHED = 2; "
                        "common = { GetAbsTimeMs = function() return 1000 end }; "
                        "BotOnGlobalCooldown({ effect = 1, remaining = 700 }); "
                        "BotOnGlobalCooldown({ effect = 2 })"))
        self.assertEqual(st["gcd_ms"], "0")

    def test_target_fields(self):
        st = run()
        self.assertEqual(st["has_target"], "true")
        self.assertEqual(st["target_hp"], "35")
        self.assertEqual(st["target_attackable"], "true")
        self.assertEqual(st["target_enemy"], "true")
        self.assertEqual(st["target_in_melee"], "true")
        self.assertEqual(st["target_distance"], "4.5")
        self.assertEqual(st["target_tagged_other"], "false")

    def test_target_tagged_by_someone_else(self):
        st = run("W.tagged = true")
        self.assertEqual(st["target_tagged_other"], "true")

    def test_own_tag_is_not_foreign(self):
        st = run("W.tagged = true; W.taggedByMe = true")
        self.assertEqual(st["target_tagged_other"], "false")

    def test_no_target(self):
        st = run("W.target = nil")
        self.assertNotIn("has_target", {k for k, v in st.items() if v == "true"})
        self.assertNotIn("target_hp", st)

    def test_vanished_target_counts_as_none(self):
        st = run("W.targetExists = false")
        self.assertNotEqual(st.get("has_target"), "true")

    def test_spell_masks(self):
        # 'Удар' кд 0 -> готов; 'spellCharge' кд 400 = ГКД -> готов;
        # 'Щит' кд 5000 -> не готов; 4-го умения нет в книге
        st = run()
        self.assertEqual(st["spells_known"], str(0b0111))
        self.assertEqual(st["spells_ready"], str(0b0011))

    def test_broken_api_call_does_not_break_collection(self):
        st = run("W.brokenMana = true")
        self.assertNotIn("mana", st)
        self.assertEqual(st["hp"], "77")

    def test_mana_falls_back_to_object_mana_info(self):
        st = run("unit.GetManaPercentage = nil\n"
                 "object.GetManaInfo = function(id) return { valuePercents = 55 } end")
        self.assertEqual(st["mana"], "55")

    def test_no_avatar_yet(self):
        st = run("W.exists = false")
        self.assertNotEqual(st.get("avatar_exists"), "true")
        self.assertEqual(st["seq"], "5")

    def test_target_identity(self):
        st = run("object.GetName = function(id) return { w = 'Береговой краб' } end")
        self.assertEqual(st["target_id"], "51")                  # 50 % 65535 + 1
        self.assertEqual(st["target_kind"], str(protocol.kind_hash("Береговой краб".encode("utf-8"))))

    def test_no_target_has_no_identity(self):
        st = run("W.target = nil")
        self.assertNotIn("target_id", st)

    def test_casting_flag_passed_through(self):
        st = run(call="st = BotCollect(1, true, BOT_IDS)")
        self.assertEqual(st["casting"], "true")


if __name__ == "__main__":
    unittest.main()
