#!/usr/bin/env python3
"""
Проверка веток перед публикацией. Ловит всё, что ломает голос и охват.

    python3 check_posts.py <файл.json>            # проверить
    python3 check_posts.py <файл.json> --json      # машиночитаемый вывод
    python3 check_posts.py --to-html "текст"       # текст -> HTML для Postiz

Формат файла: массив записей {day, slot, type: single|thread, title, parts: [...]}.
Необязательные поля, которые включают дополнительные проверки:
    "event": true   — ветка зовёт на событие (тогда обязательны ссылка и слово «бесплатно»)
    "kind": "list"  — ветка-список (тогда в первом посте обязан стоять пункт 1)
Оба поля определяются автоматически по тексту, если не заданы явно.
"""
import argparse, html, json, re, sys

# --- Конструкция «не X, а Y» во всех вариантах, на которых она проскакивает ---
CONTRAST = [
    (r"\bне\s+[^.!?\n]{1,60},\s+а\s+", "«не X, а Y»"),
    (r"\b[ЭэТт]то\s+не\s+[^.!?\n]{1,60}[.!]\s*[ЭэТт]то\s+", "«Это не X. Это Y»"),
    (r"\b[Дд]ело\s+не\s+в\b", "«дело не в X»"),
    (r"\b[Нн]е\s+потому\s+что\b[^.!?\n]{1,80}[.!]\s*[Пп]отому\s+что\b", "«не потому что X. Потому что Y»"),
    (r"[.!?]\s+[Нн]е\s+[а-яёА-ЯЁ]{2,20}[.!]", "рубленое «Не X.» контрастом"),
    (r"\bне\s+столько\b[^.!?\n]{1,60}\bсколько\b", "«не столько X сколько Y»"),
    (r"\bэто\s+не\s+про\b[^.!?\n]{1,60}[.!]\s*[ЭэТт]то\s+про\b", "«это не про X. Это про Y»"),
]

AI_WORDS = ["инновацион", "эффективн", "в современном мире", "важно понимать",
            "на новый уровень", "раскрыть потенциал", "комплексный подход",
            "стоит отметить", "как показывает практика", "в эпоху", "delve"]

# Ветка-список: открывающий пост обещает пронумерованный разбор
LIST_PROMISE = re.compile(
    r"\b(два|две|три|четыре|пять|шесть|семь|восемь|девять|десять|\d{1,2})\s+"
    r"(шаг|решени|этап|ошибк|вопрос|рол|част|возражени|правил|приём|прием|признак|"
    r"способ|вещ|совет|причин|формул|приёма|приема)", re.I)
LIST_ITEM1 = re.compile(
    r"(Решение|Этап|Шаг|Способ|Ошибка|Вопрос|Роль|Часть|Возражение|Правило|"
    r"Приём|Прием|Признак|Причина|Совет|Формула)\s*1\b")

EVENT_WORDS = re.compile(
    r"эфир|вебинар|хакатон|мастер-класс|мастеркласс|воркшоп|интенсив|практикум|"
    r"регистрац|записыва|созвон", re.I)

TAG_RE = re.compile(r"<[^>]+>")
MAX_CHARS = 500


def visible(t):
    """Видимая длина: Threads считает текст, а не HTML-разметку."""
    return html.unescape(TAG_RE.sub("", t))


def to_html(text):
    """Plain text -> HTML, который ждёт Postiz: абзац на <p>, пустая строка на <p></p>."""
    out = []
    for line in text.split("\n"):
        out.append(f"<p>{html.escape(line)}</p>" if line.strip() else "<p></p>")
    return "".join(out)


def is_event(u):
    if "event" in u:
        return bool(u["event"])
    return bool(EVENT_WORDS.search(" ".join(u["parts"])))


def is_list_thread(u):
    if u.get("kind"):
        return u["kind"] == "list"
    return u.get("type") == "thread" and bool(LIST_PROMISE.search(visible(u["parts"][0])))


def check(units):
    problems = []
    for u in units:
        tag = f'{u.get("day","?")}·{u.get("slot","?")} {u.get("title","?")}'
        parts = u["parts"]

        for i, raw in enumerate(parts):
            t = visible(raw)
            where = f"{tag} [{'пост' if i == 0 else f'комм {i}'}]"
            if len(t) > MAX_CHARS:
                problems.append((where, f"длина {len(t)} (видимых знаков, лимит {MAX_CHARS})"))
            if "—" in t or "–" in t:
                problems.append((where, "длинное тире"))
            for rx, name in CONTRAST:
                if rx and re.search(rx, t):
                    problems.append((where, name))
            hits = [w for w in AI_WORDS if w in t.lower()]
            if hits:
                problems.append((where, f"ИИ-маркер: {hits}"))
            if t.count("#") > 1:
                problems.append((where, "2+ хештега (Threads принимает один)"))

        # Ссылка никогда не в открывающем посте — она режет раздачу
        if "http" in parts[0]:
            problems.append((tag, "ССЫЛКА В ПЕРВОМ ПОСТЕ"))

        # Ветки про событие обязаны вести на регистрацию и говорить, что бесплатно
        if is_event(u):
            joined = " ".join(visible(p) for p in parts)
            if "http" not in " ".join(parts):
                problems.append((tag, "ветка про событие без ссылки"))
            if not re.search(r"бесплатн", joined, re.I):
                problems.append((tag, "ветка про событие: не сказано, что бесплатно"))

        # Ветка-список обязана нести пункт 1 в открывающем посте, а не обещание
        if is_list_thread(u) and not LIST_ITEM1.search(visible(parts[0])):
            problems.append((tag, "список-тред: в первом посте нет пункта 1"))

    return problems


def main():
    ap = argparse.ArgumentParser(description="Проверка веток Threads")
    ap.add_argument("path", nargs="?")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--to-html")
    a = ap.parse_args()

    if a.to_html is not None:
        print(to_html(a.to_html))
        return
    if not a.path:
        ap.error("нужен путь к файлу с ветками или --to-html")

    units = json.load(open(a.path, encoding="utf-8"))
    problems = check(units)
    n_posts = sum(len(u["parts"]) for u in units)

    if a.json:
        print(json.dumps({"ok": not problems, "units": len(units), "posts": n_posts,
                          "problems": [{"where": w, "what": p} for w, p in problems]},
                         ensure_ascii=False, indent=2))
        sys.exit(1 if problems else 0)

    if problems:
        print(f"НАЙДЕНО {len(problems)} проблем:\n")
        for where, what in problems:
            print(f"  {where:52} {what}")
        sys.exit(1)
    print(f"OK. {len(units)} веток, {n_posts} постов, все проверки пройдены.")


if __name__ == "__main__":
    main()
