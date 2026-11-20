import unittest

from aobot.protocol import GameState
from aobot.rotation import RotationStep, step_applies


def st(**o):
    return GameState(**{**dict(avatar_exists=True, hp=90, has_target=True,
                               target_hp=80), **o})


class StepApplies(unittest.TestCase):
    def test_attack_applies_by_default(self):
        self.assertTrue(step_applies(RotationStep(spell=3, key="3"), st(), False))

    def test_heal_applies_only_below_threshold(self):
        heal = RotationStep(spell=1, key="1", self_hp_below=50)
        self.assertTrue(step_applies(heal, st(hp=30), True))
        self.assertFalse(step_applies(heal, st(hp=50), True))
        self.assertFalse(step_applies(heal, st(hp=90), True))

    def test_heal_needs_known_hp(self):
        heal = RotationStep(spell=1, key="1", self_hp_below=50)
        self.assertFalse(step_applies(heal, st(hp=None), True))

    def test_heal_not_an_attack_and_vice_versa(self):
        heal = RotationStep(spell=1, key="1", self_hp_below=50)
        hit = RotationStep(spell=3, key="3")
        self.assertFalse(step_applies(heal, st(hp=30), False))
        self.assertFalse(step_applies(hit, st(hp=30), True))

    def test_target_hp_window(self):
        s = RotationStep(spell=2, key="2", min_target_hp=10, max_target_hp=30)
        self.assertTrue(step_applies(s, st(target_hp=20), False))
        self.assertTrue(step_applies(s, st(target_hp=10), False))
        self.assertTrue(step_applies(s, st(target_hp=30), False))
        self.assertFalse(step_applies(s, st(target_hp=31), False))
        self.assertFalse(step_applies(s, st(target_hp=9), False))

    def test_unknown_target_hp_counts_as_full(self):
        finish = RotationStep(spell=2, key="2", max_target_hp=30)
        self.assertFalse(step_applies(finish, st(target_hp=None), False))
        self.assertTrue(step_applies(RotationStep(spell=3, key="3"),
                                     st(target_hp=None), False))

    def test_melee_only_step_waits_for_range(self):
        s = RotationStep(spell=3, key="3", needs_melee=True)
        self.assertFalse(step_applies(s, st(target_in_melee=False), False))
        self.assertTrue(step_applies(s, st(target_in_melee=True), False))


if __name__ == "__main__":
    unittest.main()
