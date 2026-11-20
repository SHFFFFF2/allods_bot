# Режим боя-помощник — план работ (план 1 из 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** по горячей клавише бот бьёт текущую цель игрока ротацией из `config.toml`, пока цель есть, и пишет каждый бой в журнал; `stats` показывает итоги по видам мобов.

**Architecture:** логика «когда жать» (ГКД, подтверждение, очередь каста) выносится из `Brain` в `Executor`, а сам бот-фармер (`Brain`, команда `run`) удаляется — решение пользователя, режим фарма будет построен заново позже; выбор умения идёт через интерфейс `Policy` (сейчас — `RotationPolicy`, в плане 3 — обученная модель); `Assist` управляет включением, сменой и пропажей цели и делит игру на бои для `FightRecorder`. Полоса получает идентификатор и вид цели (протокол v2).

**Tech Stack:** Python 3.11+ (только стандартная библиотека), Lua 5.1 (аддон), LuaJIT из `tools/luajit` для тестов аддона, `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-17-combat-ai-design.md`

**Входит в этот план:** режим-помощник, исполнитель, удаление старого бота-фармера, интерфейс модели, журнал боёв, статистика, протокол v2 (id и вид цели).

Общая картина режимов и планов — `docs/superpowers/roadmap.md`.
**Не входит:** каталог умений и вех, чтение панели умений, классовый ресурс, эффекты, каст цели, точки решения во время ГКД для умений без ГКД, калькулятор стартовой ротации (план 2); модель, обучение, сравнение, откат (план 3).

## Global Constraints

- Только стандартная библиотека Python в этом плане (numpy появится в плане 3).
- `python -m unittest discover -s tests -t .` зелёный после каждой задачи (до начала — 104 теста; после задачи 2b тесты фармера уходят вместе с ним).
- Lua-файлы хранятся в UTF-8; установщик перекодирует их в cp1251. Новые глобалы аддона — только через `Global(...)` (в клиенте строгие глобалы).
- Любое изменение формата полосы — одновременно в `aobot/protocol.py` и `addon/BotBridge/Scripts/Packer.lua` (сверяет `tests/test_lua_packer.py`).
- Клавиши жмутся только через PS/2-бэкенд и только когда окно игры активно.
- Бот-фармер (`aobot/brain.py`, команда `run`, пауза `pause_key`) удаляется по решению пользователя; его код остаётся в коммите задачи 0. Тайминг нажатий из него переносится в `Executor` без изменения поведения.
- Остаются команды `install`, `diag`, `test-input`; клавиша остановки программы `[safety] stop_key` (F12) остаётся.
- Тексты для пользователя — по-русски, как во всём проекте.
- `aobot/brain.py` недавно правили в другой сессии: перед задачей 2 убедиться у пользователя, что там правок больше не идёт.
- Проект пока не под git: задача 0 создаёт репозиторий, дальше каждая задача кончается коммитом.

## Review Focus

1. Горячую клавишу держат или жмут повторно → бот включается один раз; нажатие во время боя ничего не меняет; после остановки удерживаемая клавиша не включает его снова, пока её не отпустят и не нажмут заново (задача 5).
2. Цель убита, и игра сама сняла выделение (цели нет, последнее здоровье ≤ 2%) → бой засчитан как убийство, а не как сброс (задача 5).
3. Окно игры потеряло фокус или данные полосы пропали посреди боя → бот ничего не жмёт, бой не обрывается и продолжается, когда данные вернутся (задача 5).
4. Пользователь во время боя открыл чат (клавиши из `[assist] chat_keys`, по умолчанию Enter и Backspace; `/` не входит — на неё может быть назначено умение) → бот сразу выключается, чтобы его клавиши не печатались в чат (задачи 5 и 6).
5. В журнале битая строка (игра упала посреди записи) или папка недоступна для записи → `stats` пропускает и считает битые строки; запись боя предупреждает один раз и не роняет бой (задачи 4 и 7).

---

### Task 0: Репозиторий

**Files:**
- Create: `.gitignore`

- [ ] **Step 1: Создать репозиторий и снимок текущего состояния**

`.gitignore`: `__pycache__/`, `*.pyc`, `data/`.

```bash
cd "D:/14/utility/allods_bot_impossible" && git init && git add -A && git commit -m "chore: snapshot before combat assist mode"
```
Expected: коммит создан, `git status` чистый.

---

### Task 1: Протокол v2 — идентификатор и вид цели

**Files:**
- Modify: `aobot/protocol.py` (раскладка в докстринге, `VERSION`, `PAYLOAD_LEN`, `GameState`, `encode_bytes`, `decode_bytes`)
- Modify: `addon/BotBridge/Scripts/Packer.lua`, `addon/BotBridge/Scripts/Collect.lua` (`BotCollect`), `addon/BotBridge/Scripts/Main.lua` (`paint`)
- Modify: `aobot/__main__.py` (`describe`), `README.md` (число ячеек)
- Test: `tests/test_protocol.py`, `tests/test_lua_packer.py`, `tests/test_lua_collect.py`, `tests/test_lua_main.py`

