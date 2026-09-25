#!/usr/bin/env python3
"""
Очередь постов Threads — файловая, без зависимостей.

Хранилище (по умолчанию ~/Claude/threads/):
    queue/queue.jsonl      — всё, что запланировано (одна запись = один пост/тред)
    queue/published.jsonl  — журнал опубликованного
    bank/topics.jsonl      — банк тем (радар)

Запись очереди:
{
  "id": "2026-09-08T09-00-ru-1",
  "slot": "2026-09-08T09:00:00+02:00",
  "rubric": "разбор",
  "formula": "T10",
  "format": "single|thread|image|video|carousel",
  "goal": "replies|reposts|likes|quotes",
  "text": "...",              # для single
  "parts": ["...", "..."],    # для thread
  "media": ["https://..."],
  "first_comment": "ссылка/уточнение отдельным ответом",
  "status": "draft|approved|published|failed|skipped",
  "score": 8,
  "topic": "короткая тема для проверки свежести",
  "published_id": null,
  "created": "..."
}

Команды:
    python3 queue.py add --file post.json          # добавить (можно массив)
    python3 queue.py list [--status approved] [--day 2026-09-08]
    python3 queue.py due [--now ISO] [--window 30] # что пора публиковать (минуты допуска)
    python3 queue.py approve --id X [--all-day 2026-09-08]
    python3 queue.py mark --id X --status published --published-id 123
    python3 queue.py fresh --topic "текст темы" [--days 14]
    python3 queue.py stats
    python3 queue.py publish-due [--dry-run] [--window 30]
"""
import argparse, datetime as dt, json, os, re, subprocess, sys

ROOT = os.environ.get("THREADS_HOME", os.path.expanduser("~/Claude/threads"))
QUEUE = os.path.join(ROOT, "queue", "queue.jsonl")
PUBLISHED = os.path.join(ROOT, "queue", "published.jsonl")
API = os.path.join(os.path.dirname(os.path.abspath(__file__)), "threads_api.py")


def ensure():
    for p in (QUEUE, PUBLISHED):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if not os.path.exists(p):
            open(p, "a").close()


def read(path=QUEUE):
    ensure()
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def write(items, path=QUEUE):
    ensure()
    with open(path, "w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")


def append(item, path=PUBLISHED):
    ensure()
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(item, ensure_ascii=False) + "\n")


def parse_dt(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s)
    except ValueError:
        return None


def norm(text):
    return set(re.findall(r"[a-zA-Zа-яА-ЯёЁіїєІЇЄ]{4,}", (text or "").lower()))


def cmd_add(a):
    data = json.load(open(a.file, encoding="utf-8")) if a.file else json.load(sys.stdin)
    items = data if isinstance(data, list) else [data]
    q = read()
    seen = {i["id"] for i in q}
    added = 0
    for it in items:
        it.setdefault("status", "draft")
        it.setdefault("created", dt.datetime.now().astimezone().isoformat())
        it.setdefault("id", (it.get("slot") or it["created"])[:16].replace(":", "-") + f"-{len(q)+added}")
        if it["id"] in seen:
            continue
        q.append(it); added += 1
    q.sort(key=lambda x: x.get("slot") or "")
    write(q)
    print(json.dumps({"added": added, "total": len(q)}, ensure_ascii=False))


def cmd_list(a):
    q = read()
    if a.status:
        q = [i for i in q if i.get("status") == a.status]
    if a.day:
        q = [i for i in q if (i.get("slot") or "").startswith(a.day)]
    for i in q:
        head = (i.get("text") or (i.get("parts") or [""])[0]).split("\n")[0][:70]
        print(f"{i.get('slot','—'):25} {i.get('status','?'):10} {i.get('rubric','—'):16} {i.get('formula','—'):4} {head}")
    print(f"\nвсего: {len(q)}")


