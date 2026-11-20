import unittest

from aobot.actions import Press
from aobot.executor import Executor, Slot
from aobot.protocol import GameState
from aobot.rotation import CombatConfig


class ExecutorTest(unittest.TestCase):
    def test_slot_now_when_no_gcd(self):
        ex = Executor(CombatConfig()); st = GameState(avatar_exists=True, seq=1)
        ex.observe(st, 0.0)
        self.assertEqual(ex.slot(st, 0.0), Slot(at=None, queued=False))

    def test_no_slot_while_gcd_far(self):
        ex = Executor(CombatConfig()); st = GameState(avatar_exists=True, seq=1, gcd_ms=900)
        ex.observe(st, 0.0)
        self.assertIsNone(ex.slot(st, 0.0))

    def test_slot_at_gcd_end_within_lookahead(self):
        ex = Executor(CombatConfig(gcd_lookahead=0.06))
        ex.observe(GameState(avatar_exists=True, seq=1, gcd_ms=900), 0.0)
        st = GameState(avatar_exists=True, seq=2, gcd_ms=40)
        ex.observe(st, 0.86)
        slot = ex.slot(st, 0.86)
        self.assertFalse(slot.queued); self.assertAlmostEqual(slot.at, 0.905)

    def test_waits_for_confirmation_after_commit(self):
        ex = Executor(CombatConfig(confirm_frames=2, confirm_seconds=0.2))
        st = lambda seq: GameState(avatar_exists=True, seq=seq)
        ex.observe(st(1), 0.0); ex.commit("3", 2, ex.slot(st(1), 0.0), 0.0)
        ex.observe(st(2), 0.05); self.assertIsNone(ex.slot(st(2), 0.05))
        ex.observe(st(3), 0.25); self.assertIsNotNone(ex.slot(st(3), 0.25))

    def test_queue_slot_only_after_cast_queue_after(self):
        ex = Executor(CombatConfig(cast_queue_after=0.3))
        st = lambda seq: GameState(avatar_exists=True, seq=seq, casting=True)
        ex.observe(st(1), 0.0); self.assertIsNone(ex.slot(st(1), 0.2))
        ex.observe(st(2), 0.35); self.assertEqual(ex.slot(st(2), 0.35), Slot(at=None, queued=True))

    def test_retry_blocked_until_press_cooldown(self):
        ex = Executor(CombatConfig(press_cooldown=0.35)); st = GameState(avatar_exists=True, seq=1)
        ex.observe(st, 0.0); ex.commit("3", 2, Slot(None, False), 0.0)
        self.assertTrue(ex.retry_blocked("3", 0.1)); self.assertFalse(ex.retry_blocked("3", 0.36))

    def test_queue_blocked_after_three_failed_queued_presses(self):
        ex = Executor(CombatConfig(cast_queue_after=0.0, confirm_frames=1, confirm_seconds=0.0))
        t, seq = 0.0, 0
        for _ in range(3):
            seq += 1; st = GameState(avatar_exists=True, seq=seq, casting=True, spells_ready=0b100)
            ex.observe(st, t); ex.commit("3", 2, ex.slot(st, t), t)
            t += 0.4; seq += 1
            ex.observe(GameState(avatar_exists=True, seq=seq, casting=True, spells_ready=0b100), t)
            t += 0.4
        self.assertTrue(ex.queue_blocked("3", Slot(None, True)))
        self.assertFalse(ex.queue_blocked("3", Slot(None, False)))



def fighting(**over):
    base = dict(avatar_exists=True, hp=100, mana=100, has_target=True, target_attackable=True,
                target_enemy=True, target_hp=80, target_in_melee=True, in_combat=True,
                spells_known=0b111, spells_ready=0b111)
    base.update(over)
    return GameState(**base)


class Tick:
    """Один «ход» бота: наблюдение + попытка нажать умение «3» (индекс 2)."""
    def __init__(self, **cfg):
        self.ex = Executor(CombatConfig(**cfg))

    def __call__(self, now, **state):
        st = fighting(**state)
        self.ex.observe(st, now)
        slot = self.ex.slot(st, now)
        if slot is None or self.ex.retry_blocked("3", now) or self.ex.queue_blocked("3", slot):
            return []
        return [self.ex.commit("3", 2, slot, now)]


