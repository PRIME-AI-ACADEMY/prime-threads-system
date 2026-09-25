#!/usr/bin/env python3
"""
Журнал статистики и пересчёт весов — работает БЕЗ Graph API.

Цифры берутся откуда удобно: из приложения Threads (вкладка «Статистика» у каждой
ветки), со скриншота, из браузера. Скрипт считает одинаково в любом случае.

    python3 stats_log.py add --file measures.json     # записать замеры
    python3 stats_log.py add --stdin                  # то же из stdin
    python3 stats_log.py weights                      # пересчитать memory/patterns.json
    python3 stats_log.py report [--weeks 2]           # отчёт за период
    python3 stats_log.py template [--days 14]         # заготовка под замеры

Замер (все поля кроме views необязательны — пиши, что видно):
{
  "id": "1-07:30",            # из журнала published.jsonl, чтобы подтянуть рубрику и формулу
  "date": "2026-09-25",
  "views": 39400, "likes": 338, "replies": 40,
  "reposts": 10, "quotes": 0, "shares": 107, "follows": 88
}
"""
import argparse, datetime as dt, json, os, statistics, sys

ROOT = os.environ.get("THREADS_HOME", os.path.expanduser("~/Claude/threads"))
STATS = os.path.join(ROOT, "memory", "stats.jsonl")
PUBLISHED = os.path.join(ROOT, "queue", "published.jsonl")
PATTERNS = os.path.join(ROOT, "memory", "patterns.json")

# Веса сигналов Threads: комментарий ≈ 30 лайков, отправка в личку 3–5, репост «сохранение»
W = {"replies": 30, "shares": 5, "reposts": 3, "quotes": 3, "likes": 1}
MIN_N = 5  # меньше пяти постов в срезе — это шум, вывод не делаем


def read(path):
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def append(rec, path=STATS):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def enrich(m, pub_by_id):
    """Подтягивает рубрику, формулу, окно и цель из журнала публикаций."""
    src = pub_by_id.get(m.get("id"), {})
    for k in ("rubric", "formula", "goal", "land", "window", "topic", "slot", "type"):
        if k not in m and src.get(k):
            m[k] = src[k]
    return m


def score(m):
    v = m.get("views") or 0
    if not v:
        return None, None
    eng = sum(W[k] * (m.get(k) or 0) for k in W)
    subs = (m.get("follows") or 0) / v * 1000
    return eng / v, subs


def cmd_template(a):
    """Готовит заготовку: берёт опубликованное за N дней и оставляет поля под цифры."""
    cutoff = dt.datetime.now().astimezone() - dt.timedelta(days=a.days)
    rows = []
    for p in read(PUBLISHED):
        raw = p.get("slot") or p.get("published_at") or p.get("logged") or ""
        try:
            when = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            when = None
        if when and when.tzinfo is None:
            when = when.replace(tzinfo=cutoff.tzinfo)
        if when and when < cutoff:
            continue
        rows.append({"id": p.get("id"), "topic": (p.get("topic") or "")[:70],
                     "slot": p.get("slot"), "views": None, "likes": None,
                     "replies": None, "reposts": None, "shares": None, "follows": None})
    print(json.dumps(rows, ensure_ascii=False, indent=1))
    print(f"\n// {len(rows)} веток. Проставь цифры и скорми: stats_log.py add --file ...",
          file=sys.stderr)


def cmd_add(a):
    data = json.load(sys.stdin) if a.stdin else json.load(open(a.file, encoding="utf-8"))
    items = data if isinstance(data, list) else [data]
    pub_by_id = {p.get("id"): p for p in read(PUBLISHED) if p.get("id")}
    n, skipped = 0, 0
    for m in items:
        if not m.get("views"):
            skipped += 1
            continue
        m = enrich(dict(m), pub_by_id)
        m.setdefault("date", dt.datetime.now().strftime("%Y-%m-%d"))
        er, subs = score(m)
        m["er"], m["subs_per_1k"] = round(er, 5), round(subs, 3)
        append(m)
        n += 1
    print(json.dumps({"записано": n, "пропущено_без_просмотров": skipped,
                      "дальше": "stats_log.py weights"}, ensure_ascii=False))


def slice_weights(rows, key, avg_er):
    out, notes = {}, []
    groups = {}
    for r in rows:
        k = r.get(key)
        if k:
            groups.setdefault(k, []).append(r)
    for k, g in groups.items():
        if len(g) < MIN_N:
            notes.append(f"{key}={k}: только {len(g)} постов, вывод не делаем")
            continue
        out[k] = round(statistics.mean(x["er"] for x in g) / avg_er, 2) if avg_er else 1.0
    return out, notes


