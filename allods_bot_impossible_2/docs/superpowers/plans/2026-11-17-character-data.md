# Данные о персонаже — план работ (план 2 из 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** бот сам знает, что лежит на панели умений и на каких клавишах, видит ресурс, кулдауны, эффекты, каст и «босс ли» цели, сам считает стартовую ротацию `rotation.start.toml` и показывает всё это командой `python -m aobot catalog`; ручной `BOT_SPELLS` больше не нужен.

**Architecture:** аддон пишет в `mods.txt` выгрузку каталога (строки `BOTCAT`) при входе и при любой смене книги, панели, вех или клавиш, а в полосе (протокол v3, переменной длины) шлёт номер выгрузки и быстрые данные боя: готовность и кулдауны 36 слотов, ресурс, все эффекты, каст цели, босс, врагов рядом. Бот читает лог по хвосту, собирает `Catalog`, по нему калькулятор (`calc.py`) пишет стартовую ротацию по правилу «вариант А», ротация привязывается к слотам по названию умения, а помощник не жмёт ничего, пока номер выгрузки в полосе не совпал с прочитанным. Исполнитель получает отдельную точку решения во время ГКД для умений без ГКД.

**Tech Stack:** Python 3.11+ (только стандартная библиотека), Lua 5.1 (аддон), LuaJIT из `tools/luajit` для тестов аддона, `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-17-combat-ai-design.md` — раздел «План 2 — решения» (утверждён пользователем 2026-11-17) поверх общего дизайна.

**Входит:** каталог умений, пассивок, вех, панели и клавиш; протокол v3; чтение панели вместо `BOT_SPELLS`; ротация по названиям с условиями по ресурсу и эффектам; точки решения во время ГКД; калькулятор стартовой ротации; команда `catalog`.
**Не входит:** модель, обучение, сравнение, откат (план 3); классы кроме некроманта (интерфейсы общие, реализован и проверен некромант).

Общая картина — `docs/superpowers/roadmap.md`.

## Global Constraints

- Только стандартная библиотека Python (numpy появится в плане 3).
- `python -m unittest discover -s tests -t .` зелёный после каждой задачи (до начала — 189 тестов).
- Lua-файлы хранятся в UTF-8; установщик перекодирует их в cp1251. Новые глобалы аддона — только через `Global(...)` (в клиенте строгие глобалы). Новый скрипт аддона — в `AddonDesc.(UIAddon).xdb` (`ScriptFileRefs`) и в `ORDER` в `tests/test_lua_main.py`.
- Любое изменение формата полосы — одновременно в `aobot/protocol.py` и `addon/BotBridge/Scripts/Packer.lua` (сверяет `tests/test_lua_packer.py`).
- Установщик сохраняет пользовательский `Config.lua` игры: аддон обязан работать со старым `Config.lua` (в нём есть `BOT_SPELLS`, нет новых настроек) — новые настройки читать через `rawget(_G, ...)` со значением по умолчанию.
- Строки игры в cp1251: хэш названия считается по байтам cp1251 (`kind_hash(name.encode("cp1251"))` в Python, `BotKind` в Lua). `mods.txt` читается построчно: UTF-8, при ошибке — cp1251.
- Тяжёлые вызовы API (содержимое слотов, названия, клавиши, описания) аддон делает только по событиям, не чаще раза в секунду; каждый кадр (50 мс) — только кулдауны, ГКД, ресурс, цель, эффекты. Перекрашиваются только ячейки, цвет которых изменился. Врагов рядом — раз в секунду.
- Клавиши жмутся только через PS/2-бэкенд и только когда окно игры активно. Клавиша шага, совпадающая (целиком или частью сочетания) с `[assist].key`, `stop_key`, `chat_keys` или `chat_close_keys`, не жмётся никогда.
- Запуск для пользователя — только `assist.bat`; новых батников не делать.
- Тексты для пользователя — по-русски.
- Git: ветка `main`, автор SHFFFFF без почты (настроено в репозитории); каждая задача кончается коммитом.
- Живые проверки в игре проводит пользователь: исполнитель даёт ему шаги и ждёт результата; когда нужно перезагрузить аддон — просит его об этом (сам окно игры не трогает).

## Review Focus

1. Установщик оставил старый `Config.lua` (с `BOT_SPELLS`, без новых настроек) → аддон запускается без ошибок строгих глобалов и работает по панели (задачи 2, 4).
2. Выгрузка в логе оборвана (игра упала посреди записи) или в лог попали две выгрузки и строки старой сессии с тем же номером → берётся последняя полная выгрузка в конце файла; строки разной кодировки читаются (задача 1).
3. Посреди боя переставили умение, сменили клавишу или убрали умение с панели → бот ничего не жмёт, пока не прочтёт новую выгрузку; убранное умение пропускается со статусом «нет на панели»; бой при этом не закрывается (задачи 5, 6).
4. Эффектов так много, что полоса не помещается в окно → полоса никогда не шире окна, первыми отброшены чужие эффекты на цели, потом чужие на себе; бот читает полосу любой длины (задача 3).
5. Пользователь поправил `rotation.start.toml` или сохранил его с ошибкой → файл никогда не перезаписывается; при ошибке бот пишет, где ошибка, и не бьёт (не подменяет молча ротацией из `config.toml`) (задача 8).

---

### Task 1: Чтение лога и разбор выгрузки каталога

**Files:**
- Create: `aobot/modslog.py`, `aobot/catalog.py`
- Modify: `aobot/stats.py` (`kind_names` читает через `modslog.read_lines`)
- Test: `tests/test_modslog.py`, `tests/test_catalog.py`

**Interfaces:**
- Produces: `modslog.decode_line(raw: bytes) -> str` (UTF-8, иначе cp1251); `modslog.read_lines(path) -> list[str]` (без префикса `[время][UserAddon/...]Info: ` — функция `modslog.message(line) -> str` его срезает; `[]` при OSError); `modslog.LogTail(path)` с методом `new_lines() -> list[str]` (читает только дописанное с прошлого вызова; если файл стал короче — читает с начала).
- Produces: формат строки каталога `BOTCAT\t<gen>\t<TAG>\t<k>=<v>\t…` (значения экранированы: `\\`, `\t`, `\n`, `\r`); теги и поля:
  - `BEGIN`: `v=1`, `session=<мс от старта аддона при первой выгрузке>`;
  - `SPELL`: `name`, `sys`, `desc`, `params` (`var0=23.1292;var1=…`), `cd_ms`, `cast_ms`, `channel`, `harmful`, `helpful`, `target`, `range`, `nogcd` (0/1);
  - `SLOT`: `slot` (1..36), `kind` (`spell|item|mount|emote|other`), `name`, `keys` (как отдаёт игра, части через `+`, напр. `ALT+1`; пусто — нет клавиши);
  - `PASSIVE`: `name`, `desc`;
  - `TALENT`: `field` (0 — базовые, 1..3 — поля вех), `row`, `col`, `rank`, `name`, `desc`, `src` (`ability|spell|raw`);
  - `RES`: `name` (`blood`), `max`;
  - `END`: `count` (число строк между `BEGIN` и `END`).
