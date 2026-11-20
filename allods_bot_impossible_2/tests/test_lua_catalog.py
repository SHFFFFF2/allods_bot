"""Выгрузка каталога (Catalog.lua) на заглушках игрового API; вывод разбирает aobot.catalog."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from aobot import catalog

ROOT = Path(__file__).resolve().parent.parent
LUAJIT = ROOT / "tools" / "luajit" / "luajit.exe"
SCRIPTS = ROOT / "addon" / "BotBridge" / "Scripts"

# Книга: 201 «Вирус», 202 «Дыхание смерти» (без ГКД), 203 «Атака».
# Слоты (0-based): 0 -> Вирус, 12 -> Дыхание смерти, 5 -> предмет, остальные пусты.
FAKE_API = r"""
Global = function(n, v) rawset(_G, n, v) end
ACTION_TYPE_SPELL, ACTION_TYPE_ITEM, ACTION_TYPE_MOUNT, ACTION_TYPE_EMOTE = 1, 2, 3, 4
common = { GetAbsTimeMs = function() return 12345 end,
           IsValuedText = function(v) return type(v) == "table" and v.vt ~= nil end }
userMods = { FromWString = function(w) if type(w) == "table" then return w.w end return w end,
             FromValuedText = function(v) return v.vt end }
local SPELLS = {
  [201] = { name = { w = "Вирус" }, sysName = "spellVirus",
            description = { vt = "…каждую секунду\nв течение 9 сек." } },
  [202] = { name = { w = "Дыхание смерти" }, sysName = "spellBreath", description = { w = "Наносит 80.95 ед." } },
  [203] = { name = { w = "Атака" }, sysName = "", description = { w = "Удар\tоружием" } },
}
-- в слотах — id объектов умений (action id); SpellId из них даёт GetObjectSpell
ACTION_TO_SPELL = { [30573] = 201, [30574] = 202 }
SLOTS = { [0] = { type = ACTION_TYPE_SPELL, id = 30573 }, [12] = { type = ACTION_TYPE_SPELL, id = 30574 },
          [5] = { type = ACTION_TYPE_ITEM, id = 77 } }
avatar = {
  GetSpellBook = function() return { 201, 202, 203 } end,
  GetActionInfo = function(i) return SLOTS[i] end,
  GetSpellObjectInfo = function(id) if id == 901 then return { name = { w = "Вирус" } } end end,
  GetAbilities = function() return { 501, 502 } end,
  GetAbilityInfo = function(id)
    if id == 501 then return { name = { w = "Жрец тьмы" }, description = { vt = "усиливает на 15%" } } end
    if id == 502 then return { name = { w = "Фонтан крови" }, description = { w = "1 каплю каждые 1 сек." } } end
  end,
  GetNecromancerBloodPool = function() return { value = 2, maxValue = 5 } end,
  GetFieldTalentTableSize = function() return { fieldsCount = 3, rowsCount = 2, columnsCount = 2 } end,
  GetFieldTalentInfo = function(f, r, c)
    if f == 0 and r == 0 and c == 1 then
      return { isLearned = true, currentRank = 3, ranks = {
        { rank = 1, name = { w = "Жрец тьмы" }, desc = { w = '<r name="Damage_Up"/>%' }, abilityId = 501 } } }
    end
    if f == 1 and r == 1 and c == 0 then
      return { isLearned = true, currentRank = 1, ranks = {
        { rank = 1, name = { w = "Пагуба" }, desc = { w = '<t href="ceb6"/>' } } } }
    end
    if f == 2 and r == 0 and c == 0 then
      return { isLearned = false, currentRank = 0, ranks = { { rank = 1, name = { w = "Не изучена" }, desc = { w = "" } } } }
    end
    return nil
  end,
  GetBaseTalentTableSize = function() return 2, 2 end,
  GetBaseTalentInfo = function(la, li)
    if la == 1 and li == 1 then
      return { isLearned = true, currentRank = 2, ranks = {
        { rank = 1, name = { w = "Атака" }, desc = { w = "старый текст" }, spellId = 999 },
        { rank = 2, name = { w = "Атака" }, desc = { w = "сырой" }, spellId = 203 } } }
    end
    return nil
  end,
}
spellLib = {
  GetDescription = function(id)
    -- как клиент: action id вместо SpellId — ошибка типа
    if id >= 900 then error("Param 1 has unexpected type: [number]") end
    return SPELLS[id]
  end,
  GetObjectSpell = function(id) return ACTION_TO_SPELL[id] end,
  GetDescriptionParams = function(id)
    if id == 201 then return { { key = { w = "var0" }, value = 23.1292 }, { key = { w = "txt" }, value = { w = "x" } } } end
    return {}
  end,
  GetCurrentValues = function(id) return { predictedCooldown = 1500.0, prepareDuration = 1333.33, range = 30.5 } end,
  GetProperties = function(id) return { isChanneled = id == 203, isHarmful = true, isHelpFul = false, targetType = 1 } end,
  GetCooldown = function(id) return { remainingMs = 0, ignoreGlobalCooldown = id == 202 } end,
}
local BINDS = { action_01 = { keys = { [0] = { [0] = "1" } } },
                action_13 = { keys = { [0] = { [0] = { w = "ALT" }, [1] = { w = "1" } } } } }
