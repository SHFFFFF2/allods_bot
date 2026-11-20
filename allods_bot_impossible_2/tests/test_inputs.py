import unittest

from aobot.inputs import Backend, InputError, PS2Backend


class Recorder(Backend):
    def __init__(self):
        self.log = []

    def down(self, key):
        self.log.append(("down", key))

    def up(self, key):
        self.log.append(("up", key))


class Inputs(unittest.TestCase):
    def test_combo_released_in_reverse_order(self):
        r = Recorder()
        r.press("ctrl+1", hold=0)
        self.assertEqual(r.log, [("down", "ctrl"), ("down", "1"), ("up", "1"), ("up", "ctrl")])


def fake_ps2(packet=3):
    """PS2Backend без драйвера: записывает байты, ушедшие во вспомогательный порт."""
    b = PS2Backend.__new__(PS2Backend)
    b.mouse_packet, b._buttons, b._held, b._h = packet, 0, set(), None
    b.allow_mouse = True
    b.sent = []
    b._byte = lambda value, cmd=0xD2: b.sent.append((cmd, value))
    return b


class Mouse(unittest.TestCase):
    def test_ps2_move_packet(self):
        b = fake_ps2()
        b.move(5, 3)    # вправо и вниз на экране = вниз у PS/2 (отрицательный dy)
        self.assertEqual(b.sent, [(0xD3, 0x08 | 0x20), (0xD3, 5), (0xD3, (-3) & 0xFF)])

    def test_ps2_large_move_is_split(self):
        b = fake_ps2()
        b.move(-600, 0)
        dxs = [b.sent[i + 1][1] for i in range(0, len(b.sent), 3)]
        self.assertEqual(dxs, [(-255) & 0xFF, (-255) & 0xFF, (-90) & 0xFF])

    def test_ps2_click_keeps_button_bits(self):
        b = fake_ps2(packet=4)
        b.mouse_down("right")
        b.move(1, 0)
        b.mouse_up("right")
        firsts = [b.sent[i][1] for i in range(0, len(b.sent), 4)]
        self.assertEqual(firsts, [0x0A, 0x0A, 0x08])
        self.assertEqual(len(b.sent), 12)

    def test_ps2_mouse_off_unless_asked(self):
        b = fake_ps2()
        b.allow_mouse = False
        with self.assertRaises(InputError):
            b.move(1, 0)

    def test_unknown_button(self):
        with self.assertRaises(InputError):
            fake_ps2().mouse_down("x1")

    def test_sendinput_has_mouse(self):
        from aobot.inputs import SendInputMouse
        self.assertIsNot(SendInputMouse.move, Backend.move)

    def test_sendinput_mouse_has_no_keys(self):
        from aobot.inputs import SendInputMouse
        with self.assertRaises(InputError):
            SendInputMouse.__new__(SendInputMouse).down("1")


class Split(unittest.TestCase):
    def test_keys_and_mouse_go_to_their_backends(self):
        from aobot.inputs import SplitBackend
        kb, ms = Recorder(), Recorder()
        ms.move = lambda dx, dy: ms.log.append(("move", dx, dy))
        b = SplitBackend(kb, ms)
        b.press("1", hold=0)
        b.move(3, 4)
        self.assertEqual(kb.log, [("down", "1"), ("up", "1")])
        self.assertEqual(ms.log, [("move", 3, 4)])

    def test_unknown_mouse_is_an_error(self):
        from aobot.inputs import make_backend
        with self.assertRaises(InputError):
            make_backend(mouse="arduino")


if __name__ == "__main__":
    unittest.main()