- Produces: dataclasses в `catalog.py`: `SpellInfo(name, sys, desc, params: dict[str, float], cd_ms: int, cast_ms: int, channel: bool, harmful: bool, helpful: bool, target: int, range: float, nogcd: bool)`, `SlotInfo(slot: int, kind: str, name: str, keys: str, key: Optional[str])`, `PassiveInfo(name, desc)`, `TalentInfo(field, row, col, rank, name, desc, src)`, `Catalog(gen: int, session: str, spells: dict[str, SpellInfo], slots: dict[int, SlotInfo], passives: list, talents: list, resource: Optional[tuple[str, int]])`; `catalog.parse_dumps(lines: list[str]) -> list[Catalog]` (только полные, в порядке файла); `catalog.latest(lines, gen: Optional[int] = None) -> Optional[Catalog]` (последняя полная, при `gen` — последняя с этим номером); `catalog.game_key(keys: str) -> Optional[str]` (имя клавиши игры → имя `aobot.keys`); `catalog.keys_from_user_cfg(text: str) -> dict[int, str]` (слот → `keys` из `Personal\user.cfg`, запасной источник); `Catalog.to_json() -> str`, `Catalog.from_json(text) -> Catalog`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_modslog.py
def test_decode_line_utf8_and_cp1251(self):
    self.assertEqual(decode_line("умение".encode("utf-8")), "умение")
    self.assertEqual(decode_line("Атака".encode("cp1251")), "Атака")

def test_message_strips_prefix(self):
    line = "[19:24:29][UserAddon/BotBridge: 1.0 (build 1)]Info: BOTCAT\t1\tEND\tcount=0"
    self.assertEqual(message(line), "BOTCAT\t1\tEND\tcount=0")

def test_log_tail_reads_only_new_and_restarts_on_truncate(self):   # tmp-файл
    # записали 2 строки -> new_lines() == 2 строки; дописали 1 -> == [та 1];
    # перезаписали файл короче -> снова читает с начала

# tests/test_catalog.py — строки собираются хелпером dump(gen, *rows)
def test_parse_full_dump(self):
    cat = latest(dump(3, ("SPELL", {"name": "Вирус", "cd_ms": "0", "cast_ms": "0", "nogcd": "0",
                                    "params": "var0=23.1292",
                                    "desc": "…каждую секунду в течение 9 сек."}),
                         ("SLOT", {"slot": "4", "kind": "spell", "name": "Вирус", "keys": "ALT+1"}),
                         ("RES", {"name": "blood", "max": "5"})))
    self.assertEqual(cat.gen, 3)
    self.assertEqual(cat.spells["Вирус"].params, {"var0": 23.1292})
    self.assertEqual(cat.slots[4].key, "alt+1")
    self.assertEqual(cat.resource, ("blood", 5))

def test_cut_dump_is_ignored_and_previous_used(self):          # RF 2
    lines = dump(1, …) + dump(2, …)[:-1]        # у второй нет END
    self.assertEqual(latest(lines).gen, 1)

def test_count_mismatch_is_ignored(self):                       # RF 2
def test_same_gen_from_older_session_loses_to_newer(self):      # RF 2
    lines = dump(1, …, session="100") + dump(1, …, session="200")
    self.assertEqual(latest(lines, gen=1).session, "200")

def test_escaping_round_trip(self):            # таб, перевод строки, обратный слэш в desc

def test_game_key_names(self):
    self.assertEqual(game_key("1"), "1")
    self.assertEqual(game_key("ALT+-"), "alt+-")
    self.assertEqual(game_key("CTRL+="), "ctrl+=")
    self.assertEqual(game_key("NUM_ENTER"), "numenter")
    self.assertEqual(game_key("PG_UP"), "pageup")
    self.assertIsNone(game_key(""))
    self.assertIsNone(game_key("+ANY+MW"))        # колесо мыши — не клавиша

def test_keys_from_user_cfg(self):     # фрагмент key_bindings/mission_actions из user.cfg
    self.assertEqual(keys_from_user_cfg(USER_CFG)[13], "ALT+1")

def test_json_round_trip(self):
    self.assertEqual(Catalog.from_json(cat.to_json()), cat)
```

`USER_CFG` в тесте — настоящий фрагмент из `Personal\user.cfg`:
```
t_b mission_actions
t_b action_01
t_b 0
key=L"1"
t_e 0
t_e action_01
t_b action_13
t_b 0
key=L"ALT+1"
t_e 0
t_e action_13
t_e mission_actions
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_modslog tests.test_catalog -v`
Expected: FAIL (`ModuleNotFoundError: aobot.modslog`)

- [ ] **Step 3: Implement `aobot/modslog.py` and `aobot/catalog.py`**

`game_key`: части по `+`, в нижний регистр; переименования `NUM_ENTER→numenter`, `PG_UP→pageup`, `PG_DOWN→pagedown`, `NUM_0..9→num0..9`; если какая-то часть не в `keys.SCANCODES` (в том числе `ANY`, `MW`) — `None`. `kind_names` в `stats.py` перевести на `read_lines`/`message` без изменения поведения (его тесты остаются зелёными).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -t .`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add aobot/modslog.py aobot/catalog.py aobot/stats.py tests/test_modslog.py tests/test_catalog.py
git commit -m "feat: mods.txt tail reader and BOTCAT catalog parser"
```

---

### Task 2: Аддон пишет выгрузку каталога

**Files:**
- Create: `addon/BotBridge/Scripts/Catalog.lua`
- Modify: `addon/BotBridge/AddonDesc.(UIAddon).xdb` (скрипт после `Collect.lua`), `addon/BotBridge/Scripts/Main.lua` (события, отложенная выгрузка), `addon/BotBridge/Scripts/Config.lua` (убрать `BOT_SPELLS`)
- Test: `tests/test_lua_catalog.py`, `tests/test_lua_main.py` (`ORDER`)

**Interfaces:**
- Consumes: формат `BOTCAT` из задачи 1 (тест разбирает вывод Lua через `catalog.latest`).
- Produces (Lua): `BotCatalogDump(gen, log)` — пишет одну выгрузку функцией `log(text)` и возвращает число строк; `BotSlotCache()` → таблица `[1..36] = { kind =, name =, spellId = }` (тот же разбор слотов, что в выгрузке); `BOT_STATE.catalog_gen` (0..255, растёт на 1 при каждой выгрузке); `BOT_STATE.slots` — последний кэш слотов.
- Produces (Main.lua): `EVENT_AVATAR_CREATED`, `EVENT_SPELLBOOK_CHANGED`, `EVENT_ACTION_PANEL_CHANGED`, `EVENT_TALENTS_CHANGED`, `EVENT_BINDING_CHANGED` только ставят флаг «нужна выгрузка»; выгрузка делается в `EVENT_SECOND_TIMER` (не чаще раза в секунду): сначала `BOT_STATE.slots = BotSlotCache()`, потом `catalog_gen + 1`, потом `BotCatalogDump`.

Как аддон достаёт данные (каждый вызов — через `safe`, ошибки — в `BOT_API_ERRORS`):
- умения книги: `avatar.GetSpellBook()`, `spellLib.GetDescription(id)` (имя, sysName, описание — через `userMods.FromValuedText`, если это ValuedText, иначе `FromWString`), `spellLib.GetDescriptionParams`, `spellLib.GetCurrentValues` (`predictedCooldown`, `prepareDuration`, `range`), `spellLib.GetProperties` (`isChanneled`, `isHarmful`, `isHelpFul`, `targetType`), `spellLib.GetCooldown(id).ignoreGlobalCooldown`;
- слоты: `avatar.GetActionInfo(i)` для `i = 0..35` (слот `i + 1`); `type == ACTION_TYPE_SPELL` → сначала `spellLib.GetDescription(info.id)`, если `nil` — `avatar.GetSpellObjectInfo(info.id)` и поиск по имени в книге; клавиша — `binding.GetBind("mission_actions", string.format("action_%02d", i + 1))`, первая привязка `keys[0]`, её части через `+`;
- пассивки: `avatar.GetAbilities()` + `avatar.GetAbilityInfo`;
- вехи: `avatar.GetBaseTalentTableSize`/`GetBaseTalentInfo`, `avatar.GetFieldTalentTableSize`/`GetFieldTalentInfo` для полей 1..3 — только изученные; текст текущего ранга: `ranks[currentRank + 1].abilityId` → `avatar.GetAbilityInfo(id).description` (`src=ability`), иначе `spellId` → `spellLib.GetDescription(id).description` (`src=spell`), иначе `ranks[…].desc` (`src=raw`);
- ресурс: `avatar.GetNecromancerBloodPool()` → `RES name=blood max=<maxValue>`; нет функции или `nil` — строки `RES` нет.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_lua_catalog.py — заглушки API как в test_lua_collect.py: книга из 3 умений
# («Вирус» nogcd=0, «Дыхание смерти» ignoreGlobalCooldown=true, «Атака»),
# слоты 0 -> «Вирус», 12 -> «Дыхание смерти», 5 -> предмет, остальные nil;
# GetBind: action_01 -> {[0]={[0]="1"}}, action_13 -> {[0]={[0]="ALT",[1]="1"}}
def test_dump_parses_in_python(self):
    cat = catalog.latest(lua_dump_lines(gen=7))
    self.assertEqual(cat.gen, 7)
    self.assertEqual(cat.slots[1].name, "Вирус")
    self.assertEqual(cat.slots[13].key, "alt+1")
    self.assertTrue(cat.spells["Дыхание смерти"].nogcd)
    self.assertEqual(cat.slots[6].kind, "item")

def test_spell_object_fallback(self):   # GetDescription(info.id) = nil, GetSpellObjectInfo даёт имя
def test_talent_text_prefers_ability(self):   # src == "ability", desc с числами
def test_talent_raw_when_no_ids(self):        # src == "raw"
def test_missing_api_does_not_break_dump(self):   # нет binding, нет GetAbilities -> выгрузка полная, keys пусты
def test_no_blood_pool_means_no_res_line(self):

# tests/test_lua_main.py
def test_works_with_old_config_lua(self):                        # RF 1
    # Config.lua из коммита плана 1 (с BOT_SPELLS) подкладывается вместо текущего;
    # три тика + EVENT_SECOND_TIMER проходят без ошибок, в LOG есть строки BOTCAT
def test_dump_is_debounced_to_second_timer(self):
    # 5 событий EVENT_ACTION_PANEL_CHANGED подряд -> до EVENT_SECOND_TIMER выгрузок нет,
    # после него ровно одна, BOT_STATE.catalog_gen вырос на 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_lua_catalog tests.test_lua_main -v`
