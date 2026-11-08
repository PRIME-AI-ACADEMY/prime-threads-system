#!/usr/bin/env python3
"""
Импорт контент-плана от SMM в формат системы.

Принимает CSV (выгрузка из Google-таблицы), TSV или JSON с колонками:
    date, time, goal, rubric, hook_type, title, post, c1..c5, media, event

Делает три вещи:
  1) собирает ветки (пост + комментарии) и считает UTC из даты, времени и часового пояса;
  2) прогоняет их через тот же валидатор, что и собственные тексты системы;
  3) выдаёт готовые payload для Postiz — остаётся только отправить.

    python3 import_plan.py plan.csv                      # проверить и показать отчёт
    python3 import_plan.py plan.csv --tz Europe/Kyiv     # часовой пояс аудитории
    python3 import_plan.py plan.csv --out units.json     # сохранить ветки
    python3 import_plan.py plan.csv --postiz <integrationId> --out payloads.json
    python3 import_plan.py --template plan-template.csv  # создать пустой шаблон
"""
import argparse, csv, datetime as dt, json, os, re, sys, zoneinfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_posts import check, to_html, visible  # noqa: E402

COLS = ["date", "time", "goal", "rubric", "hook_type", "title", "post",
        "c1", "c2", "c3", "c4", "c5", "media", "event"]
REQUIRED = ["date", "time", "title", "post"]

TEMPLATE_ROW = {
    "date": "2026-10-20", "time": "07:30", "goal": "подписки",
    "rubric": "полезный список", "hook_type": "обещание",
    "title": "5 этапов автоматизации блога",
    "post": ("Пять этапов, после которых блог перестаёт зависеть от настроения.\n\n"
             "Этап 1. Темы.\n\nПерестаёшь придумывать тему с нуля: один раз отдаёшь "
             "свои вопросы из директа и комментариев, просишь сгруппировать по болям "
             "и выдать тридцать тем с углами."),
    "c1": "Этап 2. Сценарии.\n\nТекст пишется по твоей структуре, а не с чистого листа.",
    "c2": "Этап 3. Визуал.\n\nОдин раз фиксируешь стиль, дальше обложка за минуту.\n\nРазбор целиком: https://пример.ру",
    "c3": "", "c4": "", "c5": "", "media": "", "event": "",
}


def norm_tz(name):
    try:
        return zoneinfo.ZoneInfo(name)
    except Exception:
        sys.exit(f"Неизвестный часовой пояс: {name}")


def read_rows(path):
    if path.lower().endswith(".json"):
        data = json.load(open(path, encoding="utf-8"))
        return data if isinstance(data, list) else [data]
    with open(path, encoding="utf-8-sig", newline="") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return list(csv.DictReader(fh, dialect=dialect))


def build(rows, tz):
    units, errors = [], []
    for i, r in enumerate(rows, start=2):  # строка 1 — заголовки
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items() if k}
        if not any(r.get(k) for k in REQUIRED):
            continue  # пустая строка
        missing = [k for k in REQUIRED if not r.get(k)]
        if missing:
            errors.append(f"строка {i}: нет обязательных колонок {missing}")
            continue
        try:
            d = dt.date.fromisoformat(r["date"])
            hh, mm = (int(x) for x in r["time"].replace(".", ":").split(":")[:2])
            local = dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz)
        except Exception as e:  # noqa: BLE001
            errors.append(f"строка {i}: не разобрать дату или время ({r.get('date')} {r.get('time')}): {e}")
            continue

        parts = [r["post"]] + [r[k] for k in ("c1", "c2", "c3", "c4", "c5") if r.get(k)]
        unit = {
            "day": d.isoformat(), "slot": f"{hh:02d}:{mm:02d}",
            "utc": local.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z"),
            "type": "thread" if len(parts) > 1 else "single",
            "goal": r.get("goal") or None, "rubric": r.get("rubric") or None,
            "hook_type": r.get("hook_type") or None, "title": r["title"],
            "parts": parts, "row": i,
        }
        if r.get("media"):
            # | или ; — карусель в одном посте, > — следующий пост ветки
            groups = [g for g in r["media"].split(">")]
            unit["media_parts"] = [[m.strip() for m in re.split(r"[|;]", g) if m.strip()]
                                   for g in groups]
            unit["media"] = unit["media_parts"][0]
        if r.get("event", "").lower() in ("да", "yes", "true", "1", "+"):
            unit["event"] = True
        units.append(unit)
    return units, errors


