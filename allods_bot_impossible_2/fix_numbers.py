import re, pathlib, sys

LOG = pathlib.Path(sys.argv[1] if len(sys.argv) > 1
                   else r"D:\VK Play\Аллоды Онлайн\Personal\Logs\mods.txt")
CFG = pathlib.Path("config.toml")
MAX_SPELLS = 16

text = LOG.read_bytes().decode("cp1251", errors="replace")
row = re.compile(r"BOTCAT\t(\d+)\tSLOT\tslot=(\d+)\tkind=(\w+)\tname=([^\t\r\n\[]*)\tkeys=([^\t\r\n\[]*)")

# каждый дамп начинается с BEGIN; берём последний, где есть строки SLOT
starts = [m.start() for m in re.finditer(r"BOTCAT\t\d+\tBEGIN", text)]
chunks = [text[starts[i]: starts[i + 1] if i + 1 < len(starts) else len(text)]
          for i in range(len(starts))] or [text]
rows = []
for ch in reversed(chunks):
    rows = row.findall(ch)
    if rows:
        break
if not rows:
    sys.exit("В логе нет строк SLOT. Передвинь умение на панели и перезайди.")

slots = {int(r[1]): (r[2], r[3].strip(), r[4].strip()) for r in rows}
by_key, n = {}, 0
print("ПАНЕЛЬ (что видит бот):")
for s in sorted(slots):
    kind, name, keys = slots[s]
    if kind != "spell":
        print(f"  --  slot={s:2} {keys:9} [{kind}] {name}")
        continue
    n += 1
    if keys:
        by_key.setdefault(keys.lower(), (n, name))
    print(f"  {n:2}  slot={s:2} {keys:9} {name}" + ("   <-- ЗА ЛИМИТОМ 16" if n > MAX_SPELLS else ""))

src = CFG.read_text(encoding="utf-8")
CFG.with_suffix(".toml.bak").write_text(src, encoding="utf-8")

out = []
print("\nПРАВКИ:")
for block in re.split(r"(?=\[\[rotation\]\])", src):
    mk = re.search(r'key\s*=\s*"([^"]+)"', block)
    if not block.lstrip().startswith("[[rotation]]") or not mk:
        out.append(block)
        continue
    key = mk.group(1).lower()
    hit = by_key.get(key)
    if not hit:
        print(f"  {key:9} НЕТ НА ПАНЕЛИ — строка не тронута")
        out.append(block)
        continue
    num, name = hit
    old = re.search(r"spell\s*=\s*(\d+)", block)
    print(f"  {key:9} {name:24} {old.group(1) if old else '?'} -> {num}"
          + ("   <-- БОТ НЕ УВИДИТ (>16)" if num > MAX_SPELLS else ""))
    out.append(re.sub(r"spell\s*=\s*\d+", f"spell = {num}", block, count=1))

CFG.write_text("".join(out), encoding="utf-8")
print("\n" + "=" * 60)
print(CFG.read_text(encoding="utf-8"))
print("=" * 60)
print("Записано. Бэкап: config.toml.bak")