def cmd_due(a):
    now = parse_dt(a.now) or dt.datetime.now().astimezone()
    win = dt.timedelta(minutes=a.window)
    out = []
    for i in read():
        if i.get("status") != "approved":
            continue
        slot = parse_dt(i.get("slot"))
        if slot is None:
            continue
        if slot.tzinfo is None:
            slot = slot.replace(tzinfo=now.tzinfo)
        if slot - win <= now <= slot + win * 4:
            out.append(i)
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_approve(a):
    q = read(); n = 0
    for i in q:
        if (a.id and i.get("id") == a.id) or (a.all_day and (i.get("slot") or "").startswith(a.all_day)):
            if i.get("status") == "draft":
                i["status"] = "approved"; n += 1
    write(q)
    print(json.dumps({"approved": n}, ensure_ascii=False))


def cmd_mark(a):
    q = read(); n = 0
    for i in q:
        if i.get("id") == a.id:
            i["status"] = a.status
            if a.published_id:
                i["published_id"] = a.published_id
            i["updated"] = dt.datetime.now().astimezone().isoformat()
            if a.status == "published":
                append(dict(i))
            n += 1
    write(q)
    print(json.dumps({"updated": n}, ensure_ascii=False))


def cmd_fresh(a):
    """Проверка свежести: не поднимали ли эту тему за N дней."""
    cutoff = dt.datetime.now().astimezone() - dt.timedelta(days=a.days)
    new = norm(a.topic)
    hits = []
    for i in read(PUBLISHED) + [x for x in read() if x.get("status") in ("approved", "draft")]:
        when = parse_dt(i.get("slot")) or parse_dt(i.get("created"))
        if when and when.tzinfo is None:
            when = when.replace(tzinfo=cutoff.tzinfo)
        if when and when < cutoff:
            continue
        old = norm(i.get("topic") or i.get("text") or "")
        if not old or not new:
            continue
        overlap = len(new & old) / max(1, len(new))
        if overlap >= 0.5:
            hits.append({"id": i.get("id"), "slot": i.get("slot"), "overlap": round(overlap, 2),
                         "topic": (i.get("topic") or i.get("text") or "")[:80]})
    print(json.dumps({"fresh": not hits, "collisions": hits}, ensure_ascii=False, indent=2))


def cmd_log(a):
    """Записать в журнал то, что ушло мимо очереди (например, прямо в Postiz).

    Без этого проверка свежести (`fresh`) слепа: она смотрит в published.jsonl,
    а в режиме Postiz посты туда не попадают.
    """
    data = json.load(open(a.file, encoding="utf-8")) if a.file else json.load(sys.stdin)
    items = data if isinstance(data, list) else [data]
    n = 0
    for it in items:
        rec = {"id": it.get("id") or f'{it.get("day","?")}-{it.get("slot","?")}',
               "slot": it.get("utc") or it.get("slot"),
               "topic": it.get("topic") or it.get("title") or (it.get("parts") or [""])[0][:120],
               "rubric": it.get("rubric"), "formula": it.get("formula"),
               "window": it.get("window"), "type": it.get("type"),
               "goal": it.get("goal"), "land": it.get("land"),
               "channel": a.channel, "published_id": it.get("postId"),
               "text": (it.get("parts") or [it.get("text", "")])[0],
               "logged": dt.datetime.now().astimezone().isoformat()}
        append(rec)
        n += 1
    print(json.dumps({"logged": n, "channel": a.channel,
                      "note": "теперь queue.py fresh увидит эти темы"}, ensure_ascii=False))


def cmd_stats(a):
    q, pub = read(), read(PUBLISHED)
    by_status, by_rubric, by_formula = {}, {}, {}
    for i in q:
        by_status[i.get("status", "?")] = by_status.get(i.get("status", "?"), 0) + 1
    for i in pub:
        by_rubric[i.get("rubric", "—")] = by_rubric.get(i.get("rubric", "—"), 0) + 1
        by_formula[i.get("formula", "—")] = by_formula.get(i.get("formula", "—"), 0) + 1
    print(json.dumps({"в_очереди": by_status, "опубликовано_всего": len(pub),
                      "по_рубрикам": by_rubric, "по_формулам": by_formula},
                     ensure_ascii=False, indent=2))