class TimingPorted(unittest.TestCase):
    """Тайминг, который раньше проверялся через Brain."""

    def test_waits_while_casting_without_queue(self):
        t = Tick(queue_during_cast=False)
        self.assertEqual(t(0.0, casting=True, seq=1), [])
        self.assertEqual(t(1.0, casting=True, seq=2), [])

    def test_queues_next_spell_during_cast(self):
        t = Tick(cast_queue_after=0.3)
        self.assertEqual(t(0.0, casting=True, seq=1), [])
        self.assertEqual(t(0.2, casting=True, seq=2), [])
        self.assertEqual(t(0.35, casting=True, seq=3), [Press("3")])

    def test_no_queue_during_cast_while_gcd(self):
        t = Tick()
        t(0.0, casting=True, gcd_ms=900, seq=1)
        self.assertEqual(t(0.4, casting=True, gcd_ms=500, seq=2), [])

    def test_learns_spell_that_cannot_be_queued(self):
        t = Tick(cast_queue_after=0.0, confirm_frames=2, confirm_seconds=0.0, press_cooldown=0.35)
        now, seq, presses = 0.0, 0, 0
        for _ in range(40):
            now += 0.05
            seq += 1
            presses += len(t(now, casting=True, seq=seq))
        self.assertIn("3", t.ex.no_queue)
        self.assertEqual(presses, 3)
        # после каста «3» жмётся как обычно
        self.assertEqual(t(now + 1.0, seq=seq + 5), [Press("3")])

    def test_queued_spell_that_starts_gcd_is_kept(self):
        t = Tick(cast_queue_after=0.0, confirm_frames=2, confirm_seconds=0.0)
        self.assertEqual(t(0.0, casting=True, seq=1), [Press("3")])
        t(0.05, casting=True, seq=2, gcd_ms=990)
        t(0.10, casting=True, seq=3, gcd_ms=940)
        self.assertNotIn("3", t.ex.no_queue)
        self.assertEqual(t.ex.queue_fails.get("3"), 0)

    def test_waits_for_server_before_judging_press(self):
        t = Tick(confirm_frames=2, confirm_seconds=0.2)
        self.assertEqual(t(0.0, seq=1), [Press("3")])
        self.assertEqual(t(0.05, seq=2), [])
        self.assertEqual(t(0.10, seq=3), [])   # кадров хватает, времени нет
        self.assertEqual(t(0.15, seq=4), [])
        self.assertEqual(t(0.40, seq=5), [Press("3")])

    def test_same_key_not_spammed_before_state_updates(self):
        t = Tick()
        t(0.0, seq=1)
        self.assertEqual(t(0.1, seq=1), [])
        self.assertEqual(t(0.5, seq=2), [Press("3")])

    def test_waits_for_global_cooldown(self):
        self.assertEqual(Tick()(0.0, gcd_ms=800, seq=1), [])

    def test_presses_exactly_at_predicted_gcd_end(self):
        t = Tick(gcd_lookahead=0.06, gcd_lead=0.02)
        self.assertEqual(t(0.0, gcd_ms=500, seq=1), [])
        acts = t(0.46, gcd_ms=40, seq=2)
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0].key, "3")
        # самая ранняя оценка: 0.46 + 0.045; минус упреждение 0.02
        self.assertAlmostEqual(acts[0].at, 0.485, places=6)

    def test_earliest_gcd_estimate_wins(self):
        t = Tick(gcd_lead=0.0)
        t(0.0, gcd_ms=500, seq=1)                        # конец ~0.505
        acts = t(0.55, gcd_ms=10, seq=1)                 # тот же кадр, увиденный позже
        self.assertAlmostEqual(acts[0].at, 0.55, places=6)   # прошлое — жмём сразу
        t = Tick(gcd_lead=0.0)
        t(0.40, gcd_ms=100, seq=1)                       # конец ~0.505
        acts = t(0.47, gcd_ms=50, seq=1)                 # оценка 0.525 позднее
        self.assertAlmostEqual(acts[0].at, 0.505, places=6)

    def test_new_gcd_resets_estimate(self):
        t = Tick()
        t(0.0, gcd_ms=30, seq=1)
        self.assertEqual(t(0.5, gcd_ms=1500, seq=5), [])

    def test_second_spell_waits_for_game_to_show_first(self):
        ex = Executor(CombatConfig())
        st1 = fighting(seq=1)
        ex.observe(st1, 0.0)
        ex.commit("3", 2, ex.slot(st1, 0.0), 0.0)
        st2 = fighting(seq=2)   # ГКД ещё не виден
        ex.observe(st2, 0.02)
        self.assertIsNone(ex.slot(st2, 0.02))

    def test_dead_key_is_blocked_so_rotation_can_move_on(self):
        t = Tick(confirm_frames=2, confirm_seconds=0.0)
        self.assertEqual(t(0.0, seq=1), [Press("3")])
        self.assertTrue(t.ex.retry_blocked("3", 0.10))     # выбирающий возьмёт другое умение
        self.assertFalse(t.ex.retry_blocked("3", 0.40))    # потом «3» снова можно

    def test_early_timed_press_is_retried_after_confirm_frames(self):
        t = Tick(confirm_frames=2, confirm_seconds=0.0, gcd_lead=0.02)
        acts = t(0.0, gcd_ms=30, seq=1)
        self.assertEqual(acts[0].key, "3")
        self.assertIsNotNone(acts[0].at)
        self.assertEqual(t(0.05, seq=2), [])
        self.assertEqual(t(0.10, seq=3), [Press("3")])

if __name__ == "__main__":
    unittest.main()