Expected: FAIL (нет `Catalog.lua`)

- [ ] **Step 3: Implement `Catalog.lua`, события в `Main.lua`, убрать `BOT_SPELLS` из `Config.lua` и `resolveSpells`/`dbgSpells` из `Main.lua`**

Отладку ГКД (`BOT_DEBUG_GCD`) оставить, но без `BOT_SPELLS`: она печатает кулдауны умений из `BOT_STATE.slots`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -t .`
Expected: OK

- [ ] **Step 5: Живая проверка (проводит пользователь)**

Попросить пользователя: `python -m aobot install`, затем перезагрузить аддон в игре (перезайти персонажем) и через 5 секунд выполнить

```bash
python -c "from aobot import modslog, catalog; c = catalog.latest([modslog.message(l) for l in modslog.read_lines(r'D:\VK Play\Аллоды Онлайн\Personal\Logs\mods.txt')]); print(c.gen, len(c.spells), {s: (i.name, i.keys) for s, i in sorted(c.slots.items())}, c.resource, [(t.name, t.src, t.desc[:60]) for t in c.talents[:5]])"
```

Затем переставить одно умение на панели, подождать 2 секунды, выполнить ещё раз. Записать в отчёт задачи:
- номер выгрузки вырос, слоты и клавиши совпадают с панелью в игре;
- через сколько секунд после перестановки новая выгрузка появилась в `mods.txt` (задержка лога — риск из дизайна);
- какой `src` у вех и есть ли в их тексте числа (если везде `raw` с `<r name=…>` — калькулятор в задаче 7 помечает вехи «не понято», это ожидаемо);
- не обрезаны ли длинные описания (сравнить с подсказкой в игре).
Если клавиши пусты — переключить источник клавиш на `keys_from_user_cfg` (бот читает `Personal\user.cfg`, задача 6) и записать это в отчёт.

- [ ] **Step 6: Commit**

```bash
git add addon/BotBridge tests/test_lua_catalog.py tests/test_lua_main.py
git commit -m "feat(addon): catalog dump to mods.txt on spellbook/panel/talent/binding change"
```

---

### Task 3: Протокол v3 — полоса переменной длины

**Files:**
- Modify: `aobot/protocol.py` (докстринг-раскладка, `VERSION`, `GameState`, `Effect`, `encode_bytes`, `decode_bytes`, `encode_cells`, `read_strip`), `addon/BotBridge/Scripts/Packer.lua`, `aobot/reader.py`, `aobot/capture.py`, `aobot/__main__.py` (`describe`)
- Modify (чтобы набор тестов оставался зелёным): `aobot/rotation.py` (поле `RotationStep.slot`), `aobot/policy.py` (`legal_steps`), `aobot/assist.py` (проверка «нет умений»), `tests/test_assist.py`, `tests/test_policy.py`
- Test: `tests/test_protocol.py`, `tests/test_lua_packer.py`, `tests/test_reader.py`

**Interfaces:**
- Produces: раскладка v3 (big-endian):

```
0      версия (3)
1      seq
2-3    длина данных L (без контрольной суммы)
4      флаги 1 (как в v2)
5      флаги 2: b0 цель в ближнем бою, b1 враждебна, b2 помечена другим,
                b3 цель кастует, b4 цель IsGreat, b5 цель HasBossPlate,
                b6 ресурс известен
6      здоровье %     7  мана %     8  здоровье цели %   (255 — неизвестно)
9-10   дистанция, дм (0xFFFF — неизвестно)
11-12  ГКД, мс/10
13-15 X, 16-18 Y, 19-21 Z — дм, знаковое 24 бита
22-23  направление, рад*10000
24-25  id цели       26-27  вид цели
28-29  ресурс сейчас 30-31  ресурс максимум
32     номер выгрузки каталога (0..255)
33     врагов в бою рядом (255 — неизвестно)
34-35  остаток каста цели, мс/10      36-37  хэш названия каста цели
38-42  маска готовых слотов: 36 бит, бит i — слот i+1
43-78  кулдаун слотов 1..36, по байту:
         0 — нет кулдауна; 1..200 — ceil(мс/100); 201..254 — 20 с + (b-200) с;
         255 — в слоте нет умения / неизвестно
79     n — эффектов на себе      80  m — эффектов на цели
81…    n+m эффектов по 5 байт: хэш названия u16;
         байт: b7 «наложен мной», b0-6 стаки (до 127);
         остаток u16 в 100 мс (0xFFFF — бессрочный/неизвестно)