object = {
  GetBuffs = function(id) if id == 1 then return { 71, 72 } end return {} end,
  GetBuffInfo = function(id)
    if id == 71 then return { name = { w = "Капли крови" }, stackCount = 4 } end
    return { name = { w = "Страж" }, stackCount = 1 }
  end,
}
avatar.GetId = function() return 1 end
binding = { GetBind = function(section, name)
  if section ~= "mission_actions" then return nil end
  return BINDS[name]
end }
"""


def run_lua(setup="", call="N = BotCatalogDump(7, function(t) OUT[#OUT + 1] = t end)", tail=""):
    code = (FAKE_API + f"dofile([[{SCRIPTS / 'Collect.lua'}]])\n"
            + f"dofile([[{SCRIPTS / 'Catalog.lua'}]])\n" + setup + "\n"
            + "OUT = {}\n" + call + "\n"
            + "for _, l in ipairs(OUT) do io.write(l, '\\n') end\n" + tail)
    with tempfile.NamedTemporaryFile("w", suffix=".lua", encoding="utf-8", delete=False) as f:
        f.write(code)
    try:
        res = subprocess.run([str(LUAJIT), f.name], capture_output=True, timeout=20, encoding="utf-8")
    finally:
        os.unlink(f.name)
    if res.returncode:
        raise AssertionError(res.stderr)
    return res.stdout.split("\n")


def lua_dump(setup="", gen=7):
    return catalog.latest(run_lua(setup, call=f"N = BotCatalogDump({gen}, function(t) OUT[#OUT + 1] = t end)"))


@unittest.skipUnless(LUAJIT.exists(), "нет tools/luajit/luajit.exe")
class CatalogDump(unittest.TestCase):
    def test_dump_parses_in_python(self):
        cat = lua_dump(gen=7)
        self.assertIsNotNone(cat)
        self.assertEqual(cat.gen, 7)
        self.assertEqual(cat.session, "12345")
        self.assertEqual(cat.slots[1].name, "Вирус")
        self.assertEqual(cat.slots[1].kind, "spell")
        self.assertEqual(cat.slots[1].key, "1")
        self.assertEqual(cat.slots[13].name, "Дыхание смерти")
        self.assertEqual(cat.slots[13].keys, "ALT+1")
        self.assertEqual(cat.slots[13].key, "alt+1")
        self.assertEqual(cat.slots[6].kind, "item")
        self.assertEqual(sorted(cat.slots), [1, 6, 13])
        self.assertTrue(cat.spells["Дыхание смерти"].nogcd)
        self.assertFalse(cat.spells["Вирус"].nogcd)

    def test_slot_spell_id_comes_from_object_spell(self):
        out = run_lua(call="local s = BotSlotCache()\n"
                           "io.write(tostring(s[1].spellId), ' ', tostring(s[13].spellId), ' ', s[1].name, ' ', "
                           "tostring(BOT_API_ERRORS['spellLib.GetDescription']), '\\n')")
        self.assertEqual(out[0], "201 202 Вирус nil")

    def test_no_object_spell_never_passes_action_id_to_spell_lib(self):
        out = run_lua("spellLib.GetObjectSpell = nil",
                      call="local s = BotSlotCache()\n"
                           "io.write(s[1].kind, ' ', tostring(s[1].spellId), ' [', s[1].name, '] ', "
                           "tostring(BOT_API_ERRORS['spellLib.GetDescription']), '\\n')")
        self.assertEqual(out[0], "spell nil [] nil")

    def test_spell_fields(self):
        cat = lua_dump()
        self.assertEqual(sorted(cat.spells), ["Атака", "Вирус", "Дыхание смерти"])
        v = cat.spells["Вирус"]
        self.assertEqual(v.sys, "spellVirus")
        self.assertEqual(v.desc, "…каждую секунду\nв течение 9 сек.")
        self.assertEqual(v.params, {"var0": 23.1292})
        self.assertEqual((v.cd_ms, v.cast_ms, v.range, v.target), (1500, 1333, 30.5, 1))
        self.assertTrue(v.harmful)
        self.assertFalse(v.helpful)
        self.assertFalse(v.channel)
        self.assertTrue(cat.spells["Атака"].channel)
        self.assertEqual(cat.spells["Атака"].desc, "Удар\tоружием")

    def test_passives_and_resource(self):
        cat = lua_dump()
        self.assertEqual([(p.name, p.desc) for p in cat.passives],
                         [("Жрец тьмы", "усиливает на 15%"), ("Фонтан крови", "1 каплю каждые 1 сек.")])
        self.assertEqual(cat.resource, ("blood", 5))

    def test_returns_number_of_lines(self):
        out = run_lua(tail="io.write('N=', N)")
        lines = [l for l in out if l.startswith("BOTCAT")]
        self.assertEqual(out[-1], f"N={len(lines)}")

    def test_spell_object_fallback(self):
        cat = lua_dump("spellLib.GetObjectSpell = nil; "
                       "SLOTS[0] = { type = ACTION_TYPE_SPELL, id = 901 }")
        self.assertEqual(cat.slots[1].name, "Вирус")
        self.assertEqual(cat.slots[1].kind, "spell")
        out = run_lua("spellLib.GetObjectSpell = nil; SLOTS[0] = { type = ACTION_TYPE_SPELL, id = 901 }",
                      call="local s = BotSlotCache(); io.write(#s, ' ', s[1].kind, ' ', tostring(s[1].spellId), "
                           "' ', s[6].kind, ' ', s[2].kind, '\\n')")
        self.assertEqual(out[0], "36 spell 201 item none")

    def test_enum_only_via_global_metatable(self):
        # клиент отдаёт ACTION_TYPE_* через __index окружения, rawget их не видит
        cat = lua_dump(
            "local E = { ACTION_TYPE_SPELL = 1, ACTION_TYPE_ITEM = 2, ACTION_TYPE_MOUNT = 3, ACTION_TYPE_EMOTE = 4 }\n"
            "for k in pairs(E) do rawset(_G, k, nil) end\n"
            "setmetatable(_G, { __index = function(_, k) if E[k] then return E[k] end "
            "error('нет глобала: ' .. tostring(k), 2) end })")
        self.assertEqual((cat.slots[1].kind, cat.slots[1].name), ("spell", "Вирус"))
        self.assertEqual(cat.slots[6].kind, "item")

    def test_unknown_type_with_spell_id_is_spell(self):
        cat = lua_dump("SLOTS[0] = { type = 99, id = 30573 }; SLOTS[2] = { type = 99, id = 777 }")
        self.assertEqual((cat.slots[1].kind, cat.slots[1].name), ("spell", "Вирус"))
        self.assertEqual((cat.slots[3].kind, cat.slots[3].name), ("other", ""))
        cat = lua_dump("spellLib.GetObjectSpell = nil; SLOTS[1] = { type = 99, id = 901 }; "
                       "SLOTS[2] = { type = 99, id = 777 }")
        self.assertEqual((cat.slots[2].kind, cat.slots[2].name), ("spell", "Вирус"))
        self.assertEqual((cat.slots[3].kind, cat.slots[3].name), ("other", ""))
        self.assertEqual(cat.slots[6].kind, "item")

    def test_diag_line(self):
        out = run_lua(call="io.write(BotCatalogDiag(), '\\n')")
        self.assertIn("BotBridge: диаг слот 1 type=1(number) id=30573 SPELL raw=1 idx=1", out[0])
        self.assertIn("кровь value=2 min=nil max=5", out[0])
        self.assertIn("эффекты 2: Капли кровиx4, Стражx1", out[0])
        out = run_lua("avatar.GetActionInfo = function() error('x') end; avatar.GetNecromancerBloodPool = nil",
                      call="io.write(BotCatalogDiag(), '\\n')")
        self.assertIn("слотов нет", out[0])
        self.assertIn("кровь: функции нет", out[0])
        out = run_lua("object = nil", call="io.write(BotCatalogDiag(), '\\n')")
        self.assertIn("эффекты: нет данных", out[0])

    def test_talent_text_prefers_ability(self):
        cat = lua_dump()
        t = [t for t in cat.talents if t.name == "Жрец тьмы"][0]
        self.assertEqual((t.field, t.row, t.col, t.rank), (1, 0, 1, 3))
        self.assertEqual(t.src, "ability")
        self.assertEqual(t.desc, "усиливает на 15%")

    def test_talent_raw_when_no_ids(self):
        cat = lua_dump()
        t = [t for t in cat.talents if t.name == "Пагуба"][0]
        self.assertEqual((t.field, t.row, t.col, t.src), (2, 1, 0, "raw"))
        self.assertEqual(t.desc, '<t href="ceb6"/>')

    def test_base_talent_uses_current_rank_spell(self):
        cat = lua_dump()
        t = [t for t in cat.talents if t.field == 0][0]
        self.assertEqual((t.row, t.col, t.rank, t.name, t.src), (1, 1, 2, "Атака", "spell"))
        self.assertEqual(t.desc, "Удар\tоружием")

    def test_rank_picked_by_rank_field_any_indexing(self):
        ranks0 = ("{ [0] = { rank = 1, name = 'Р1', desc = 'a' }, [1] = { rank = 2, name = 'Р2', desc = 'b' },"
                  " [2] = { rank = 3, name = 'Р3', desc = 'c' } }")
        ranks1 = "{ { rank = 1, name = 'Р1', desc = 'a' }, { rank = 2, name = 'Р2', desc = 'b' }, { rank = 3, name = 'Р3', desc = 'c' } }"
        partial = "{ { rank = 1, name = 'Р1', desc = 'a' }, { rank = 2, name = 'Р2', desc = 'b' } }"
        cases = [(ranks0, 2, "Р2"), (ranks1, 1, "Р1"), (ranks1, 3, "Р3"), (partial, 5, "Р2"),
                 ("{ [0] = { name = 'Б', desc = 'x' }, [1] = { name = 'В', desc = 'y' } }", 1, "В")]
        for ranks, cur, want in cases:
            with self.subTest(ranks=ranks, cur=cur):
                cat = lua_dump("avatar.GetBaseTalentInfo = function(la, li) if la == 0 and li == 0 then "
                               f"return {{ isLearned = true, currentRank = {cur}, ranks = {ranks} }} end end")
                t = [t for t in cat.talents if t.field == 0][0]
                self.assertEqual((t.name, t.rank, t.src), (want, cur, "raw"))

    def test_only_learned_talents(self):
        cat = lua_dump()
        self.assertEqual(len(cat.talents), 3)

    def test_missing_api_does_not_break_dump(self):
        cat = lua_dump("binding = nil; avatar.GetAbilities = nil; spellLib.GetDescriptionParams = nil\n"
                       "avatar.GetFieldTalentTableSize = nil; avatar.GetBaseTalentTableSize = nil")
        self.assertIsNotNone(cat)
        self.assertEqual(cat.slots[1].keys, "")
        self.assertIsNone(cat.slots[1].key)
        self.assertEqual(cat.passives, [])
        self.assertEqual(cat.talents, [])
        self.assertEqual(len(cat.spells), 3)

    def test_broken_api_call_is_recorded(self):
        out = run_lua("spellLib.GetCurrentValues = function() error('сбой') end",
                      tail="io.write('ERR=', tostring(BOT_API_ERRORS['spellLib.GetCurrentValues'] ~= nil))")
        self.assertEqual(out[-1], "ERR=true")
        self.assertEqual(catalog.latest(out).spells["Вирус"].cd_ms, 0)

    def test_no_blood_pool_means_no_res_line(self):
        self.assertIsNone(lua_dump("avatar.GetNecromancerBloodPool = nil").resource)
        self.assertIsNone(lua_dump("avatar.GetNecromancerBloodPool = function() return nil end").resource)


if __name__ == "__main__":
    unittest.main()
