import unittest

from aobot.actions import Press
from aobot.assist import KILL_HP, Assist
from aobot.policy import RotationPolicy
from aobot.protocol import GameState
from aobot.rotation import CombatConfig, RotationStep


def state(**over):
    base = dict(avatar_exists=True, hp=100, mana=100, in_combat=False)
    base.update(over)
    return GameState(**base)


def fighting(**over):
    base = dict(has_target=True, target_attackable=True, target_enemy=True,
                target_hp=80, target_distance=3.0, target_in_melee=True,
                in_combat=True, spells_known=0b111, spells_ready=0b111,
                target_id=51)
    base.update(over)
    return state(**base)


ROTATION = [RotationStep(1, "1", self_hp_below=50), RotationStep(3, "3")]


class FakeRecorder:
    def __init__(self):
        self.calls = []

    def begin(self, target_id, target_kind, policy, now):
        self.calls.append(("begin", target_id))

    def step(self, now, st, legal, chosen):
        self.calls.append(("step", list(legal), chosen))

    def set_kind(self, kind):
        self.calls.append(("kind", kind))

    def end(self, now, outcome):
        self.calls.append(("end", outcome))


def make():
    cfg = CombatConfig(rotation=list(ROTATION))
    return Assist(cfg, RotationPolicy(cfg.rotation))


def make_with_recorder():
    cfg = CombatConfig(rotation=list(ROTATION))
    rec = FakeRecorder()
    return Assist(cfg, RotationPolicy(cfg.rotation), rec), rec


