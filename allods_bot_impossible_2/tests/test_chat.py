import unittest

from aobot.chat import ChatGuard


def guard():
    return ChatGuard(open_keys=["enter", "backspace"], close_keys=["enter", "esc"])


class ChatGuardTests(unittest.TestCase):
    def test_closed_at_start(self):
        self.assertFalse(guard().update(set()))

    def test_enter_opens_and_stays_open_after_release(self):
        g = guard()
        self.assertTrue(g.update({"enter"}))
        self.assertTrue(g.update(set()))
        self.assertTrue(g.update(set()))

    def test_second_enter_closes(self):
        g = guard()
        g.update({"enter"})
        g.update(set())
        g.update({"enter"})           # отправили сообщение
        self.assertFalse(g.update(set()))

    def test_held_enter_does_not_toggle_again(self):
        g = guard()
        for _ in range(5):
            self.assertTrue(g.update({"enter"}))
        self.assertTrue(g.update(set()))

    def test_esc_closes(self):
        g = guard()
        g.update({"backspace"})
        g.update(set())
        g.update({"esc"})
        self.assertFalse(g.update(set()))

    def test_backspace_inside_chat_keeps_it_open(self):
        g = guard()
        g.update({"enter"})
        g.update(set())
        g.update({"backspace"})       # стёрли букву
        self.assertTrue(g.update(set()))

    def test_esc_when_closed_changes_nothing(self):
        g = guard()
        g.update({"esc"})
        self.assertFalse(g.update(set()))

    def test_typing_letters_keeps_open(self):
        g = guard()
        g.update({"enter"})
        g.update({"e"})
        self.assertTrue(g.update(set()))

    def test_reset_closes(self):
        g = guard()
        g.update({"enter"})
        g.reset()
        self.assertFalse(g.update(set()))

    def test_keys_lists(self):
        self.assertEqual(sorted(guard().keys), ["backspace", "enter", "esc"])


if __name__ == "__main__":
    unittest.main()