L, L+1 Fletcher-16 по байтам 0..L-1; дальше нули до кратного 3
```

- Produces: `protocol.VERSION == 3`, `protocol.FIXED_LEN == 81`, `protocol.SLOTS == 36`, `protocol.EFFECT_LEN == 5`; `Effect(kind: int, stacks: int, mine: bool, remaining_ms: Optional[int])` (frozen); в `GameState` вместо `spells_known`/`spells_ready`: `target_casting`, `target_great`, `target_boss: bool`, `resource`, `resource_max: Optional[int]`, `catalog_gen: int`, `enemies_near: Optional[int]`, `target_cast_ms: int`, `target_cast_kind: int`, `slots_ready: int`, `slot_cd_ms: tuple[Optional[int], ...]` (36 значений, после декодирования — нижняя граница интервала: `b*100` или `20000+(b-200)*1000`), `effects_self`, `effects_target: tuple[Effect, ...]`; методы `slot_ready(i: int) -> bool` (i с 0), `target_effect(kind: int, mine: bool = True) -> Optional[Effect]`, `self_effect(kind, mine=False)`.
- Produces: `protocol.encode_bytes(st, max_cells: Optional[int] = None) -> bytes` — если полоса не влезает в `max_cells` ячеек (включая SYNC и CALIB), эффекты отбрасываются по одному в порядке: последний чужой на цели → последний чужой на себе → последний на цели → последний на себе; `protocol.cells_for(body_len) -> int` (`body_len` — данные с контрольной суммой; результат `2 + ceil(body_len / 3)`, вместе с SYNC и CALIB); `protocol.encode_cells(st, max_cells=None)` — то же отбрасывание; `protocol.read_strip(get, geo, width: int) -> GameState` — сначала читает ячейку 2 (версия, seq, L), считает число ячеек, если полоса выходит за `width` → `DecodeError("полоса шире захвата")`.
- Produces (Lua): `BotPack(st, maxCells) -> bytes` с тем же правилом отбрасывания и возвратом `dropped` вторым значением; поля `st` — как у `GameState` (эффекты — массивы `{ kind =, stacks =, mine =, remaining_ms = }`).
- Produces: `ScreenGrabber.want_width` (по умолчанию 160, BitBlt захватывает `min(want_width, ширина окна)`; буфер — под 3840 px); `StateReader` после удачного чтения ставит `grab.want_width = geo.x + geo.cell * (cells + 1)` (если у `grab` есть такой атрибут) и при `DecodeError("полоса шире захвата")` расширяет захват и читает ещё раз.
- Produces (временная привязка до задачи 5): `RotationStep.slot: Optional[int] = None` (слот с 0, не задаётся в TOML); `legal_steps` берёт шаги с `slot is not None and st.slot_ready(slot)`; `Assist` вместо `spells_known == 0` проверяет «нет шагов со слотом» (`STATUS_NO_SPELLS`). В тестах помощника шаги создаются с `slot=…`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_protocol.py
def test_v3_constants(self):
    self.assertEqual((protocol.VERSION, protocol.FIXED_LEN, protocol.SLOTS), (3, 81, 36))

def test_round_trip_with_effects(self):
    st = sample_state(effects_self=(Effect(101, 3, True, 4500),),
                      effects_target=(Effect(202, 50, True, None), Effect(303, 1, False, 100)),
                      slots_ready=(1 << 35) | 1, resource=3, resource_max=5,
                      catalog_gen=200, target_casting=True, target_cast_ms=1230)
    self.assertEqual(decode_bytes(encode_bytes(st)), st)

def test_cooldown_byte_codes(self):
    # 0 -> 0; 50 -> 100 (1 байт); 20000 -> 20000; 20500 -> 21000; 10**7 -> 74000; None -> None

def test_length_field_and_cells(self):
    body = encode_bytes(sample_state())
    self.assertEqual(body[2] << 8 | body[3], 81)
    self.assertEqual(len(encode_cells(sample_state())), 2 + 28)

def test_trim_drops_foreign_target_effects_first(self):           # RF 4
    st = sample_state(effects_self=(E(1, mine=False),), effects_target=(E(2, mine=True), E(3, mine=False)))
    got = decode_bytes(encode_bytes(st, max_cells=cells_for(81 + 2 * 5 + 2)))
    self.assertEqual([e.kind for e in got.effects_target], [2])
    self.assertEqual([e.kind for e in got.effects_self], [1])

def test_strip_never_wider_than_limit(self):                       # RF 4
    st = sample_state(effects_target=tuple(E(i, mine=True) for i in range(500)))
    self.assertLessEqual(len(encode_cells(st, max_cells=120)), 120)

# tests/test_lua_packer.py — check(st) сравнивает BotPack(st) c encode_bytes
def test_effects_match_python(self):
def test_trimming_matches_python(self):      # тот же st и maxCells — те же байты и dropped
def test_36_bit_mask_matches_python(self):   # slots_ready = 2**36 - 1

# tests/test_reader.py
def test_reads_strip_of_any_length(self):     # полоса с 300 эффектами из фальшивого get_pixel
def test_widens_capture_when_strip_is_wider(self):   # grab.want_width растёт, второе чтение удачно
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_protocol tests.test_lua_packer tests.test_reader -v`
Expected: FAIL (`VERSION` 2, нет `Effect`)

- [ ] **Step 3: Implement v3 in `protocol.py` and `Packer.lua`; `reader.py`, `capture.py`; `describe` в `__main__.py`**

`describe` вместо «умения найдено 01111» показывает `слоты готовы 1 3 13`, `ресурс 3/5`, `эффекты 2/5`, `каталог #200`, у цели — `каст 1.2с`, `босс` (IsGreat или HasBossPlate). В `Packer.lua` маску 36 бит раскладывать делением на степени 2 (Lua 5.1, числа — double).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -t .`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add aobot addon/BotBridge/Scripts/Packer.lua tests
git commit -m "feat: protocol v3 — variable-length strip, slots, resource, effects"
```

---

### Task 4: Аддон собирает данные v3

**Files:**
- Modify: `addon/BotBridge/Scripts/Collect.lua` (`BotCollect`), `addon/BotBridge/Scripts/Main.lua` (`paint`, `layout`, создание ячеек по надобности, перекраска только изменившихся, лог новых эффектов и каста)
- Test: `tests/test_lua_collect.py`, `tests/test_lua_main.py`

**Interfaces:**
- Consumes: `BOT_STATE.slots` и `BOT_STATE.catalog_gen` (задача 2), `BotPack(st, maxCells)` и `BotKind` (задача 3).
- Produces: `BotCollect(seq, casting, slots)` заполняет все поля v3:
  - слоты: для каждого слота с умением `spellLib.GetCooldown(spellId).remainingMs` и `spellLib.CanRunAvatar` — готов, если `can ~= false and remaining <= gcdMs` (как в плане 1); кулдаун слота — `remaining` (если `remaining <= gcdMs` — 0); без умения — `nil` (байт 255);
  - ресурс: `avatar.GetNecromancerBloodPool()` → `value`/`maxValue`, нет — `nil`;
  - эффекты: `object.GetBuffs(id)` + `object.GetBuffInfo(buff)` → `kind = BotKind(name)`, `stacks = stackCount`, `remaining_ms = remainingMs` (`nil`, если не показывается длительность), `mine = producer.casterId == avatar.GetId()`; в каждом списке сначала свои;
  - цель: `unit.GetMobActionProgress(t)` → `target_casting`, `target_cast_ms = duration - progress`, `target_cast_kind = BotKind(name)`; `unit.IsGreat`, `unit.HasBossPlate`;
  - `enemies_near`: раз в секунду (кэш в `BOT_STATE.enemies_near`) — число юнитов `avatar.GetUnitList()` с `object.IsEnemy`, `object.IsInCombat` и `object.IsInUsageRange`;
  - `catalog_gen = BOT_STATE.catalog_gen`.