**Interfaces:**
- Produces: `GameState.target_id: int = 0` (0 — нет цели, иначе 1..65535), `GameState.target_kind: int = 0` (0 — неизвестно, иначе 1..65521); `protocol.VERSION == 2`, `protocol.PAYLOAD_LEN == 30`, `protocol.CELL_COUNT == 13`; байты 26–27 — `target_id`, 28–29 — `target_kind` (u16, big-endian); `protocol.kind_hash(data: bytes) -> int` (эталон для тестов); `protocol.KIND_LOG_PREFIX = "BotBridge: вид цели "`.
- Produces (Lua): `BotKind(name) -> int` в `Collect.lua`; `BotCollect` заполняет `st.target_id`, `st.target_name` (строка, не пакуется), `st.target_kind` только когда цель есть; `Packer` пишет `0` вместо `nil`; `Main.lua` один раз на вид пишет в лог `BotBridge: вид цели <kind> = <name>`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_protocol.py
def test_target_identity_round_trip(self):
    st = sample_state(target_id=4321, target_kind=777)
    self.assertEqual(decode_bytes(encode_bytes(st)), st)

def test_v2_layout(self):
    self.assertEqual((protocol.VERSION, protocol.PAYLOAD_LEN, protocol.CELL_COUNT), (2, 30, 13))

def test_kind_hash(self):
    self.assertEqual(protocol.kind_hash(b""), 0)
    self.assertEqual(protocol.kind_hash(b"A"), 66)          # (0*31+65) % 65521 + 1
    self.assertTrue(1 <= protocol.kind_hash("Краб".encode("cp1251")) <= 65521)

# tests/test_lua_packer.py
def test_target_identity_matches_python(self):
    self.check(sample_state(target_id=4321, target_kind=777))

def test_missing_identity_packs_as_zero(self):
    code = ("Global = function(n, v) _G[n] = v end\n"
            f"dofile([[{PACKER}]])\n"
            "local out = BotPack({ seq = 1 })\n"
            "io.write(out[27], ',', out[28], ',', out[29], ',', out[30])\n")
    res = subprocess.run([str(LUAJIT), "-e", code], capture_output=True, text=True, timeout=20)
    self.assertEqual(res.stdout, "0,0,0,0")                   # байты 26–29, в Lua индексы с 1

# tests/test_lua_collect.py
def test_target_identity(self):
    st = run("object.GetName = function(id) return { w = 'Береговой краб' } end")
    self.assertEqual(st["target_id"], "51")                  # 50 % 65535 + 1
    self.assertEqual(st["target_kind"], str(protocol.kind_hash("Береговой краб".encode("utf-8"))))

def test_no_target_has_no_identity(self):
    st = run("W.target = nil")
    self.assertNotIn("target_id", st)

# tests/test_lua_main.py
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
```

`sample_state` в `tests/test_protocol.py` не трогать: новые поля имеют значения по умолчанию.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_protocol tests.test_lua_packer tests.test_lua_collect tests.test_lua_main -v`
Expected: FAIL (`unexpected keyword argument 'target_id'`, `AttributeError: kind_hash`, нет поля в дампе Lua).

- [ ] **Step 3: Implement**

- `protocol.py`: поля в конец `GameState`; `PAYLOAD_LEN = 30`; `encode_bytes` дописывает `_u16(st.target_id) + _u16(st.target_kind)`; `decode_bytes` читает `u16(26)`, `u16(28)`; `kind_hash`: `h = (h*31 + b) % 65521` по байтам, результат `h + 1`, для пустых данных `0`.
- `Packer.lua`: `BOT_VERSION = 2`, `BOT_PAYLOAD_LEN = 30`, `BOT_BODY_PADDED = 33`, `BOT_CELL_COUNT = 13`; `pushU16(out, st.target_id or 0)`, `pushU16(out, st.target_kind or 0)` после направления.
- `Collect.lua`: `BotKind` по той же формуле через `string.byte`; в ветке «цель есть»: `st.target_id = type(t) == "number" and t % 65535 + 1 or 0`, `st.target_name = wstr(safe("object.GetName", lib(object, "GetName"), t))`, `st.target_kind = BotKind(st.target_name)`.
- `Main.lua`: локальная таблица увиденных видов; в `paint()` после `BotCollect` — одна запись лога на новый `target_kind ~= 0`.
- `describe`: дописать `#<target_id> вид <target_kind>` к описанию цели.
- `README.md`: «полосой из 12 ячеек» → «полосой из 13 ячеек».

- [ ] **Step 4: Run all tests**

Run: `python -m unittest discover -s tests -t .`
Expected: OK (104 + 7 новых).

- [ ] **Step 5: Commit**

```bash
git add aobot/protocol.py aobot/__main__.py addon/BotBridge/Scripts README.md tests && git commit -m "feat: protocol v2 with target id and kind"
```

---

### Task 2: Исполнитель (вынос из Brain)

