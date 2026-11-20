"""Запуск:

    python -m aobot install [--game "D:\\VK Play\\Аллоды Онлайн"]   — поставить аддон
    python -m aobot diag                                          — показать, что видит бот
    python -m aobot assist [--config config.toml] [--dry]          — режим боя-помощник
    python -m aobot stats [--data DIR] [--game DIR]               — статистика боёв из журнала
    python -m aobot test-input [--key 1] [--mouse]                — проверить, принимает ли игра нажатия

В режиме assist: [assist].key (по умолчанию F9) включает бой по текущей цели,
F12 (stop_key) — выход из программы. Пока открыт чат, горячая клавиша не действует.
Клавиши нажимаются только когда окно игры активно.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import capture, keys
from .actions import Hold, Press
from .assist import Assist
from .chat import ChatGuard
from .journal import FightRecorder
from .policy import RotationPolicy
from .inputs import InputError, make_backend
from .config import ConfigError, load_config
from .install import install_addon
from .protocol import calib_error
from .reader import StateReader
from .stats import format_rows, kind_names, load_fights, summarize

ROOT = Path(__file__).resolve().parent.parent
GAME_GUESSES = [Path(r"D:\VK Play\Аллоды Онлайн"), Path(r"C:\VK Play\Аллоды Онлайн"),
                Path(r"C:\Games\Аллоды Онлайн"), Path(r"D:\Games\Аллоды Онлайн")]


def describe(st) -> str:
    if st is None:
        return "-"
    tgt = "нет цели"
    if st.has_target:
        flags = [f for f, on in (("мертва", st.target_dead), ("атакуема", st.target_attackable),
                                 ("враг", st.target_enemy), ("игрок", st.target_is_player),
                                 ("чужая", st.target_tagged_other),
                                 ("рядом", st.target_in_melee)) if on]
        dist = "?" if st.target_distance is None else f"{st.target_distance:.1f}м"
        tgt = (f"цель #{st.target_id} вид {st.target_kind} "
               f"{st.target_hp}% {dist} [{', '.join(flags)}]")
    me = [f for f, on in (("бой", st.in_combat), ("каст", st.casting), ("мёртв", st.dead)) if on]
    return (f"#{st.seq:3d} HP {st.hp}% MP {st.mana}% {' '.join(me)} | {tgt} | "
            f"ГКД {st.gcd_ms}мс умения найдено {st.spells_known & 0x1F:05b}"
            f"/готово {st.spells_ready & 0x1F:05b} (справа №1) | "
            f"({st.x:.1f}, {st.y:.1f}, {st.z:.1f})")


def cmd_install(args) -> int:
    game = Path(args.game) if args.game else next((g for g in GAME_GUESSES if g.exists()), None)
    if not game or not (game / "data" / "Mods").exists():
        print("Не нашёл папку игры. Укажите её: python -m aobot install --game \"путь\"")
        return 1
    had_cfg = (game / "data" / "Mods" / "Addons" / "BotBridge" / "Scripts" / "Config.lua").exists()
    dst = install_addon(game, overwrite_config=args.overwrite_config)
    if had_cfg and not args.overwrite_config:
        print("Ваш Config.lua в игре сохранён (перезаписать: --overwrite-config).")
    print(f"Аддон установлен: {dst}")
    print("Дальше: в главном меню игры включите пользовательские дополнения, войдите "
          "персонажем, затем запустите: python -m aobot diag")
    return 0


def cmd_diag(args) -> int:
    grab = capture.ScreenGrabber()
    reader = StateReader(grab, stale_seconds=2.0)
    print("Ctrl+C — выход")
    try:
        while True:
            st, why = reader.read(time.monotonic())
            extra = ""
            if reader.geo:
                frame = grab()
                if frame:
                    extra = f" | ячейка {reader.geo.cell}px, искажение цвета {calib_error(frame[0], reader.geo)}"
            print((describe(st) if st else why) + extra)
            if args.once:
                return 0 if st else 2
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0


def open_backend(cfg):
    i = cfg.input
    return make_backend(mouse=i.mouse, mouse_packet=i.mouse_packet)


def wait_until(t: float) -> None:
    """Точное ожидание: спим почти до момента, остаток дожидаемся в цикле."""
    while True:
        left = t - time.monotonic()
        if left <= 0:
            return
        if left > 0.003:
            time.sleep(left - 0.002)


def perform(backend, acts) -> None:
    """Выполнить действия через ввод PS/2 (Press.at ждём точно)."""
    for a in acts:
        if isinstance(a, Press):
            if a.at is not None:
                wait_until(a.at)
            backend.press(a.key)
        elif isinstance(a, Hold):
            backend.press(a.key, hold=a.seconds)


def cmd_assist(args) -> int:
    try:
        cfg = load_config(args.config)
    except (ConfigError, OSError) as e:
        print(f"Ошибка настроек: {e}")
        return 1
    if not cfg.combat.rotation:
        print("В config.toml нет ни одного [[rotation]] — бот не знает, чем бить.")
        return 1
    backend = None
    if not args.dry:
        try:
            backend = open_backend(cfg)
        except InputError as e:
            print(f"Ввод: {e}")
            return 1
        print(f"Способ ввода: {backend.name}")
    assist = Assist(cfg.combat, RotationPolicy(cfg.combat.rotation),
                    None if args.dry else FightRecorder(Path(args.data)))
    try:
        return assist_loop(args, cfg, backend, assist)
    finally:
        if backend:
            backend.close()


def assist_loop(args, cfg, backend, assist) -> int:
    grab = capture.ScreenGrabber()
    reader = StateReader(grab, cfg.stale_seconds)
    chat = ChatGuard(cfg.chat_keys, cfg.chat_close_keys)
    deadline = time.monotonic() + args.seconds if args.seconds else None
    print(f"Помощник: {cfg.assist_key.upper()} — бить текущую цель, "
          f"{cfg.stop_key.upper()} — выход." + (" [пробный режим: клавиши не нажимаются]" if args.dry else ""))
    last_line = ""
    try:
        while True:
            now = time.monotonic()
            if deadline and now > deadline:
                print("\nВремя вышло.")
                return 0
            if keys.is_down(cfg.stop_key):
                print("\nОстановлено клавишей.")
                return 0
            st, why = reader.read(now)
            hwnd = grab.window()
            if st is None:
                line = f"ждём: {why}"
            elif not hwnd or not capture.is_foreground(hwnd):
                line = "окно игры не активно — ничего не нажимаю"
            else:
                typing = chat.update({k for k in chat.keys if keys.is_down(k)})
                acts = assist.step(st, now, keys.is_down(cfg.assist_key), typing=typing)
                if backend:
                    perform(backend, acts)
                pressed = " ".join(a.key for a in acts if isinstance(a, (Press, Hold)))
                status = (f"чат открыт: {cfg.assist_key.upper()} не действует (Esc — сброс)"
                          if typing else assist.status)
                line = f"{status:22s} {pressed:6s} | " + describe(st)
            key_line = line.split("|", 1)[0]
            if key_line != last_line:
                if args.log:
                    print(f"{time.strftime('%H:%M:%S')} {line}")
                else:
                    sys.stdout.write("\r" + line[:150].ljust(150))
                    sys.stdout.flush()
                last_line = key_line
            time.sleep(cfg.poll_seconds)
    except KeyboardInterrupt:
        print("\nПрервано.")
        return 0
    finally:
        assist.stop(time.monotonic())


def cmd_stats(args) -> int:
    data = Path(args.data)
    fights, bad = load_fights(data)
    if not fights:
        print(f"Боёв в журнале нет: {data}")
        if bad:
            print(f"пропущено битых строк: {bad}")
        return 0
    game = Path(args.game) if args.game else next((g for g in GAME_GUESSES if g.exists()), None)
    names = kind_names(game / "Personal" / "Logs" / "mods.txt") if game else {}
    print(format_rows(summarize(fights, names)))
    if bad:
        print(f"пропущено битых строк: {bad}")
    return 0


def cmd_test_input(args) -> int:
    try:
        cfg = load_config(args.config)
        backend = open_backend(cfg)
    except (ConfigError, OSError, InputError) as e:
        print(f"Ошибка: {e}")
        return 1
    try:
        if args.click is not None:
            from .inputs import cursor_pos
            if args.click:
                x, y = args.click
                where = f"в точке ({x}, {y})"
            else:
                where = "там, где будет курсор"
            print(f"Способ ввода: {backend.name}. Через {args.delay:.0f} с кликну "
                  f"{args.button} {where} {args.times} раз(а).")
            time.sleep(args.delay)
            for _ in range(args.times):
                if args.click:
                    ok = backend.move_to(x, y)
                    time.sleep(0.05)
                else:
                    ok = True
                backend.click(args.button, hold=args.hold)
                print(f"  клик в {cursor_pos()}" + ("" if ok else " (курсор не дошёл до точки)"))
                time.sleep(0.7)
            print("Готово. Если в игре ничего не нажалось — клики этим способом игра не принимает.")
            return 0
        if args.mouse:
            from .inputs import cursor_pos
            print(f"Способ ввода: {backend.name}. Через {args.delay:.0f} с сдвину мышь "
                  f"на 100 px вправо и обратно {args.times} раз(а), без кликов.")
            time.sleep(args.delay)
            for _ in range(args.times):
                x, y = cursor_pos()
                there = backend.move_to(x + 100, y)
                mid = cursor_pos()
                time.sleep(0.4)
                back = backend.move_to(x, y)
                print(f"  {(x, y)} -> {mid} -> {cursor_pos()} "
                      f"{'ок' if there and back else 'курсор не дошёл (игра могла его вернуть)'}")
                time.sleep(0.4)
            return 0
        print(f"Способ ввода: {backend.name}. Переключитесь в окно игры — через "
              f"{args.delay:.0f} с нажму «{args.key}» {args.times} раз(а).")
        time.sleep(args.delay)
        for _ in range(args.times):
            backend.press(args.key, hold=args.hold)
            time.sleep(0.5)
        print("Готово. Если в игре ничего не произошло — этот способ игра не принимает.")
        return 0
    finally:
        backend.close()


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="python -m aobot")
    sub = p.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("install", help="поставить аддон BotBridge в игру")
    pi.add_argument("--game", help="папка игры")
    pi.add_argument("--overwrite-config", action="store_true")
    pd = sub.add_parser("diag", help="показать, что бот видит на экране")
    pd.add_argument("--once", action="store_true")
    pa = sub.add_parser("assist", help="режим боя-помощник: горячая клавиша — бить текущую цель")
    pa.add_argument("--config", default=str(ROOT / "config.toml"))
    pa.add_argument("--dry", action="store_true", help="не нажимать клавиши")
    pa.add_argument("--seconds", type=float, default=0, help="остановиться через N секунд")
    pa.add_argument("--log", action="store_true", help="печатать каждую смену статуса строкой")
    pa.add_argument("--data", default=str(ROOT / "data" / "fights"), help="папка журнала боёв")
    ps = sub.add_parser("stats", help="статистика боёв из журнала")
    ps.add_argument("--data", default=str(ROOT / "data" / "fights"), help="папка журнала боёв")
    ps.add_argument("--game", help="папка игры (для названий целей из mods.txt)")
    pt = sub.add_parser("test-input", help="проверить, доходят ли нажатия до игры")
    pt.add_argument("--config", default=str(ROOT / "config.toml"))
    pt.add_argument("--key", default="1")
    pt.add_argument("--times", type=int, default=3)
    pt.add_argument("--hold", type=float, default=0.05)
    pt.add_argument("--delay", type=float, default=5.0)
    pt.add_argument("--mouse", action="store_true", help="проверить мышь вместо клавиш")
    pt.add_argument("--click", nargs="*", type=int, metavar=("X", "Y"),
                    help="кликнуть: без чисел — где курсор, с X Y — в этой точке экрана")
    pt.add_argument("--button", default="left", choices=["left", "right", "middle"])
    args = p.parse_args(argv)
    if getattr(args, "click", None) and len(args.click) != 2:
        p.error("--click: либо без чисел, либо два числа X Y")
    return {"install": cmd_install, "diag": cmd_diag,
            "assist": cmd_assist, "stats": cmd_stats, "test-input": cmd_test_input}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