- Produces (Main.lua): `maxCells = floor(ширина окна в реальных пикселях / BOT_CELL_PX)`; недостающие ячейки создаются через `CreateChildByDesc` и размещаются в `layout`; лишние прячутся (`Show(false)`); `setColor` вызывается только если цвет ячейки изменился; если `BotPack` вернул `dropped > 0` — один раз в лог `BotBridge: эффектов больше, чем помещается в полосу`; каждый новый `kind` эффекта и каста цели — один раз в лог строкой `BotBridge: эффект <kind> = <name>`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_lua_collect.py
def test_slot_ready_and_cooldown(self):     # слот 1 cd 0 -> готов, cd 0; слот 2 cd 5000 -> не готов, 5000
def test_slot_cd_equal_gcd_is_ready(self):  # remaining == gcd -> готов, кулдаун 0
def test_empty_slot_is_nil(self):
def test_blood_pool(self):                  # value 3, maxValue 5
def test_no_blood_pool_api(self):           # функции нет -> resource nil, ошибки в BOT_API_ERRORS, сбор не упал
def test_effects_mine_first_and_fields(self):
def test_target_cast_and_boss(self):        # duration 3000, progress 1000 -> 2000; IsGreat true
def test_enemies_counted_once_per_second(self):   # GetUnitList вызван 1 раз за 20 тиков

# tests/test_lua_main.py
def test_cells_created_on_demand_and_hidden(self):   # 20 эффектов -> ячеек больше; 0 -> лишние Show(false)
def test_unchanged_cells_not_repainted(self):        # второй тик с тем же состоянием (кроме seq) — перекрашены ≤ 2 ячейки
def test_strip_fits_window(self):                    # RF 4: 1000 эффектов, окно 1280 px, ячейка 4 -> ячеек ≤ 320, в LOG одна строка про «больше, чем помещается»
def test_effect_name_logged_once(self):
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_lua_collect tests.test_lua_main -v`
Expected: FAIL

- [ ] **Step 3: Implement in `Collect.lua` and `Main.lua`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -t .`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add addon/BotBridge tests/test_lua_collect.py tests/test_lua_main.py
git commit -m "feat(addon): collect slots, blood, effects, target cast and boss for v3"
```

---

### Task 5: Ротация по названиям и привязка к панели

**Files:**
- Modify: `aobot/rotation.py`, `aobot/config.py` (разбор `[[rotation]]` вынести в `rotation.parse_steps`), `aobot/policy.py`
- Test: `tests/test_rotation.py`, `tests/test_config.py`, `tests/test_policy.py`

**Interfaces:**
- Consumes: `Catalog`, `SlotInfo.key` (задача 1), `GameState.target_effect`, `slot_ready` (задача 3), `protocol.kind_hash`.
- Produces: `RotationStep` — поля из TOML: `spell: int | str` (строка — название умения; число — старый формат, ничего не значит), `key: Optional[str] = None`, `min_target_hp`, `max_target_hp`, `self_hp_below`, `needs_melee` (как было), новые `refresh_effect: Optional[str] = None` (шаг подходит, только если своего эффекта с этим названием на цели нет или осталось ≤ `refresh_at`), `refresh_at: float = 0.0` (с), `below_stacks: Optional[int] = None` (подходит, пока своих стаков `refresh_effect` меньше), `min_resource: Optional[int] = None`; поля привязки (не из TOML): `slot: Optional[int]`, `nogcd: bool = False`, `effect_kind: int = 0`.
- Produces: `rotation.parse_steps(items: list, where: str) -> list[RotationStep]` (бросает `ConfigError`-подобное `RotationError` с номером шага; `config.py` оборачивает его в `ConfigError`); `rotation.bind(steps, cat: Catalog, busy: set[str]) -> tuple[list[RotationStep], list[str]]` — возвращает привязанные шаги (копии с `slot`, `key`, `nogcd`, `effect_kind = kind_hash(refresh_effect.encode("cp1251"))`) и предупреждения:
  - шаг с названием: слот — первый слот, где лежит это умение; клавиша — `SlotInfo.key` (явный `key` из TOML побеждает); нет на панели → «<имя>: нет на панели»; нет клавиши → «<имя>: нет клавиши»;
  - шаг с числом (старый `config.toml`): слот — тот, чья клавиша равна `key`; нет такого → «клавиша <key>: на панели такой нет»; предупреждение «<key>: spell = N больше не используется, умение — <имя в слоте>» один раз;
  - клавиша, которая целиком или частью сочетания входит в `busy` (горячая, стоп, чат) → шаг выкинут, «<имя>: клавиша <k> занята»;
  - выкинутые шаги в результат не попадают.
- Produces: `step_applies(step, st, heals)` учитывает `refresh_effect`/`refresh_at`/`below_stacks` (по `st.target_effect(step.effect_kind, mine=True)`) и `min_resource` (ресурс неизвестен → условие не выполнено); `legal_steps(rotation, st, ex, now, nogcd_only: bool = False)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rotation.py — CAT: слоты 1 «Вирус» key "1", 13 «Дыхание смерти» key "alt+1" (nogcd), 2 «Атака» key "e"
def test_bind_by_name(self):
    steps, warn = bind(parse_steps([{"spell": "Вирус"}], "t"), CAT, set())
    self.assertEqual((steps[0].slot, steps[0].key), (0, "1"))

def test_moved_spell_binds_to_new_slot(self):        # RF 3: тот же шаг, «Вирус» в слоте 5 -> slot 4
def test_removed_spell_skipped_with_warning(self):  # RF 3
    steps, warn = bind(parse_steps([{"spell": "Лихорадка"}], "t"), CAT, set())
    self.assertEqual(steps, [])
    self.assertIn("Лихорадка: нет на панели", warn)

def test_old_numeric_step_binds_by_key(self):
def test_busy_key_dropped(self):
    steps, warn = bind(parse_steps([{"spell": "Атака"}], "t"), CAT, {"e"})
    self.assertEqual(steps, [])
def test_busy_part_of_combo_dropped(self):           # busy {"alt"} выкидывает «Дыхание смерти»
def test_nogcd_flag_from_catalog(self):
def test_refresh_effect_condition(self):
    # эффекта нет -> подходит; свой с остатком 5000 мс, refresh_at 1.0 -> нет; 900 мс -> да;
    # чужой с тем же хэшем не считается
def test_below_stacks(self):
def test_min_resource_unknown_resource_not_applicable(self):
def test_parse_rejects_unknown_fields_and_bad_types(self):  # refresh_at = "x", spell = 1.5, лишнее поле