**Files:**
- Create: `aobot/actions.py` — `Press`, `Hold`, `Stop`, `Action`, перенесённые из `brain.py`
- Create: `aobot/rotation.py` — `RotationStep` из `brain.py` и `step_applies`
- Create: `aobot/executor.py`
- Modify: `aobot/brain.py` (`Brain` использует `Executor`; поведение не меняется; `brain.py` реэкспортирует `Press`, `Hold`, `Stop`, `Action`, `RotationStep`, чтобы `from aobot.brain import ...` в `config.py` и тестах работал как раньше)
- Test: `tests/test_executor.py`; `tests/test_brain.py` — без изменений

Порядок импортов без циклов: `actions` ← `executor`; `rotation` ← `brain`, `policy`; `executor` ← `brain`, `assist`.

**Interfaces:**
- Produces:
  - `step_applies(step: RotationStep, st: GameState, heals: bool) -> bool` в `aobot/rotation.py` — условия шага ротации (`self_hp_below`, окно здоровья цели, ближний бой), как сейчас в `Brain._pick`.
  - `@dataclass(frozen=True) class Slot: at: Optional[float]; queued: bool` — момент нажатия (`None` — сейчас) и «во время каста».
  - `class Executor(cfg)`: `cfg` — любой объект с полями тайминга `BotConfig` (`press_cooldown`, `confirm_seconds`, `confirm_frames`, `gcd_lookahead`, `gcd_lead`, `queue_during_cast`, `cast_queue_after`).
  - `Executor.observe(st: GameState, now: float) -> None` — бывший `Brain._observe` плюс учёт начала каста (`cast_since`).
  - `Executor.slot(st: GameState, now: float) -> Optional[Slot]` — `None`, если сейчас жать нельзя (ГКД дальше `gcd_lookahead`, ждём подтверждения прошлого нажатия, каст короче `cast_queue_after` или `queue_during_cast` выключен).
  - `Executor.retry_blocked(key: str, now: float) -> bool`, `Executor.queue_blocked(key: str, slot: Slot) -> bool`.
  - `Executor.commit(key: str, spell_index: int, slot: Slot, now: float) -> Press` — учёт нажатия, как строки 282–291 нынешнего `_pick`.
  - атрибуты `Executor.no_queue: set[str]`, `Executor.queue_fails: dict[str, int]`; у `Brain` — свойства `no_queue` и `queue_fails`, отдающие их (их читают тесты).

- [ ] **Step 1: Write the failing tests** (`tests/test_executor.py`, состояние через `GameState(avatar_exists=True, ...)`, конфиг — `BotConfig()`)

```python
def test_slot_now_when_no_gcd(self):
    ex = Executor(BotConfig()); st = GameState(avatar_exists=True, seq=1)
    ex.observe(st, 0.0)
    self.assertEqual(ex.slot(st, 0.0), Slot(at=None, queued=False))

def test_no_slot_while_gcd_far(self):
    ex = Executor(BotConfig()); st = GameState(avatar_exists=True, seq=1, gcd_ms=900)
    ex.observe(st, 0.0)
    self.assertIsNone(ex.slot(st, 0.0))

def test_slot_at_gcd_end_within_lookahead(self):
    ex = Executor(BotConfig(gcd_lookahead=0.06))
    ex.observe(GameState(avatar_exists=True, seq=1, gcd_ms=900), 0.0)
    st = GameState(avatar_exists=True, seq=2, gcd_ms=40)
    ex.observe(st, 0.86)
    slot = ex.slot(st, 0.86)
    self.assertFalse(slot.queued); self.assertAlmostEqual(slot.at, 0.905)

def test_waits_for_confirmation_after_commit(self):
    ex = Executor(BotConfig(confirm_frames=2, confirm_seconds=0.2))
    st = lambda seq: GameState(avatar_exists=True, seq=seq)
    ex.observe(st(1), 0.0); ex.commit("3", 2, ex.slot(st(1), 0.0), 0.0)
    ex.observe(st(2), 0.05); self.assertIsNone(ex.slot(st(2), 0.05))
    ex.observe(st(3), 0.25); self.assertIsNotNone(ex.slot(st(3), 0.25))

def test_queue_slot_only_after_cast_queue_after(self):
    ex = Executor(BotConfig(cast_queue_after=0.3))
    st = lambda seq: GameState(avatar_exists=True, seq=seq, casting=True)
    ex.observe(st(1), 0.0); self.assertIsNone(ex.slot(st(1), 0.2))
    ex.observe(st(2), 0.35); self.assertEqual(ex.slot(st(2), 0.35), Slot(at=None, queued=True))

def test_retry_blocked_until_press_cooldown(self):
    ex = Executor(BotConfig(press_cooldown=0.35)); st = GameState(avatar_exists=True, seq=1)
    ex.observe(st, 0.0); ex.commit("3", 2, Slot(None, False), 0.0)
    self.assertTrue(ex.retry_blocked("3", 0.1)); self.assertFalse(ex.retry_blocked("3", 0.36))

def test_queue_blocked_after_three_failed_queued_presses(self):
    ex = Executor(BotConfig(cast_queue_after=0.0, confirm_frames=1, confirm_seconds=0.0))
    t, seq = 0.0, 0
    for _ in range(3):
        seq += 1; st = GameState(avatar_exists=True, seq=seq, casting=True, spells_ready=0b100)
        ex.observe(st, t); ex.commit("3", 2, ex.slot(st, t), t)
        t += 0.4; seq += 1
        ex.observe(GameState(avatar_exists=True, seq=seq, casting=True, spells_ready=0b100), t)
        t += 0.4
    self.assertTrue(ex.queue_blocked("3", Slot(None, True)))
    self.assertFalse(ex.queue_blocked("3", Slot(None, False)))
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_executor -v`
Expected: FAIL (`No module named 'aobot.executor'`).