class AssistTests(unittest.TestCase):
    def test_kill_hp(self):
        self.assertEqual(KILL_HP, 2)

    def test_idle_until_hotkey(self):
        a = make(); self.assertEqual(a.step(fighting(seq=1), 0.0, False), []); self.assertFalse(a.active)

    def test_hotkey_starts_attack(self):
        a = make(); self.assertEqual(a.step(fighting(seq=1), 0.0, True), [Press("3")]); self.assertTrue(a.active)

    def test_hotkey_without_target_does_nothing(self):
        a = make(); self.assertEqual(a.step(state(seq=1), 0.0, True), []); self.assertEqual(a.status, "нет цели")

    def test_hotkey_while_active_does_not_stop(self):                    # RF 1
        a = make(); a.step(fighting(seq=1), 0.0, True); a.step(fighting(seq=2), 0.5, False)
        a.step(fighting(seq=3), 1.0, True); self.assertTrue(a.active)

    def test_held_hotkey_does_not_restart_after_stop(self):              # RF 1
        a = make(); a.step(fighting(seq=1), 0.0, True)
        a.step(state(seq=2), 0.5, True)                                  # цель пропала, клавиша всё ещё зажата
        a.step(state(seq=3), 1.0, True)                                  # дольше выдержки — бой закрыт
        a.step(fighting(seq=4, target_id=52), 1.2, True); self.assertFalse(a.active)
        a.step(fighting(seq=5, target_id=52), 1.5, False); a.step(fighting(seq=6, target_id=52), 2.0, True)
        self.assertTrue(a.active)

    def test_hotkey_held_from_start_activates_once(self):                # RF 1
        a, rec = make_with_recorder()
        for i in range(5):
            a.step(fighting(seq=i + 1), i * 0.5, True)
        self.assertEqual([c for c in rec.calls if c[0] == "begin"], [("begin", 51)])

    def test_target_change_continues_and_splits_fight(self):
        a, rec = make_with_recorder(); a.step(fighting(seq=1), 0.0, True)
        a.step(fighting(seq=2, target_id=52, target_hp=90), 0.5, False)
        self.assertIn(("end", "switched"), rec.calls); self.assertIn(("begin", 52), rec.calls); self.assertTrue(a.active)

    def test_target_change_after_low_hp_counts_as_kill(self):
        a, rec = make_with_recorder(); a.step(fighting(seq=1, target_hp=2), 0.0, True)
        a.step(fighting(seq=2, target_id=52, target_hp=90), 0.5, False)
        self.assertIn(("end", "kill"), rec.calls)

    def test_target_cleared_after_low_hp_counts_as_kill(self):           # RF 2
        a, rec = make_with_recorder(); a.step(fighting(seq=1, target_hp=1), 0.0, True)
        a.step(state(seq=2), 0.5, False); a.step(state(seq=3), 1.0, False)
        self.assertEqual(rec.calls[-1], ("end", "kill")); self.assertFalse(a.active)

    def test_target_dropped_counts_as_dropped(self):
        a, rec = make_with_recorder(); a.step(fighting(seq=1, target_hp=60), 0.0, True)
        a.step(state(seq=2), 0.5, False); a.step(state(seq=3), 1.0, False)
        self.assertEqual(rec.calls[-1], ("end", "dropped"))

    def test_brief_no_target_on_switch_keeps_fighting(self):
        a, rec = make_with_recorder(); a.step(fighting(seq=1), 0.0, True)
        self.assertEqual(a.step(state(seq=2), 0.5, False), [])         # кадр без цели при смене
        self.assertTrue(a.active)
        a.step(fighting(seq=3, target_id=52), 0.6, False)
        self.assertTrue(a.active)
        self.assertIn(("begin", 52), rec.calls)
        self.assertIn(("end", "switched"), rec.calls)
        self.assertNotIn(("end", "dropped"), rec.calls)

    def test_dead_target_selected_counts_as_kill(self):
        a, rec = make_with_recorder(); a.step(fighting(seq=1, target_hp=40), 0.0, True)
        a.step(fighting(seq=2, target_dead=True, target_hp=0), 0.5, False)
        a.step(fighting(seq=3, target_dead=True, target_hp=0), 0.75, False); self.assertEqual(rec.calls[-1], ("end", "kill"))

    def test_one_frame_dead_flag_does_not_stop(self):
        a, rec = make_with_recorder(); a.step(fighting(seq=1, target_hp=40), 0.0, True)
        self.assertEqual(a.step(fighting(seq=2, target_dead=True, target_hp=16), 0.5, False), [])
        a.step(fighting(seq=3, target_hp=16), 0.55, False)
        self.assertTrue(a.active)
        self.assertNotIn(("end", "kill"), rec.calls)

    def test_death_ends_fight(self):
        a, rec = make_with_recorder(); a.step(fighting(seq=1), 0.0, True)
        a.step(fighting(seq=2, dead=True), 0.5, False); self.assertEqual(rec.calls[-1], ("end", "death")); self.assertFalse(a.active)

    def test_gap_in_data_keeps_fight(self):                              # RF 3
        a, rec = make_with_recorder(); a.step(fighting(seq=1), 0.0, True)
        self.assertEqual(a.step(fighting(seq=9), 5.0, False), [Press("3")])
        self.assertNotIn("end", [c[0] for c in rec.calls])

    def test_chat_stops_bot(self):                                       # RF 4
        a, rec = make_with_recorder(); a.step(fighting(seq=1), 0.0, True)
        self.assertEqual(a.step(fighting(seq=2), 0.5, False, typing=True), [])
        self.assertFalse(a.active); self.assertEqual(rec.calls[-1], ("end", "stopped"))
        self.assertEqual(a.status, "чат — бот выключен")

    def test_chat_stops_before_decision(self):                           # RF 4
        a, rec = make_with_recorder(); a.step(fighting(seq=1), 0.0, True)
        n = len(rec.calls)
        a.step(fighting(seq=2), 5.0, False, typing=True)
        self.assertEqual(rec.calls[n:], [("end", "stopped")])

    def test_no_known_spells_status(self):
        a = make(); a.step(fighting(seq=1, spells_known=0, spells_ready=0), 0.0, True)
        self.assertEqual(a.status, "умения не найдены")

    def test_stop_closes_open_fight(self):
        a, rec = make_with_recorder(); a.step(fighting(seq=1), 0.0, True); a.stop(1.0)
        self.assertEqual(rec.calls[-1], ("end", "stopped"))

    def test_stop_without_fight_records_nothing(self):
        a, rec = make_with_recorder(); a.stop(1.0)
        self.assertEqual(rec.calls, [])

    def test_records_decision_with_legal_and_choice(self):
        a, rec = make_with_recorder(); a.step(fighting(seq=1, spells_ready=0b100), 0.0, True)
        self.assertIn(("step", ["3"], "3"), rec.calls)

    def test_repeated_polls_record_one_step(self):
        a, rec = make_with_recorder()
        a.step(fighting(seq=1, spells_ready=0), 0.0, True)
        for i in range(1, 6):
            a.step(fighting(seq=1, spells_ready=0), i * 0.005, False)
        self.assertEqual([c for c in rec.calls if c[0] == "step"], [("step", [], None)])
        a.step(fighting(seq=2, spells_ready=0), 0.1, False)
        self.assertEqual(len([c for c in rec.calls if c[0] == "step"]), 2)

    def test_dedupe_memory_reset_on_new_fight(self):
        a, rec = make_with_recorder()
        a.step(fighting(seq=1, spells_ready=0), 0.0, True)
        a.step(fighting(seq=1, spells_ready=0, target_id=52), 0.1, False)
        self.assertEqual(len([c for c in rec.calls if c[0] == "step"]), 2)

    def test_corpse_switch_mid_fight_is_switched(self):
        a, rec = make_with_recorder(); a.step(fighting(seq=1, target_hp=60), 0.0, True)
        a.step(fighting(seq=2, target_id=52, target_dead=True, target_hp=0), 0.5, False)
        a.step(fighting(seq=3, target_id=52, target_dead=True, target_hp=0), 0.75, False)
        self.assertEqual(rec.calls[-1], ("end", "switched")); self.assertFalse(a.active)
        self.assertEqual([c for c in rec.calls if c[0] == "begin"], [("begin", 51)])

    def test_corpse_switch_at_low_hp_is_kill(self):
        a, rec = make_with_recorder(); a.step(fighting(seq=1, target_hp=1), 0.0, True)
        a.step(fighting(seq=2, target_id=52, target_dead=True, target_hp=0), 0.5, False)
        a.step(fighting(seq=3, target_id=52, target_dead=True, target_hp=0), 0.75, False)
        self.assertEqual(rec.calls[-1], ("end", "kill")); self.assertFalse(a.active)

    def test_kind_refreshed_when_first_frame_had_none(self):
        a, rec = make_with_recorder(); a.step(fighting(seq=1, target_kind=0), 0.0, True)
        a.step(fighting(seq=2, target_kind=7), 0.5, False)
        a.step(fighting(seq=3, target_kind=7), 1.0, False)
        self.assertEqual([c for c in rec.calls if c[0] == "kind"], [("kind", 7)])

    def test_kind_not_touched_when_known_at_start(self):
        a, rec = make_with_recorder(); a.step(fighting(seq=1, target_kind=5), 0.0, True)
        a.step(fighting(seq=2, target_kind=5), 0.5, False)
        self.assertEqual([c for c in rec.calls if c[0] == "kind"], [])


if __name__ == "__main__":
    unittest.main()