def rhythm_warnings(units):
    """Мягкие замечания по ритму — не ошибки, но стоит посмотреть."""
    out = []
    by_day = {}
    for u in units:
        by_day.setdefault(u["day"], []).append(u)
    for day, rows in sorted(by_day.items()):
        rows.sort(key=lambda x: x["slot"])
        if len(rows) > 8:
            out.append(f"{day}: {len(rows)} веток — выше нормы 5–8")
        mins = [int(a) * 60 + int(b) for a, b in (x["slot"].split(":") for x in rows)]
        for a, b, ra, rb in zip(mins, mins[1:], rows, rows[1:]):
            if b - a < 20:
                out.append(f"{day}: между {ra['slot']} и {rb['slot']} меньше 20 минут")
        hooks = [x.get("hook_type") for x in rows]
        for a, b, ra, rb in zip(hooks, hooks[1:], rows, rows[1:]):
            if a and a == b:
                out.append(f"{day}: {ra['slot']} и {rb['slot']} — один тип хука «{a}»")
        goals = [x.get("goal") for x in rows if x.get("goal")]
        if goals and all(g == goals[0] for g in goals) and len(goals) > 3:
            out.append(f"{day}: все ветки на одну цель «{goals[0]}» — нет баланса")
    sales = sum(1 for u in units if (u.get("goal") or "").startswith("прод"))
    if units and sales == 0:
        out.append("за весь план нет ни одной ветки на продажи (норма: минимум 1 в неделю)")
    return out


def to_postiz(units, integration_id):
    payloads = []
    for u in units:
        mp = u.get("media_parts") or [u.get("media", [])]
        mp = mp + [[]] * (len(u["parts"]) - len(mp))
        comments = [{"content": to_html(p), "attachments": m}
                    for p, m in zip(u["parts"][1:], mp[1:])]
        first = {"content": to_html(u["parts"][0]), "attachments": mp[0]}
        payloads.append({"socialPost": [{
            "integrationId": integration_id, "isPremium": False,
            "date": u["utc"], "shortLink": False, "type": "draft",
            "settings": [], "postsAndComments": [first] + comments}],
            "_meta": {"title": u["title"], "slot": f'{u["day"]} {u["slot"]}'}})
    return payloads


def cmd_template(path):
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerow(TEMPLATE_ROW)
    print(f"Шаблон создан: {path}\nКолонки: {', '.join(COLS)}")
    print("Обязательные: date, time, title, post. Остальные по необходимости.")


def main():
    ap = argparse.ArgumentParser(description="Импорт контент-плана Threads")
    ap.add_argument("path", nargs="?")
    ap.add_argument("--tz", default="Europe/Kyiv", help="часовой пояс аудитории")
    ap.add_argument("--out", help="куда сохранить ветки или payload")
    ap.add_argument("--postiz", help="integrationId канала Threads в Postiz")
    ap.add_argument("--template", help="создать пустой шаблон CSV по этому пути")
    a = ap.parse_args()

    if a.template:
        cmd_template(a.template)
        return
    if not a.path:
        ap.error("нужен путь к плану или --template")

    rows = read_rows(a.path)
    units, errors = build(rows, norm_tz(a.tz))
    problems = check(units)
    warns = rhythm_warnings(units)

    print(f"\nПрочитано строк: {len(rows)} · собрано веток: {len(units)} · "
          f"постов: {sum(len(u['parts']) for u in units)}")

    if errors:
        print(f"\nОШИБКИ РАЗБОРА ({len(errors)}):")
        for e in errors:
            print("  " + e)
    if problems:
        print(f"\nНАРУШЕНИЯ ПРАВИЛ ({len(problems)}):")
        for where, what in problems:
            print(f"  {where:46} {what}")
    if warns:
        print(f"\nЗАМЕЧАНИЯ ПО РИТМУ ({len(warns)}):")
        for w in warns:
            print("  " + w)
    if not (errors or problems):
        print("\nПравила пройдены." + (" Замечания по ритму выше — на твоё усмотрение."
                                       if warns else ""))

    if a.out:
        data = to_postiz(units, a.postiz) if a.postiz else units
        json.dump(data, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\nСохранено: {a.out}" + (" (payload для Postiz, type=draft)" if a.postiz else ""))

    sys.exit(1 if (errors or problems) else 0)


if __name__ == "__main__":
    main()