# tests/test_policy.py
def test_legal_uses_slot_ready(self):
def test_nogcd_only_filters(self):
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_rotation tests.test_policy tests.test_config -v`
Expected: FAIL

- [ ] **Step 3: Implement in `rotation.py`, `config.py`, `policy.py`**

Проверка `1 <= spell <= MAX_SPELLS` для числа убирается; проверка клавиш `[[rotation]]` против горячей, стоп и чата в `config.py` остаётся для явных `key`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -t .`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add aobot/rotation.py aobot/config.py aobot/policy.py tests
git commit -m "feat: rotation by spell name, bound to action bar slots and keys"
```

---

### Task 6: Помощник — каталог, умения без ГКД, журнал v2

**Files:**
- Create: `aobot/live.py` (`CatalogWatcher`)
- Modify: `aobot/executor.py`, `aobot/assist.py`, `aobot/journal.py`, `aobot/__main__.py` (`cmd_assist`, `assist_loop`, `--game`)
- Test: `tests/test_executor.py`, `tests/test_assist.py`, `tests/test_journal.py`, `tests/test_live.py`

**Interfaces:**
- Consumes: `modslog.LogTail`, `catalog.latest`, `keys_from_user_cfg` (задача 1); `rotation.bind` (задача 5); `GameState.catalog_gen` (задача 3).
- Produces: `Executor.offgcd_slot(st, now) -> Optional[Slot]` — `Slot(None, False)`, если `st.gcd_ms > 0`, не `st.casting` и `now >= offgcd_until`; иначе `None`. `Executor.commit_offgcd(key, now) -> Press` — `spell_retry[key] = now + press_cooldown`, `offgcd_until = now + confirm_seconds`, `Press(key, None)`; **не** трогает `spell_at`, `pending`, `frames_after_spell` (нажатие без ГКД не сдвигает расчёт следующего нажатия по ГКД).
- Produces: `Assist.set_rotation(steps: list[RotationStep], gen: int, warnings: list[str])`; `Assist.rotation_gen: Optional[int]`; в `step`: если бой идёт и `st.catalog_gen != rotation_gen` → статус `STATUS_CATALOG = "панель изменилась — читаю каталог"`, нажатий нет, бой не закрывается; `STATUS_NO_SPELLS = "нет умений ротации на панели"`, когда привязанных шагов нет. `_decide`: если `ex.slot()` есть — как раньше по всем шагам; иначе если `ex.offgcd_slot()` есть — выбор из `legal_steps(..., nogcd_only=True)` и `commit_offgcd`.
- Produces: `live.CatalogWatcher(log_path: Path, user_cfg: Path, data_dir: Path)`, метод `poll(gen: int, now: float) -> Optional[Catalog]` — не чаще раза в 0,5 с дочитывает лог (`LogTail`) и возвращает выгрузку с номером `gen`, если она появилась (последняя полная; пустые клавиши слотов дополняет из `user.cfg`); найденную сохраняет в `data_dir / "catalog.json"`. При старте `assist` первый `poll` читает лог целиком.
- Produces: журнал `"v": 2` (состояние v3 целиком, `legal` — клавиши, как раньше); `stats` читает и v1, и v2.
- Produces (`assist_loop`): каждый кадр — если `st.catalog_gen != assist.rotation_gen`, `watcher.poll(st.catalog_gen, now)`; на новой выгрузке — `rotation_for(catalog)` (задача 8; до задачи 8 — ротация из `config.toml`), `bind(…, busy={assist_key, stop_key, *chat_keys, *chat_close_keys})`, `assist.set_rotation(…)`; предупреждения печатаются отдельной строкой один раз на выгрузку. `--game` — папка игры (по умолчанию `GAME_GUESSES`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_executor.py
def test_offgcd_slot_only_during_gcd(self):          # gcd 0 -> None; gcd 600 -> Slot(None, False); каст -> None
def test_offgcd_press_does_not_move_gcd_timing(self):
    # ГКД виден, commit_offgcd("alt+1") -> slot() к концу ГКД такой же, как без этого нажатия
def test_offgcd_blocks_itself_until_confirm(self):

# tests/test_assist.py
def test_waits_for_new_catalog_mid_fight(self):     # RF 3
    a.set_rotation(STEPS, gen=5, warnings=[])
    a.step(fighting(catalog_gen=5), 0.0, True)
    self.assertEqual(a.step(fighting(seq=2, catalog_gen=6), 0.5, False), [])
    self.assertEqual(a.status, "панель изменилась — читаю каталог")
    self.assertTrue(a.active)                       # бой не закрыт
    a.set_rotation(STEPS, gen=6, warnings=[])
    self.assertTrue(a.step(fighting(seq=3, catalog_gen=6), 1.0, False))   # снова жмёт
def test_no_bound_steps_status(self):
def test_presses_nogcd_spell_during_gcd(self):      # gcd 800, готов слот «Дыхание смерти» -> Press("alt+1", None)
def test_does_not_press_gcd_spell_during_gcd(self):

# tests/test_live.py
def test_poll_finds_dump_with_gen(self):            # tmp mods.txt: выгрузка 1, потом дописана 2 -> poll(2) находит
def test_poll_rate_limited(self):                   # второй poll через 0.1 с не читает файл
def test_empty_keys_filled_from_user_cfg(self):
def test_saves_catalog_json(self):

# tests/test_journal.py
def test_v2_record_has_effects(self):
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_executor tests.test_assist tests.test_live tests.test_journal -v`
Expected: FAIL

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -t .`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add aobot tests
git commit -m "feat: assist follows catalog changes, presses no-GCD spells during GCD"
```

---

### Task 7: Калькулятор стартовой ротации

**Files:**
- Create: `aobot/calc.py`, `tests/fixtures/necro_catalog.json`
- Test: `tests/test_calc.py`

**Interfaces:**
- Consumes: `Catalog`, `SpellInfo` (задача 1), `RotationStep` (задача 5).
- Produces: `calc.GCD_SECONDS = 1.0`; `calc.HEAL_BELOW = 40`; `SpellModel(name, kind: str` (`direct|dot|heal|skip`)`, value: float, busy_s: float, per_s: float, ticks: int, duration_s: float, stacks_max: Optional[int], resource_gain: int, nogcd: bool, multiplier: float, notes: list[str], reason: str)`; `calc.model_spell(sp: SpellInfo) -> SpellModel`; `calc.multipliers(cat: Catalog) -> tuple[dict[str, float], list[str], list[str]]` (имя умения → множитель; понятые и непонятые тексты пассивок и вех); `calc.build(cat: Catalog) -> CalcResult(steps: list[RotationStep], models: list[SpellModel], understood: list[str], not_understood: list[str])`.

