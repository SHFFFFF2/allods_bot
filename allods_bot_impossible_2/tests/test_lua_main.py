"""Дымовой тест Main.lua: заглушки виджетов + строгие глобалы, как в клиенте."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from aobot import protocol

ROOT = Path(__file__).resolve().parent.parent
LUAJIT = ROOT / "tools" / "luajit" / "luajit.exe"
SCRIPTS = ROOT / "addon" / "BotBridge" / "Scripts"
ORDER = ["Config.lua", "Packer.lua", "Collect.lua", "Catalog.lua", "Main.lua"]

# Config.lua из плана 1 (с BOT_SPELLS): установщик оставляет его в игре.
OLD_CONFIG = """
Global( "BOT_SPELLS", {
	"Атака",           -- 1
	"Вампиризм",       -- 2
	"Алчные тени",     -- 3
	"Страж",           -- 4
	"Яростная атака",  -- 5
} )
Global( "BOT_CELL_PX", 4 )
Global( "BOT_TICK_MS", 50 )
Global( "BOT_DEBUG_GCD", false )
"""

# Персонаж в игре: книга из одного умения, оно же в слоте 1.
IN_GAME = r"""
rawset(_G, "ACTION_TYPE_SPELL", 1)
avatar.IsExist = function() return true end
avatar.GetId = function() return 1 end
avatar.GetSpellBook = function() return { 201 } end
avatar.GetActionInfo = function(i) if i == 0 then return { type = 1, id = 30573 } end end
spellLib.GetObjectSpell = function(id) if id == 30573 then return 201 end end
spellLib.GetDescription = function(id) return { name = "Вирус", sysName = "v", description = "д" } end
spellLib.GetCooldown = function(id)
  if id ~= 201 then error("Param 1 has unexpected type: [number]") end
  return { remainingMs = 0 }
end
object.IsDead = function() return false end
"""

COUNT_DUMPS = r"""
local n = 0
for _, l in ipairs(LOG) do if l:find('^BOTCAT\t%d+\tBEGIN') then n = n + 1 end end
"""
TIMER = "\nHANDLERS['EVENT_SECOND_TIMER']({})\n"
TICK = "\nHANDLERS['EVENT_EFFECT_FINISHED']({ wtOwner = CHILDREN[1], effectType = ET_FADE })\n"

HARNESS = r"""
LOG = {}
HANDLERS = {}
EFFECTS = 0
local function mkWidget(name)
  local w = { name = name, color = nil, placement = {}, shown = true }
  function w:GetWidgetDesc() return { tpl = name } end
  function w:SetBackgroundColor(c) self.color = c end
  function w:SetPlacementPlain(p) for k, v in pairs(p) do self.placement[k] = v end end
  function w:PlayFadeEffect(a, b, ms, algo, needEvent) EFFECTS = EFFECTS + 1; self.lastEffect = { a, b, ms, needEvent } end
  function w:Show(v) self.shown = v end
  function w:IsValid() return true end
  function w:IsEqual(o) return self == o end
  return w
