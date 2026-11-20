import unittest

from aobot.executor import Executor, Slot
from aobot.policy import RotationPolicy, legal_steps
from aobot.protocol import GameState
from aobot.rotation import CombatConfig, RotationStep

HEAL = RotationStep(spell=1, key="1", self_hp_below=50)
FINISH = RotationStep(spell=2, key="2", max_target_hp=30)
HIT = RotationStep(spell=3, key="3")
ROT = [HEAL, FINISH, HIT]


def st(**o):
    return GameState(**{**dict(avatar_exists=True, hp=90, has_target=True,
                               target_hp=80, spells_ready=0b111), **o})


class RotationPolicyTests(unittest.TestCase):
    def test_heal_first_when_hp_low(self):
        self.assertIs(RotationPolicy(ROT).choose(st(hp=40), ROT), HEAL)

    def test_attack_when_hp_high(self):
        self.assertIs(RotationPolicy(ROT).choose(st(), ROT), HIT)

    def test_respects_target_hp_window(self):
        self.assertIs(RotationPolicy(ROT).choose(st(target_hp=20), ROT), FINISH)

    def test_nothing_legal_means_wait(self):
        self.assertIsNone(RotationPolicy(ROT).choose(st(), []))

    def test_legal_steps_filters_not_ready_and_retry_blocked(self):
        class Ex:
            def retry_blocked(self, key, now):
                return key == "2"
        self.assertEqual(legal_steps(ROT, st(spells_ready=0b110), Ex(), 0.0), [HIT])

    def test_unconfirmed_press_key_is_skipped_until_cooldown(self):
        rot = [RotationStep(spell=3, key="3"), RotationStep(spell=2, key="2")]
        ex = Executor(CombatConfig(press_cooldown=0.35))
        ex.commit("3", 2, Slot(None, False), 0.0)   # игра так и не приняла «3»
        pol = RotationPolicy(rot)
        s = st(target_hp=20)
        legal = legal_steps(rot, s, ex, 0.1)
        self.assertEqual([x.key for x in legal], ["2"])
        self.assertEqual(pol.choose(s, legal).key, "2")
        legal = legal_steps(rot, s, ex, 0.4)
        self.assertEqual([x.key for x in legal], ["3", "2"])
        self.assertEqual(pol.choose(s, legal).key, "3")

    def test_every_skips_step_after_accepted_press(self):
        dot = RotationStep(spell=3, key="3", every=8.0)
        rot = [dot, RotationStep(spell=2, key="2")]
        ex = Executor(CombatConfig())
        ex.commit("3", 2, Slot(None, False), 0.0)
        ex.observe(st(seq=1, gcd_ms=900), 0.05)      # начался ГКД — игра приняла «3»
        self.assertEqual(ex.used_at["3"], 0.0)
        self.assertEqual([x.key for x in legal_steps(rot, st(), ex, 5.0)], ["2"])
        self.assertEqual([x.key for x in legal_steps(rot, st(), ex, 8.0)], ["3", "2"])

    def test_every_not_counted_when_press_not_accepted(self):
        rot = [RotationStep(spell=3, key="3", every=8.0)]
        ex = Executor(CombatConfig(press_cooldown=0.35))
        ex.commit("3", 2, Slot(None, False), 0.0)   # ГКД так и не начался
        self.assertNotIn("3", ex.used_at)
        self.assertEqual([x.key for x in legal_steps(rot, st(), ex, 0.4)], ["3"])


if __name__ == "__main__":
    unittest.main()