Правила (тексты — из настоящей выгрузки, см. фикстуру):
- перед разбором из текста убираются `[ValuedObject]:`, html-теги и приклеенные в начале категории «Направленная атака», «Периодический урон»;
- `dot`: «N ед. урона K раз (в течение|за) D сек» → `value = N*K` (+ мгновенный урон, если есть «мгновенно наносящ… M ед. урона»), `ticks = K`, `duration_s = D`; «N ед. урона каждую секунду в течение D сек» → `value = N*D`, `ticks = D`;
- `direct`: первое «N ед. урона» вне `dot`;
- `heal`: «восстанавливает N здоровья»;
- `resource_gain`: «Восполняет запас крови на N капл»;
- `stacks_max`: «суммируется до N раз» (рост урона от стаков не считается — заметка «стаки не посчитаны»);
- `nogcd`: из каталога или текст «Игнорирует общее время восстановления»;
- `skip` с причиной: не `harmful` и не лечение («не боевое»); «жертвуя … здоровья» («тратит здоровье — решать вам»); нет чисел («не понято»);
- `busy_s = max(cast_ms/1000, GCD_SECONDS)`, для `nogcd` — 0; `per_s = value*multiplier/busy_s` (для `nogcd` — `value*multiplier`);
- множители: «урон умения «X» увеличивается на N%», «усиливает эффект «X» на N%» → `×(1+N/100)` к X (несколько — перемножаются); текст с `<r name=` или `<t href=` и вехи без чисел — в `not_understood`;
- порядок шагов: лечения (`self_hp_below = HEAL_BELOW`) → умения без ГКД по `per_s` → `dot` по `per_s` с `refresh_effect = имя умения`, `refresh_at = GCD_SECONDS` → `direct` по `per_s`; при равенстве — по имени;
- в ротацию идут только умения, лежащие на панели; сильные умения из книги без слота — в `understood` с пометкой «нет на панели».

Фикстура `tests/fixtures/necro_catalog.json` — `Catalog` с умениями (описание, `cd_ms`, `cast_ms`, флаги — дословно из выгрузки 2026-11-17):

| Умение | cd_ms | cast_ms | harmful | nogcd | описание (фрагмент, дословно) |
|---|---|---|---|---|---|
| Яростная атака | 30000 | 0 | 1 | 0 | По приказу некроманта страж бросается к врагу, нанося ему 36.57 ед. урона и делая [ValuedObject]: уязвимым на 6 сек. |
| Дыхание смерти | 1000 | 0 | 1 | 1 | Направленная атакаТёмное заклятие наносит противнику 71.49 ед. урона и [ValuedObject]: замедляет его на 1 сек.Игнорирует общее время восстановления умений. |
| Вампиризм | 0 | 1333 | 1 | 0 | Направленная атакаВысасывает жизненную силу противника, нанося ему 37.85 ед. урона. Восполняет запас крови на 1 каплю. |
| Кровавый пир | 6000 | 4000 | 1 | 0 | Некромант, применяет заклинание, жертвуя 10% от своего максимального здоровья в секунду и наносит 107 ед. урона всем противникам в указанной области радиусом 8 м в течение 4 сек. |
| Вирус | 0 | 0 | 1 | 0 | Периодический уронВводит в кровь цели мощный вирус, наносящий ей 23.13 ед. урона каждую секунду в течение 9 сек. |
| Касание смерти | 7000 | 0 | 1 | 0 | Некромант взывает к смерти, чтобы покарать врага, нанося ему 80.95 ед. урона. |
| Лихорадка | 0 | 0 | 1 | 0 | Направленная атакаПериодический уронНасылает страшную болезнь на противника, мгновенно наносящую 28.05 ед. урона, а также дополнительно 23.13 ед. урона 10 раз в течение 8 сек. |
| Нейротоксин | 0 | 0 | 1 | 0 | Периодический уронОтравляет противника, нанося ему 1.47 ед. урона 12 раз за 6 сек. Эффект суммируется до 50 раз. Урон увеличивается на 30% за каждый уровень эффекта. |
| Алчные тени | 6000 | 0 | 1 | 0 | Периодический уронНапускает на противника злобные тени, наносящие 25.23 ед. урона 10 раз в течение 10 сек. |
| Изъятие жизни | 0 | 1000 | 1 | 0 | Направленная атакаИстощает жизненную силу противника, нанося ему 50.46 ед. урона. Восполняет запас крови на 1 каплю. |
| Сила Света | 120000 | 0 | 0 | 0 | Мгновенно восстанавливает 35982 здоровья. |
| Контракт наёмников | 10000 | 3000 | 0 | 0 | Призвать капитана наёмников, у которого можно нанять бойцов для прохождения астральных островов и территорий, рассчитанных на группу. |
| Атака | 1840 | 0 | 1 | 0 | Атака |

Слоты фикстуры: все умения таблицы, кроме «Контракт наёмников», лежат на панели (слоты 1–12, клавиши 1–0, -, =). Вехи: одна с понятным текстом «Урон умения «Вирус» увеличивается на 20%.» и одна сырая `Дополнительно усиливает эффект <tip_base>«<t href="cbc4020000000000"/>»</tip_base> на <tip_green><r name="Damage_Up"/>%</tip_green>.`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_calc.py
def test_dot_per_tick(self):
    m = model_spell(CAT.spells["Алчные тени"])
    self.assertEqual((m.kind, m.ticks, m.duration_s), ("dot", 10, 10.0))
    self.assertAlmostEqual(m.value, 252.3)
def test_dot_per_second(self):      # Вирус: 23.13*9 = 208.17
def test_dot_with_instant_part(self):   # Лихорадка: 28.05 + 231.3 = 259.35
def test_cast_time_counts_as_busy(self):   # Вампиризм: busy 1.333, per_s ≈ 28.40
def test_nogcd_flag_and_busy_zero(self):   # Дыхание смерти
def test_resource_gain(self):              # Изъятие жизни: resource_gain 1
def test_stacks_noted(self):               # Нейротоксин: stacks_max 50, в notes «стаки не посчитаны»
def test_health_cost_skipped(self):        # Кровавый пир: kind skip, reason «тратит здоровье — решать вам»
def test_non_combat_skipped(self):         # Контракт наёмников
def test_no_numbers_not_understood(self):  # Атака
def test_heal(self):                       # Сила Света: heal, value 35982
def test_talent_multiplier_applied(self):  # множитель Вируса 1.2; сырая веха в not_understood
def test_rotation_order(self):
    names = [s.spell for s in build(CAT).steps]
    self.assertEqual(names, ["Сила Света", "Дыхание смерти", "Лихорадка", "Алчные тени",
                             "Вирус", "Нейротоксин", "Касание смерти", "Изъятие жизни",
                             "Яростная атака", "Вампиризм"])
def test_dot_steps_have_refresh(self):     # Вирус: refresh_effect "Вирус", refresh_at 1.0
def test_heal_threshold(self):             # Сила Света: self_hp_below 40
def test_only_panel_spells(self):          # убрать «Касание смерти» из слотов -> его нет в steps, в understood «нет на панели»
```

(Порядок `test_rotation_order`: Вирус с множителем 1.2 → 249.8 — после Алчных теней 252.3.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_calc -v`
Expected: FAIL

- [ ] **Step 3: Implement `aobot/calc.py`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -t .`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add aobot/calc.py tests/test_calc.py tests/fixtures/necro_catalog.json
git commit -m "feat: starting rotation calculator from spell and talent descriptions"
```

---

### Task 8: Файл стартовой ротации (вариант А) и выбор ротации

**Files:**
- Create: `aobot/rotfile.py`
- Modify: `aobot/__main__.py` (`cmd_assist`/`assist_loop` берут ротацию через `rotation_for`), `.gitignore` (`rotation.auto.toml`)
- Test: `tests/test_rotfile.py`