end
CHILDREN = {}
FORM = mkWidget("form")
function FORM:GetChildChecked(n) CHILDREN[1] = CHILDREN[1] or mkWidget(n); return CHILDREN[1] end
function FORM:CreateChildByDesc(d) local w = mkWidget(d.tpl); CHILDREN[#CHILDREN + 1] = w; return w end
common = {
  GetAddonName = function() return "BotBridge" end,
  GetAddonSysName = function() return "BotBridge_sys" end,
  GetAddonMainForm = function(n) return FORM end,
  RegisterEventHandler = function(f, ev) HANDLERS[ev] = f end,
  LogInfo = function(filter, ...) LOG[#LOG + 1] = table.concat({...}, "") end,
  GetPosConverterParams = function()
    return { fullVirtualSizeX = 1920, realSizeX = 1280, fullVirtualSizeY = 1080, realSizeY = 720 }
  end,
}
userMods = { FromWString = function(w) return w end }
avatar = { IsExist = function() return false end, GetSpellBook = function() return {} end }
object, unit, spellLib = {}, {}, {}
EA_MONOTONOUS_INCREASE = 1
ET_FADE = 2
Global = function(n, v) rawset(_G, n, v) end
setmetatable(_G, {
  __newindex = function(_, k) error("неявный глобал: " .. tostring(k), 2) end,
  __index = function(_, k) error("нет глобала: " .. tostring(k), 2) end,
})
"""


def run(after="", config=None):
    loads = "".join(config + "\n" if config is not None and n == "Config.lua"
                    else f"dofile([[{SCRIPTS / n}]])\n" for n in ORDER)
    code = HARNESS + loads + after
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
    return res.stdout


def color_of(i):
    return (f"local c = CHILDREN[{i}].color\n"
            "io.write(math.floor(c.r*255+0.5), ',', math.floor(c.g*255+0.5), ',', math.floor(c.b*255+0.5))\n")


@unittest.skipUnless(LUAJIT.exists(), "нет tools/luajit/luajit.exe")
class MainScript(unittest.TestCase):
    def test_loads_under_strict_globals_and_builds_all_cells(self):
        self.assertEqual(run("io.write(#CHILDREN)"), str(protocol.CELL_COUNT))

    def test_first_cells_show_sync_and_calib(self):
        self.assertEqual(run(color_of(1)), ",".join(map(str, protocol.SYNC)))
        self.assertEqual(run(color_of(2)), ",".join(map(str, protocol.CALIB)))

    def test_cells_are_sized_in_real_pixels(self):
        # 4 реальных пикселя при масштабе 1920/1280 = 6 виртуальных
        out = run("local p = CHILDREN[3].placement\n"
                  "io.write(p.sizeX, ',', p.posX, ',', p.posY)")
        self.assertEqual(out, "6,12,0")

    def test_ticker_restarts_effect_and_bumps_seq(self):
        out = run(
            "local before = EFFECTS\n"
            "HANDLERS['EVENT_EFFECT_FINISHED']({ wtOwner = CHILDREN[1], effectType = ET_FADE })\n"
            "HANDLERS['EVENT_EFFECT_FINISHED']({ wtOwner = CHILDREN[1], effectType = ET_FADE })\n"
            "io.write(EFFECTS - before)")
        self.assertEqual(out, "2")

    def test_painted_payload_decodes(self):
        out = run(
            "HANDLERS['EVENT_EFFECT_FINISHED']({ wtOwner = CHILDREN[1], effectType = ET_FADE })\n"
            "for i = 1, #CHILDREN do local c = CHILDREN[i].color\n"
            "  io.write(math.floor(c.r*255+0.5), ' ', math.floor(c.g*255+0.5), ' ', math.floor(c.b*255+0.5), ' ') end")
        vals = list(map(int, out.split()))
        cells = [tuple(vals[i:i + 3]) for i in range(0, len(vals), 3)]
        st = protocol.decode_cells(cells)
        self.assertFalse(st.avatar_exists)
        self.assertGreater(st.seq, 0)

    def test_cast_flag_expires_by_second_timer(self):
        out = run(
            "HANDLERS['EVENT_ACTION_PROGRESS_START']({ duration = 1000 })\n"
            "for i = 1, 3 do HANDLERS['EVENT_SECOND_TIMER']({}) end\n"
            "io.write(tostring(BOT_STATE.casting))")
        self.assertEqual(out, "false")

    def test_casting_events_toggle_flag(self):
        out = run(
            "HANDLERS['EVENT_ACTION_PROGRESS_START']({ duration = 1000 })\n"
            "io.write(tostring(BOT_STATE.casting), ' ')\n"
            "HANDLERS['EVENT_ACTION_PROGRESS_FINISH']({})\n"
            "io.write(tostring(BOT_STATE.casting))")
        self.assertEqual(out, "true false")

    def test_logs_each_target_kind_once(self):
        out = run(
            "avatar.IsExist = function() return true end\n"
            "avatar.GetId = function() return 1 end\n"
            "avatar.GetTarget = function() return 50 end\n"
            "object.IsExist = function() return true end\n"
            "object.GetName = function() return 'Краб' end\n"
            "for i = 1, 3 do HANDLERS['EVENT_EFFECT_FINISHED']({ wtOwner = CHILDREN[1], effectType = ET_FADE }) end\n"
            "local n = 0 for _, l in ipairs(LOG) do if l:find('BotBridge: вид цели ', 1, true) and l:find('Краб', 1, true) then n = n + 1 end end\n"
            "io.write(n)")
        self.assertEqual(out, "1")

    def test_works_with_old_config_lua(self):
        out = run(IN_GAME + TICK * 3 + "HANDLERS['EVENT_AVATAR_CREATED']({})" + TIMER
                  + COUNT_DUMPS + "io.write(n, ' ', BOT_STATE.catalog_gen)", config=OLD_CONFIG)
        self.assertEqual(out, "1 1")

    def test_dump_is_debounced_to_second_timer(self):
        out = run(IN_GAME + "local g0 = BOT_STATE.catalog_gen\n"
                  + "for i = 1, 5 do HANDLERS['EVENT_ACTION_PANEL_CHANGED']({}) end\n"
                  + "do" + COUNT_DUMPS + "io.write(n, ' ') end" + TIMER
                  + "do" + COUNT_DUMPS + "io.write(n, ' ', BOT_STATE.catalog_gen - g0, ' ') end" + TIMER
                  + "do" + COUNT_DUMPS + "io.write(n) end")
        self.assertEqual(out, "0 1 1 1")

    def test_all_change_events_request_a_dump(self):
        for ev in ("EVENT_AVATAR_CREATED", "EVENT_SPELLBOOK_CHANGED", "EVENT_ACTION_PANEL_CHANGED",
                   "EVENT_TALENTS_CHANGED", "EVENT_BINDING_CHANGED"):
            with self.subTest(ev=ev):
                out = run(IN_GAME + f"HANDLERS['{ev}']({{}})" + TIMER + COUNT_DUMPS + "io.write(n)")
                self.assertEqual(out, "1")

    def test_each_dump_logs_one_diag_line(self):
        out = run(IN_GAME + "HANDLERS['EVENT_ACTION_PANEL_CHANGED']({})" + TIMER
                  + "HANDLERS['EVENT_ACTION_PANEL_CHANGED']({})" + TIMER
                  + "local d = 0 for _, l in ipairs(LOG) do if l:find('BotBridge: диаг', 1, true) then d = d + 1 end end\n"
                  "io.write(d)")
        self.assertEqual(out, "2")

    def test_failed_dump_is_retried_next_second(self):
        out = run(IN_GAME + "local orig, failed = BotSlotCache, false\n"
                  "rawset(_G, 'BotSlotCache', function() if not failed then failed = true; error('сбой') end "
                  "return orig() end)\n"
                  "HANDLERS['EVENT_ACTION_PANEL_CHANGED']({})" + TIMER
                  + "do" + COUNT_DUMPS + "io.write(n, ' ') end" + TIMER
                  + "do" + COUNT_DUMPS + "io.write(n) end")
        self.assertEqual(out, "0 1")

    def test_dump_waits_for_avatar(self):
        out = run("HANDLERS['EVENT_SPELLBOOK_CHANGED']({})" + TIMER
                  + "do" + COUNT_DUMPS + "io.write(n, ' ') end\n" + IN_GAME + TIMER
                  + "do" + COUNT_DUMPS + "io.write(n) end")
        self.assertEqual(out, "0 1")

    def test_slots_are_cached_and_feed_the_strip(self):
        out = run(IN_GAME + "HANDLERS['EVENT_ACTION_PANEL_CHANGED']({})" + TIMER + TICK
                  + "io.write(BOT_STATE.slots[1].name, ' ', #BOT_STATE.slots, ' ', "
                  "tostring(BOT_API_ERRORS['spellLib.GetCooldown']), '|')\n"
                  "for i = 1, #CHILDREN do local c = CHILDREN[i].color\n"
                  "  io.write(math.floor(c.r*255+0.5), ' ', math.floor(c.g*255+0.5), ' ', math.floor(c.b*255+0.5), ' ') end")
        head, body = out.split("|", 1)
        self.assertEqual(head, "Вирус 36 nil")
        vals = list(map(int, body.split()))
        st = protocol.decode_cells([tuple(vals[i:i + 3]) for i in range(0, len(vals), 3)])
        self.assertEqual(st.spells_known, 1)
        self.assertEqual(st.spells_ready, 1)


if __name__ == "__main__":
    unittest.main()