def cmd_publish_due(a):
    now = dt.datetime.now().astimezone()
    win = dt.timedelta(minutes=a.window)
    q = read(); results = []
    for i in q:
        if i.get("status") != "approved":
            continue
        slot = parse_dt(i.get("slot"))
        if slot is None:
            continue
        if slot.tzinfo is None:
            slot = slot.replace(tzinfo=now.tzinfo)
        if not (slot - win <= now <= slot + win * 4):
            continue
        if a.dry_run:
            results.append({"id": i["id"], "would_publish": True}); continue
        try:
            if i.get("parts"):
                tmp = os.path.join(ROOT, "queue", f".{i['id']}.txt")
                open(tmp, "w", encoding="utf-8").write("\n---\n".join(i["parts"]))
                out = subprocess.run([sys.executable, API, "thread", "--file", tmp],
                                     capture_output=True, text=True, timeout=900)
                os.remove(tmp)
            else:
                cmd = [sys.executable, API, "post", "--text", i.get("text", "")]
                media = i.get("media") or []
                if media:
                    kind = "--video" if re.search(r"\.(mp4|mov|m4v)(\?|$)", media[0], re.I) else "--image"
                    cmd += [kind, media[0]]
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            if out.returncode != 0:
                i["status"] = "failed"; i["error"] = (out.stdout + out.stderr)[-500:]
                results.append({"id": i["id"], "ok": False, "error": i["error"]})
                continue
            res = json.loads(out.stdout.strip().splitlines()[-1])
            pid = res.get("id") or (res.get("ids") or [None])[0]
            i["status"] = "published"; i["published_id"] = pid
            i["published_at"] = dt.datetime.now().astimezone().isoformat()
            append(dict(i))
            results.append({"id": i["id"], "ok": True, "published_id": pid})
            # первый комментарий (ссылка) — отдельным ответом, чтобы не резать охват
            if i.get("first_comment") and pid:
                subprocess.run([sys.executable, API, "reply", "--to", str(pid),
                                "--text", i["first_comment"]], capture_output=True, text=True, timeout=300)
        except Exception as e:  # noqa: BLE001
            i["status"] = "failed"; i["error"] = str(e)[:500]
            results.append({"id": i["id"], "ok": False, "error": str(e)[:200]})
    write(q)
    print(json.dumps({"processed": len(results), "results": results}, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description="Очередь Threads")
    s = ap.add_subparsers(dest="cmd", required=True)
    p = s.add_parser("add"); p.add_argument("--file"); p.set_defaults(fn=cmd_add)
    p = s.add_parser("list"); p.add_argument("--status"); p.add_argument("--day"); p.set_defaults(fn=cmd_list)
    p = s.add_parser("due"); p.add_argument("--now"); p.add_argument("--window", type=int, default=30); p.set_defaults(fn=cmd_due)
    p = s.add_parser("approve"); p.add_argument("--id"); p.add_argument("--all-day", dest="all_day"); p.set_defaults(fn=cmd_approve)
    p = s.add_parser("mark"); p.add_argument("--id", required=True); p.add_argument("--status", required=True)
    p.add_argument("--published-id", dest="published_id"); p.set_defaults(fn=cmd_mark)
    p = s.add_parser("fresh"); p.add_argument("--topic", required=True); p.add_argument("--days", type=int, default=14); p.set_defaults(fn=cmd_fresh)
    p = s.add_parser("log"); p.add_argument("--file")
    p.add_argument("--channel", default="postiz"); p.set_defaults(fn=cmd_log)
    s.add_parser("stats").set_defaults(fn=cmd_stats)
    p = s.add_parser("publish-due"); p.add_argument("--dry-run", action="store_true")
    p.add_argument("--window", type=int, default=30); p.set_defaults(fn=cmd_publish_due)
    a = ap.parse_args(); a.fn(a)


if __name__ == "__main__":
    main()
