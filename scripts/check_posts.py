#!/usr/bin/env python3
"""
Строгая проверка веток перед публикацией. Ловит всё, что ломает голос и охват.

    python3 check_posts.py ~/Claude/threads/queue/webinar-all.json
"""
import json, re, sys

# Конструкция «не X, а Y» во всех пяти вариантах, на которых она обычно и проскакивает
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
            "стоит отметить", "как показывает практика", "в эпоху"]


def check(units):
    problems = []
    for u in units:
        tag = f'{u.get("day","?")}·{u.get("slot","?")} {u.get("title","?")}'
        parts = u["parts"]

        for i, t in enumerate(parts):
            where = f"{tag} [{'пост' if i == 0 else f'комм {i}'}]"
            if len(t) > 500:
                problems.append((where, f"длина {len(t)}"))
            if "—" in t or "–" in t:
                problems.append((where, "длинное тире"))
            for rx, name in CONTRAST:
                if re.search(rx, t):
                    problems.append((where, name))
            hits = [w for w in AI_WORDS if w in t.lower()]
            if hits:
                problems.append((where, f"ИИ-маркер: {hits}"))
            if t.count("#") > 1:
                problems.append((where, "2+ хештега"))

        if "http" in parts[0]:
            problems.append((tag, "ССЫЛКА В ПЕРВОМ ПОСТЕ"))
        if not any("http" in t for t in parts):
            problems.append((tag, "нет ссылки ни в одном посте"))
        if not re.search(r"бесплатн", " ".join(parts), re.I):
            problems.append((tag, "не сказано, что бесплатно"))

        # для тредов: первый пост обязан нести шаг/решение/этап № 1, а не только обещание
        if u.get("type") == "thread":
            if not re.search(r"(Решение|Этап|Шаг|Способ|Ошибка|Вопрос|Роль|Часть|Возражение|Правило|Приём|Признак)\s*1\b", parts[0]):
                problems.append((tag, "в первом посте нет пункта 1"))
    return problems


def main():
    path = sys.argv[1]
    units = json.load(open(path, encoding="utf-8"))
    problems = check(units)
    if problems:
        print(f"НАЙДЕНО {len(problems)} проблем:\n")
        for where, what in problems:
            print(f"  {where:52} {what}")
        sys.exit(1)
    n_posts = sum(len(u["parts"]) for u in units)
    print(f"OK. {len(units)} веток, {n_posts} постов, все проверки пройдены.")


if __name__ == "__main__":
    main()