def cmd_weights(a):
    rows = [r for r in read(STATS) if r.get("er") is not None]
    if len(rows) < MIN_N:
        sys.exit(f"Данных мало: {len(rows)} замеров. Нужно хотя бы {MIN_N}.")
    avg_er = statistics.mean(r["er"] for r in rows)
    notes = []
    fw, n1 = slice_weights(rows, "formula", avg_er)
    rw, n2 = slice_weights(rows, "rubric", avg_er)
    ww, n3 = slice_weights(rows, "window", avg_er)
    gw, n4 = slice_weights(rows, "goal", avg_er)
    notes += n1 + n2 + n3 + n4

    subs = {}
    for r in rows:
        k = r.get("rubric")
        if k and r.get("subs_per_1k") is not None:
            subs.setdefault(k, []).append(r["subs_per_1k"])
    subs = {k: round(statistics.mean(v), 2) for k, v in subs.items() if len(v) >= MIN_N}

    by_hour = {}
    for r in rows:
        h = (r.get("slot") or "")[11:16] or (r.get("slot") or "")[:5]
        if h:
            by_hour.setdefault(h, []).append(r["er"])
    hours = sorted(((h, statistics.mean(v)) for h, v in by_hour.items() if len(v) >= 3),
                   key=lambda x: -x[1])

    prev = json.load(open(PATTERNS, encoding="utf-8")) if os.path.exists(PATTERNS) else {}
    out = {"updated": dt.datetime.now().strftime("%Y-%m-%d"), "n_posts": len(rows),
           "avg_er": round(avg_er, 5), "source": "ручной замер, без Graph API",
           "formula_weights": fw, "rubric_weights": rw, "window_weights": ww,
           "goal_weights": gw, "subs_per_1k_by_rubric": subs,
           "best_hours": [h for h, _ in hours[:4]],
           "worst_hours": [h for h, _ in hours[-2:]] if len(hours) > 5 else [],
           "notes": (prev.get("notes") or []) + notes}
    os.makedirs(os.path.dirname(PATTERNS), exist_ok=True)
    json.dump(out, open(PATTERNS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cmd_report(a):
    cutoff = (dt.datetime.now() - dt.timedelta(weeks=a.weeks)).strftime("%Y-%m-%d")
    rows = [r for r in read(STATS) if r.get("date", "") >= cutoff and r.get("er") is not None]
    if not rows:
        sys.exit("Нет замеров за период.")
    tot = lambda k: sum(r.get(k) or 0 for r in rows)
    rows.sort(key=lambda r: -r["er"])
    line = lambda r: (f'  {r.get("slot","")[:16]:17} {str(r.get("formula") or "—"):5} '
                      f'{str(r.get("rubric") or "—"):16} '
                      f'{r.get("views") or 0:>7} просм · {r.get("replies") or 0:>3} комм · '
                      f'ER {r["er"]*100:.2f}%  {(r.get("topic") or "")[:44]}')
    print(f"\nПЕРИОД: последние {a.weeks} нед. · веток с замерами: {len(rows)}")
    print(f"Просмотры {tot('views')} · комментарии {tot('replies')} · "
          f"отправки {tot('shares')} · репосты {tot('reposts')} · подписки {tot('follows')}")
    print(f"Средний ER: {statistics.mean(r['er'] for r in rows)*100:.2f}%")
    print("\nТОП-5:"); [print(line(r)) for r in rows[:5]]
    print("\nХУДШИЕ 3:"); [print(line(r)) for r in rows[-3:]]
    print("\nДальше: stats_log.py weights — пересчитать веса для threads-write и threads-plan\n")


def main():
    ap = argparse.ArgumentParser(description="Статистика Threads без Graph API")
    s = ap.add_subparsers(dest="cmd", required=True)
    p = s.add_parser("add"); p.add_argument("--file"); p.add_argument("--stdin", action="store_true")
    p.set_defaults(fn=cmd_add)
    s.add_parser("weights").set_defaults(fn=cmd_weights)
    p = s.add_parser("report"); p.add_argument("--weeks", type=int, default=2); p.set_defaults(fn=cmd_report)
    p = s.add_parser("template"); p.add_argument("--days", type=int, default=14); p.set_defaults(fn=cmd_template)
    a = ap.parse_args(); a.fn(a)


if __name__ == "__main__":
    main()