- [ ] **Step 3: Implement `aobot/executor.py`, перевести `Brain` на него**

Код переносится из `Brain` без изменения логики. В `Brain._pick(st, now, heals, slot)` остаются фильтры ротации (через `step_applies`); перед нажатием — `retry_blocked` → следующее умение, `queue_blocked` → `return None`; затем `commit`, и `Brain` сам пишет `self.last_press[step.key]`, как сейчас.

- [ ] **Step 4: Run tests**

Run: `python -m unittest tests.test_executor tests.test_brain -v`
Expected: OK, в `test_brain` все 38 тестов без правок.

- [ ] **Step 5: Commit**

```bash
git add aobot/actions.py aobot/rotation.py aobot/executor.py aobot/brain.py tests/test_executor.py && git commit -m "refactor: extract press timing from Brain into Executor"
```

---

### Task 2b: Удалить бота-фармера

Решение пользователя: старый бот (поиск цели Tab'ом, поворот, добыча, отдых, пауза F10) больше не нужен. Режим фарма будет построен заново отдельным планом. Сначала задача 2 переносит тайминг и проверяет его старыми тестами — только потом удаление.

**Files:**
- Delete: `aobot/brain.py`, `tests/test_brain.py`
- Modify: `aobot/rotation.py` (добавить `CombatConfig`), `aobot/config.py`, `aobot/__main__.py` (убрать `cmd_run`, `run_loop`, импорт `Brain`), `config.toml`, `config.example.toml`, `README.md`
- Test: `tests/test_executor.py` (перенесённые тесты тайминга), `tests/test_config.py`

**Interfaces:**
- Produces:
  - `@dataclass class CombatConfig` в `aobot/rotation.py`: поля тайминга из `BotConfig` с теми же значениями по умолчанию (`press_cooldown=0.35`, `confirm_seconds=0.2`, `confirm_frames=2`, `gcd_lookahead=0.06`, `gcd_lead=0.0`, `queue_during_cast=True`, `cast_queue_after=0.3`) и `rotation: list[RotationStep]`. `Executor` принимает его. В `tests/test_executor.py` `BotConfig` заменить на `CombatConfig`.
  - `AppConfig.combat: CombatConfig` вместо `AppConfig.brain`; разделы `config.toml`: `[combat]` (только поля тайминга), `[safety]` (`stop_key`, `stale_seconds`, `poll_seconds`, `window_title`), `[input]`, `[[rotation]]`. Раздел `[keys]` и `pause_key` — `ConfigError` с подсказкой «бот-фармер удалён, уберите [keys] / pause_key».
  - `Press`, `Hold`, `Stop`, `Action` — только из `aobot/actions.py`; `RotationStep` — из `aobot/rotation.py`.

- [ ] **Step 1: Перенести тесты тайминга.** Из `tests/test_brain.py` в `tests/test_executor.py` переписать на `Executor` те, что проверяют ГКД, подтверждение нажатия, очередь каста и `no_queue` (поиск цели, добыча, отдых и смерть уходят вместе с ботом). Дописать в `tests/test_config.py`:

```python
def test_keys_section_is_rejected_with_hint(self):
    with self.assertRaisesRegex(ConfigError, "фармер"): parse_config('[keys]\ntarget = "tab"\n')

def test_pause_key_is_rejected_with_hint(self):
    with self.assertRaisesRegex(ConfigError, "фармер"): parse_config('[safety]\npause_key = "f10"\n')

def test_timing_fields_go_to_combat_config(self):
    self.assertEqual(parse_config('[combat]\ngcd_lookahead = 0.08\n').combat.gcd_lookahead, 0.08)
```

Тесты `tests/test_config.py`, проверяющие `[keys]` и поля фармера, удалить.

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_config tests.test_executor -v`
Expected: FAIL (`AttributeError: 'AppConfig' object has no attribute 'combat'`).

- [ ] **Step 3: Удалить `brain.py` и `run`, перевести `config.py` на `CombatConfig`; из `config.toml` и `config.example.toml` убрать `[keys]`, `pause_key` и поля фармера в `[combat]`; в `README.md` убрать разделы про бота-фармера (поиск цели, добыча, отдых, F10) — раздел о новом режиме добавит задача 6.**

- [ ] **Step 4: Run all tests**

Run: `python -m unittest discover -s tests -t .`
Expected: OK. `python -m aobot --help` не показывает `run`.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "refactor: remove the old farm bot"
```

---

### Task 3: Интерфейс модели и ротация

**Files:**
- Create: `aobot/policy.py`
- Test: `tests/test_policy.py`

**Interfaces:**
- Consumes: `Executor.retry_blocked` (задача 2; в `legal_steps` — по утиной типизации, без импорта), `RotationStep` и `step_applies` из `aobot/rotation.py`.
- Produces:
  - `class Policy(Protocol): name: str; def choose(self, st: GameState, legal: Sequence[RotationStep]) -> Optional[RotationStep]` (`None` — «ждать»).
  - `class RotationPolicy(rotation: list[RotationStep])`, `name = "rotation"`: из `legal` сначала первое подходящее лечение (в порядке ротации), потом первая подходящая атака.
  - `legal_steps(rotation: list[RotationStep], st: GameState, ex: Executor, now: float) -> list[RotationStep]` — умения, готовые в маске `st.spells_ready` и не заблокированные `retry_blocked`.

- [ ] **Step 1: Write the failing tests**

```python
HEAL = RotationStep(spell=1, key="1", self_hp_below=50)
FINISH = RotationStep(spell=2, key="2", max_target_hp=30)
HIT = RotationStep(spell=3, key="3")
ROT = [HEAL, FINISH, HIT]
st = lambda **o: GameState(**{**dict(avatar_exists=True, hp=90, has_target=True, target_hp=80, spells_ready=0b111), **o})

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
        def retry_blocked(self, key, now): return key == "2"
    self.assertEqual(legal_steps(ROT, st(spells_ready=0b110), Ex(), 0.0), [HIT])
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_policy -v`
Expected: FAIL (`cannot import name 'RotationPolicy'`).

- [ ] **Step 3: Implement `RotationPolicy`, `Policy`, `legal_steps` in `aobot/policy.py`**

- [ ] **Step 4: Run tests**

Run: `python -m unittest tests.test_policy tests.test_executor -v`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add aobot/policy.py tests/test_policy.py && git commit -m "feat: policy interface and rotation policy"
```

---

### Task 4: Журнал боёв

**Files:**
- Create: `aobot/journal.py`
- Test: `tests/test_journal.py`

**Interfaces:**
- Produces:
  - `OUTCOMES = ("kill", "switched", "dropped", "death", "stopped")`.
  - `class FightRecorder(directory: Path, wall_clock: Callable[[], datetime] = datetime.now)`.
  - `begin(target_id: int, target_kind: int, policy: str, now: float) -> None`.
  - `step(now: float, st: GameState, legal: list[str], chosen: Optional[str]) -> None` — точка решения.
  - `end(now: float, outcome: str) -> Optional[dict]` — дописывает одну строку JSON в `<directory>/fights-YYYY-MM-DD.jsonl` (дата — `wall_clock()` при `begin`) и возвращает запись; без открытого боя — `None`; неизвестный исход — `ValueError`.
  - Запись: `{"v": 1, "started": ISO-время, "duration": с, "policy": str, "target_id": int, "target_kind": int, "outcome": str, "steps": [{"t": с от начала, "s": dataclasses.asdict(GameState), "legal": [клавиши], "a": клавиша или null}]}`.
  - Ошибка записи (нет доступа, путь — файл) — одно предупреждение в `sys.stderr` за всё время жизни объекта, без исключения; `end` всё равно возвращает запись.

- [ ] **Step 1: Write the failing tests** (`tempfile.TemporaryDirectory`, часы: `lambda: datetime(2026, 11, 17, 19, 30)`)

```python
def test_writes_one_json_line_per_fight(self):
    rec = FightRecorder(d, wall_clock=CLOCK)
    rec.begin(51, 777, "rotation", 10.0)
    rec.step(10.5, GameState(avatar_exists=True, target_hp=80), ["1", "3"], "3")
    out = rec.end(14.0, "kill")
    lines = (d / "fights-2026-11-17.jsonl").read_text(encoding="utf-8").splitlines()
    self.assertEqual(len(lines), 1)
    rec_json = json.loads(lines[0])
    self.assertEqual(rec_json, out)
    self.assertEqual((rec_json["outcome"], rec_json["duration"], rec_json["target_kind"]), ("kill", 4.0, 777))
    self.assertEqual(rec_json["steps"][0], {"t": 0.5, "s": rec_json["steps"][0]["s"], "legal": ["1", "3"], "a": "3"})
    self.assertEqual(rec_json["steps"][0]["s"]["target_hp"], 80)

def test_end_without_begin_returns_none(self):
    self.assertIsNone(FightRecorder(d).end(1.0, "kill"))

def test_rejects_unknown_outcome(self):
    rec = FightRecorder(d); rec.begin(1, 0, "rotation", 0.0)
    with self.assertRaises(ValueError): rec.end(1.0, "won")

def test_unwritable_directory_warns_once_and_continues(self):   # Review Focus 5
    blocker = d / "file"; blocker.write_text("x")
    rec = FightRecorder(blocker / "fights", wall_clock=CLOCK)
    with contextlib.redirect_stderr(io.StringIO()) as err:
        for _ in range(2):
            rec.begin(1, 0, "rotation", 0.0)
            self.assertIsNotNone(rec.end(1.0, "kill"))
    self.assertEqual(err.getvalue().count("журнал"), 1)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_journal -v`
Expected: FAIL (`No module named 'aobot.journal'`).

- [ ] **Step 3: Implement `aobot/journal.py`**

Папка создаётся при первой записи (`mkdir(parents=True, exist_ok=True)`); строка пишется целиком одним `write` в режиме дописывания, кодировка UTF-8, `ensure_ascii=False`. Текст предупреждения содержит слово «журнал».

- [ ] **Step 4: Run tests**

Run: `python -m unittest tests.test_journal -v`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add aobot/journal.py tests/test_journal.py && git commit -m "feat: fight journal"
```

---

### Task 5: Режим-помощник

**Files:**
- Create: `aobot/assist.py`
- Test: `tests/test_assist.py`

**Interfaces:**
- Consumes: `Executor`, `Slot` (задача 2); `Policy`, `legal_steps` (задача 3); `FightRecorder` (задача 4) — в тестах подменяется объектом с теми же `begin/step/end`.
- Produces:
  - `KILL_HP = 2` — если цель пропала, а её последнее здоровье ≤ этого, бой считается убийством.
  - `class Assist(cfg: CombatConfig, policy: Policy, recorder: Optional[FightRecorder] = None)`; атрибуты `active: bool`, `status: str`.
  - `step(st: GameState, now: float, hotkey_down: bool, typing: bool = False) -> list[Action]`.
  - `stop(now: float) -> None` — закрыть открытый бой исходом `"stopped"` (выход из программы).
- Поведение (из спецификации, раздел «Цели» и «Модель и обучение»):
  - включение — только по фронту нажатия (`hotkey_down` стало `True`), если цель годится для атаки (`has_target`, не `target_dead`, `target_attackable`); иначе `status = "нет цели"`; в том же шаге, что и включение, бот уже принимает решение и может нажать умение;
  - нажатие во время боя ничего не меняет, отдельного выключения нет;
  - сменился `target_id` при живой цели — закрыть бой (`"kill"`, если прошлое здоровье ≤ `KILL_HP`, иначе `"switched"`), открыть новый и продолжить;
  - цели нет, она мертва или не атакуема — закрыть бой (`"kill"`, если `target_dead` или прошлое здоровье ≤ `KILL_HP`, иначе `"dropped"`) и выключиться;
  - персонаж мёртв — `"death"` и выключиться;
  - `typing` равно `True` во время боя (пользователь нажал одну из клавиш чата — `[assist] chat_keys`, задача 6) — до любого решения закрыть бой `"stopped"`, выключиться, `status = "чат — бот выключен"`;
  - точка решения: `slot = ex.slot(...)`; `legal = legal_steps(cfg.rotation, ...)`; `choice = policy.choose(st, legal)`; `recorder.step(now, st, [s.key for s in legal], choice.key if choice else None)`; `None` — ждать; `queue_blocked` — ждать; иначе `[ex.commit(choice.key, choice.spell - 1, slot, now)]`;
  - в бою и `st.spells_known == 0` — ничего не жать, `status = "умения не найдены"`.

- [ ] **Step 1: Write the failing tests** (хелперы `state(**o)` и `fighting(**o)` — как были в `tests/test_brain.py` до задачи 2b: `fighting(**o)` с `target_id=51`, `seq` растёт; ротация `[RotationStep(1, "1", self_hp_below=50), RotationStep(3, "3")]`; `FakeRecorder` пишет вызовы в список `calls`)

```python
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
    a.step(fighting(seq=3, target_id=52), 1.0, True); self.assertFalse(a.active)
    a.step(fighting(seq=4, target_id=52), 1.5, False); a.step(fighting(seq=5, target_id=52), 2.0, True)
    self.assertTrue(a.active)

def test_target_change_continues_and_splits_fight(self):
    a, rec = make_with_recorder(); a.step(fighting(seq=1), 0.0, True)
    a.step(fighting(seq=2, target_id=52, target_hp=90), 0.5, False)
    self.assertIn(("end", "switched"), rec.calls); self.assertIn(("begin", 52), rec.calls); self.assertTrue(a.active)

def test_target_cleared_after_low_hp_counts_as_kill(self):           # RF 2
    a, rec = make_with_recorder(); a.step(fighting(seq=1, target_hp=1), 0.0, True)
    a.step(state(seq=2), 0.5, False)
    self.assertEqual(rec.calls[-1], ("end", "kill")); self.assertFalse(a.active)

def test_target_dropped_counts_as_dropped(self):
    a, rec = make_with_recorder(); a.step(fighting(seq=1, target_hp=60), 0.0, True)
    a.step(state(seq=2), 0.5, False); self.assertEqual(rec.calls[-1], ("end", "dropped"))

def test_dead_target_selected_counts_as_kill(self):
    a, rec = make_with_recorder(); a.step(fighting(seq=1, target_hp=40), 0.0, True)
    a.step(fighting(seq=2, target_dead=True, target_hp=0), 0.5, False); self.assertEqual(rec.calls[-1], ("end", "kill"))

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

def test_no_known_spells_status(self):
    a = make(); a.step(fighting(seq=1, spells_known=0, spells_ready=0), 0.0, True)
    self.assertEqual(a.status, "умения не найдены")

def test_stop_closes_open_fight(self):
    a, rec = make_with_recorder(); a.step(fighting(seq=1), 0.0, True); a.stop(1.0)
    self.assertEqual(rec.calls[-1], ("end", "stopped"))

def test_records_decision_with_legal_and_choice(self):
    a, rec = make_with_recorder(); a.step(fighting(seq=1, spells_ready=0b100), 0.0, True)
    self.assertIn(("step", ["3"], "3"), rec.calls)
```

`FakeRecorder.calls`: `("begin", target_id)`, `("step", legal, chosen)`, `("end", outcome)`.

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_assist -v`
Expected: FAIL (`No module named 'aobot.assist'`).

- [ ] **Step 3: Implement `aobot/assist.py`**

- [ ] **Step 4: Run all tests**

Run: `python -m unittest discover -s tests -t .`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add aobot/assist.py tests/test_assist.py && git commit -m "feat: combat assist controller"
```

---

### Task 6: Настройка и команда `assist`

**Files:**
- Modify: `aobot/config.py` (`AppConfig.assist_key`, раздел `[assist]`), `aobot/__main__.py` (`cmd_assist`, общий `perform`), `config.example.toml`, `README.md`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `Assist`, `RotationPolicy`, `FightRecorder`.
- Produces:
  - `AppConfig.assist_key: str = "f9"`, `AppConfig.chat_keys: list[str] = ["enter", "backspace"]`; раздел `[assist]` с ключами `key` и `chat_keys`; все клавиши проверяются `_check_key`. `ConfigError`, если `key` совпадает со `stop_key`, или если клавиша чата совпадает с `key`, `stop_key` или клавишей любого `[[rotation]]` (иначе бот выключал бы сам себя своими нажатиями).
  - `perform(backend, acts: list[Action]) -> None` в `__main__.py` — исполнение действий (ожидание `Press.at` через `wait_until`, `Hold`); пригодится и будущим режимам.
  - `python -m aobot assist [--config] [--dry] [--seconds N] [--log] [--data DIR]` (`--data` по умолчанию `ROOT / "data" / "fights"`). Цикл: `stop_key` → `assist.stop(now)` и выход; нет данных или окно не активно — ничего не жать, `step` не вызывать; иначе `assist.step(st, now, keys.is_down(cfg.assist_key), typing=any(keys.is_down(k) for k in cfg.chat_keys))`. Без `[[rotation]]` — сообщение «В config.toml нет ни одного [[rotation]] — бот не знает, чем бить.» и код 1.

- [ ] **Step 1: Write the failing tests** (`tests/test_config.py`)

```python
def test_assist_key_default_f9(self):
    self.assertEqual(parse_config("").assist_key, "f9")

def test_assist_key_from_config(self):
    self.assertEqual(parse_config('[assist]\nkey = "f8"\n').assist_key, "f8")

def test_assist_unknown_param_rejected(self):
    with self.assertRaises(ConfigError): parse_config('[assist]\nbutton = "f8"\n')

def test_assist_key_same_as_stop_rejected(self):
    with self.assertRaises(ConfigError): parse_config('[assist]\nkey = "f12"\n')

def test_chat_keys_default_without_slash(self):                     # RF 4
    self.assertEqual(parse_config("").chat_keys, ["enter", "backspace"])

def test_chat_key_used_by_rotation_rejected(self):                   # RF 4
    with self.assertRaises(ConfigError):
        parse_config('[assist]\nchat_keys = ["enter", "/"]\n[[rotation]]\nspell = 1\nkey = "/"\n')
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_config -v`
Expected: FAIL (`AttributeError: 'AppConfig' object has no attribute 'assist_key'`).

- [ ] **Step 3: Implement config, `perform`, `cmd_assist`; создать в корне проекта батники для запуска двойным кликом (пользователю так удобнее): `assist.bat`, `diag.bat`, `install.bat` — каждый: `@echo off`, `cd /d "%~dp0"`, `python -m aobot <команда> %*`, `pause` (чтобы окно не закрылось и была видна ошибка); дописать `[assist]` в `config.example.toml` и раздел «Режим боя-помощник» в `README.md`** (как включать — F9; что останавливает: цель пропала, смерть, клавиши чата из `chat_keys`, F12 — выход из программы; предупреждение, что F12 в игре по умолчанию открывает «Сумку и экипировку», и `stop_key` можно сменить; где журнал)

- [ ] **Step 4: Verify**

Run: `python -m unittest discover -s tests -t .`
Expected: OK.

Run: `python -m aobot assist --dry --seconds 3`
Expected: код 0; печатается строка статуса (если игры не видно — «ждём: …»).

- [ ] **Step 5: Commit**

```bash
git add aobot/config.py aobot/__main__.py config.example.toml README.md tests/test_config.py assist.bat diag.bat install.bat && git commit -m "feat: assist command and [assist] config"
```

---

### Task 7: Статистика

**Files:**
- Create: `aobot/stats.py`
- Modify: `aobot/__main__.py` (`cmd_stats`)
- Test: `tests/test_stats.py`

**Interfaces:**
- Consumes: формат записи журнала (задача 4), `protocol.KIND_LOG_PREFIX` (задача 1).
- Produces:
  - `load_fights(directory: Path) -> tuple[list[dict], int]` — записи из всех `fights-*.jsonl` и число битых строк.
  - `kind_names(log_path: Path) -> dict[int, str]` — из `mods.txt` (cp1251) строки с `KIND_LOG_PREFIX`, формат `<kind> = <name>`; нет файла — `{}`.
  - `@dataclass(frozen=True) class Row: kind: int; name: str; policy: str; fights: int; kills: int; deaths: int; median_kill_s: Optional[float]`.
  - `summarize(fights: list[dict], names: dict[int, str]) -> list[Row]` — группы по `(target_kind, policy)`, сортировка по `fights` по убыванию; `name` — из `names` или `f"вид {kind}"`; медиана длительности только по `"kill"`.
  - `format_rows(rows: list[Row]) -> str`.
  - `python -m aobot stats [--data DIR] [--game DIR]` — таблица и, если были, «пропущено битых строк: N»; лог игры — `<game>/Personal/Logs/mods.txt` (игра ищется как в `install`).

- [ ] **Step 1: Write the failing tests**

```python
def fight(kind, outcome, duration, policy="rotation"):
    return {"v": 1, "target_kind": kind, "outcome": outcome, "duration": duration, "policy": policy}

def test_median_kill_time_per_kind_and_policy(self):
    rows = summarize([fight(7, "kill", 10), fight(7, "kill", 20), fight(7, "kill", 40)], {7: "Краб"})
    self.assertEqual(rows, [Row(7, "Краб", "rotation", 3, 3, 0, 20.0)])

def test_counts_deaths_and_other_outcomes(self):
    rows = summarize([fight(7, "kill", 10), fight(7, "death", 5), fight(7, "dropped", 3)], {})
    self.assertEqual((rows[0].fights, rows[0].kills, rows[0].deaths, rows[0].name), (3, 1, 1, "вид 7"))

def test_skips_broken_lines(self):                                   # RF 5
    (d / "fights-2026-11-17.jsonl").write_text(json.dumps(fight(7, "kill", 10)) + "\n{\"v\": 1, \"outc\n", encoding="utf-8")
    fights, bad = load_fights(d)
    self.assertEqual((len(fights), bad), (1, 1))

def test_kind_names_from_cp1251_log(self):
    line = "[19:08:16][UserAddon/BotBridge: 1.0 (build 1)]Info: BotBridge: вид цели 777 = Береговой краб\r\n"
    (d / "mods.txt").write_bytes(("мусор\r\n" + line).encode("cp1251"))
    self.assertEqual(kind_names(d / "mods.txt"), {777: "Береговой краб"})

def test_missing_log_gives_no_names(self):
    self.assertEqual(kind_names(d / "нет.txt"), {})
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_stats -v`
Expected: FAIL (`No module named 'aobot.stats'`).

- [ ] **Step 3: Implement `aobot/stats.py` and `cmd_stats`; добавить `stats.bat` по образцу батников задачи 6**

- [ ] **Step 4: Run all tests**

Run: `python -m unittest discover -s tests -t .`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add aobot/stats.py aobot/__main__.py tests/test_stats.py stats.bat && git commit -m "feat: fight stats command"
```

---

### Task 8: Проверка в игре

Нужна запущенная игра с персонажем. Перезагрузку аддона делает пользователь — попросить его.

- [ ] **Step 1: Поставить аддон**

Run: `python -m aobot install`
Expected: «Аддон установлен: …», «Ваш Config.lua в игре сохранён».

- [ ] **Step 2: Проверить полосу v2** (после перезагрузки аддона, цель — любой моб)

Run: `python -m aobot diag --once`
Expected: код 0, в описании цели есть `#<число>` и `вид <число>`, «искажение цвета» 0–2.

- [ ] **Step 3: Бой** — `python -m aobot assist --log`, выбрать моба, нажать F9.
Expected: статус «бой», умения ротации жмутся; после смерти моба — статус про убийство, бот выключен. Повторить со сбросом цели (Esc) — бот выключается, исход «dropped». F12 — выход.

- [ ] **Step 4: Итоги**

Run: `python -m aobot stats`
Expected: строка с именем моба, `kills ≥ 1`, медиана времени убийства.

- [ ] **Step 5: Commit** (если на проверке что-то правили)

```bash
git add -A && git commit -m "fix: live check of assist mode"
```