**Interfaces:**
- Consumes: `calc.build` (задача 7), `rotation.parse_steps` (задача 5), `AppConfig.combat.rotation`.
- Produces: `rotfile.render(result: CalcResult, cat: Catalog) -> str` — заголовок:
  ```
  # Стартовая ротация — посчитана ботом <дата>, каталог #<gen>.
  # Можно править: после правки бот этот файл больше не перезаписывает,
  # свежий расчёт кладёт в rotation.auto.toml.
  # auto-hash: <первые 16 hex sha256 тела>
  # Понято: …        (по строке на умение: значение, урон/с, заметки)
  # Не понято: …
  ```
  затем `[[rotation]]` с комментарием над каждым шагом (`# Лихорадка: 259.4 урона за 8 с, 259.4/с`); `rotfile.is_untouched(text) -> bool` (хэш в заголовке совпадает с телом; нет заголовка — `False`); `rotfile.write(root: Path, text: str) -> str` — нет `rotation.start.toml` или он нетронут → пишет его, `"start"`; иначе пишет `rotation.auto.toml`, `"auto"` (тронутый файл не меняется никогда); `rotfile.load_text(text, where="rotation.start.toml") -> list[RotationStep]` и `rotfile.load(path)` (бросают `RotationError` с путём и номером шага; файл без шагов — `[]`); `rotfile.rotation_for(root: Path, cfg: AppConfig) -> tuple[list[RotationStep], str]` — источник: `rotation.start.toml` (если в нём есть шаги) → `[[rotation]]` из `config.toml` → `([], "нет ротации")`; ошибка в `rotation.start.toml` → `RotationError` (не подменяется ротацией из `config.toml`).
- Produces (`assist_loop`): на новой выгрузке — `calc.build`, `rotfile.write`, `rotfile.rotation_for`; печатает источник («ротация: rotation.start.toml (посчитана ботом)» / «… (правлена вами; свежий расчёт — rotation.auto.toml)» / «config.toml»); `RotationError` → печать ошибки, бот не бьёт до исправления (статус `STATUS_NO_SPELLS`), но продолжает следить за каталогом; `([], …)` → «нужна ротация: rotation.start.toml или [[rotation]] в config.toml».

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rotfile.py
def test_render_parses_back(self):
    steps = rotfile.load_text(render(build(CAT), CAT))
    self.assertEqual([s.spell for s in steps], [s.spell for s in build(CAT).steps])
def test_untouched_detected(self):
def test_edit_detected(self):          # поменяли один символ в теле -> is_untouched False
def test_write_overwrites_untouched(self):    # -> "start", файл новый
def test_write_never_touches_edited(self):    # RF 5: правленый файл байт в байт тот же, создан rotation.auto.toml, -> "auto"
def test_write_creates_when_missing(self):
def test_source_order(self):          # start с шагами > config.toml > пусто
def test_empty_start_falls_back_to_config(self):
def test_broken_start_is_error_not_fallback(self):   # RF 5: синтаксическая ошибка -> RotationError с путём
def test_render_comments_list_not_understood(self):
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_rotfile -v`
Expected: FAIL

- [ ] **Step 3: Implement `aobot/rotfile.py`, подключить в `assist_loop`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -t .`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add aobot/rotfile.py aobot/__main__.py .gitignore tests/test_rotfile.py
git commit -m "feat: rotation.start.toml written by calculator, user edits preserved"
```

---

### Task 9: Команда `python -m aobot catalog`

**Files:**
- Modify: `aobot/__main__.py` (`cmd_catalog`, парсер), `aobot/catalog.py` (`format_report`)
- Test: `tests/test_catalog_report.py`

**Interfaces:**
- Consumes: `CatalogWatcher` (задача 6), `calc.build` (задача 7), `rotfile` (задача 8), `rotation.bind` (задача 5).
- Produces: `catalog.format_report(cat: Catalog, result: CalcResult, bound: list[RotationStep], warnings: list[str], source: str) -> str` с разделами:
  1. `Каталог #<gen>`, ресурс (`кровь, максимум 5` / `не читается`);
  2. `Панель`: слот, клавиша (или «нет клавиши»), что лежит, кулдаун, каст, «без ГКД»;
  3. `Умения`: имя, что понято (`периодический 259.4 за 8 с`, `урон/с`), в ротации ли или причина;
  4. `Пассивки и вехи`: понято / не понято (текст обрезан до 100 символов);
  5. `Ротация`: источник, предупреждения привязки, итоговый порядок с клавишами.
- Produces: `python -m aobot catalog [--game DIR] [--data DIR]` — читает лог целиком, берёт последнюю полную выгрузку, сохраняет `data/catalog.json`, обновляет ротацию по `rotfile.write` (как помощник) и печатает отчёт; выгрузки нет — «Выгрузки каталога в mods.txt нет: включите запись ошибок дополнений и перезайдите персонажем», код 1.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_catalog_report.py — на фикстуре задачи 7
def test_sections_present(self):
def test_panel_shows_keys_and_nogcd(self):       # «13  alt+1  Дыхание смерти … без ГКД»
def test_skipped_spell_has_reason(self):         # «Кровавый пир … тратит здоровье — решать вам»
def test_not_understood_talent_listed(self):
def test_missing_from_panel_warning(self):
def test_cli_without_dump_returns_1(self):       # main(["catalog", "--game", tmp]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_catalog_report -v`
Expected: FAIL

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -t .`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add aobot/__main__.py aobot/catalog.py tests/test_catalog_report.py
git commit -m "feat: catalog command — what the bot read, understood and did not"
```

---

### Task 10: Документация, настройки и живая проверка

**Files:**
- Modify: `README.md` (протокол v3, ячейки, `catalog`, `rotation.start.toml`, отказ от `BOT_SPELLS`), `config.example.toml` (`[[rotation]]` — запасной, `spell = "название"`), `config.toml` (устаревший `[[rotation]]` убрать: ротацию даёт калькулятор), `docs/superpowers/roadmap.md`

- [ ] **Step 1: Обновить документы и настройки**

В `config.toml` после удаления `[[rotation]]` оставить комментарий: «ротация — rotation.start.toml (считает бот, можно править); здесь — запасная».

- [ ] **Step 2: Run all tests**

Run: `python -m unittest discover -s tests -t .`
Expected: OK

- [ ] **Step 3: Живая проверка (проводит пользователь)**

Попросить пользователя: `python -m aobot install`, перезагрузить аддон в игре (перезайти персонажем), затем по шагам и прислать вывод:
1. `python -m aobot catalog` — панель и клавиши совпадают с игрой; ротация составлена; что «не понято».
2. `python -m aobot diag --once` — видны готовые слоты, ресурс (кровь), эффекты, номер каталога; искажение цвета 0.
3. `assist.bat` — выбрать моба, нажать E, дождаться убийства. На цели появляются «Лихорадка», «Алчные тени», «Вирус», бот обновляет их к концу, «Дыхание смерти» жмётся во время ГКД.
4. Посреди второго боя переставить умение на панели — бот пишет «панель изменилась — читаю каталог», потом продолжает бить; записать, сколько секунд он стоял.
5. Убрать умение с панели — бот бьёт остальными, в строке предупреждения «<имя>: нет на панели».
6. Поправить строку в `rotation.start.toml`, сменить веху или переставить умение — файл не перезаписан, появился `rotation.auto.toml`.
7. `python -m aobot stats` — бои записаны.

- [ ] **Step 4: Обновить статус в `docs/superpowers/roadmap.md`** — план 2 выполнен и проверен (дата, число тестов, итоги живой проверки, задержка лога), следующий — план 3.

- [ ] **Step 5: Commit**

```bash
git add README.md config.example.toml config.toml docs/superpowers/roadmap.md
git commit -m "docs: character data — README, config, roadmap after live check"
```
