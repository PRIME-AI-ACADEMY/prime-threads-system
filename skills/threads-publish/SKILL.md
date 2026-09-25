---
name: threads-publish
description: "Публикация в Threads: берёт утверждённые записи очереди и ставит их в расписание через Postiz (режим A, основной), Threads Graph API (B, продвинутый), Metricool (C) или готовит ручную выдачу (D). Умеет одиночные посты, треды, фото, видео, карусели и первый комментарий со ссылкой. Первый запуск — всегда черновик / dry-run. Триггеры: опубликуй в threads, запости threads, публикация threads, выложи пост, отправь в threads, поставь в расписание."
---

# Threads Publish — публикация

## Железные правила

1. Публикуется **только** запись со статусом `approved`. `draft` — никогда.
2. **Первый запуск в любой новой настройке — черновик**: Postiz `type: "draft"`,
   Graph API `--dry-run`. Покажи, что было бы отправлено, дождись «ок», и только потом реальная постановка.
3. Ссылка не идёт в тело поста. Только в `first_comment` — отдельным комментарием.
4. Медиа — только **публичные URL** (банк медиа / CDN). Локальный путь с диска не примет ни один режим.
5. Ошибка на одном посте не останавливает остальные: помечаем `failed`, идём дальше.
6. Время слота у пользователя — локальное. В Postiz и GitHub Actions уходит **UTC**. Пересчитай и покажи оба.

## Режим A — Postiz (MCP) — основной

Postiz публикует **из своего облака**: ноутбук может быть выключен, GitHub Actions не нужен.

**Шаг 1. Канал.** `integrationList` → запись с `platform: "threads"` → взять `id`
(это id интеграции, не internal id). Один раз запомни его в `profile/dna.md`.

**Шаг 2. Медиа (если есть).** `uploadFromUrlTool` с публичным URL из банка медиа →
вернётся ссылка, её кладём в `attachments`. Сырые внешние ссылки в `attachments` не класть.

**Шаг 3. Постановка.** `integrationSchedulePostTool` — точная форма:

```json
{"socialPost": [{
  "integrationId": "<id канала threads>",
  "isPremium": false,
  "date": "2026-09-27T06:00:00Z",
  "shortLink": false,
  "type": "draft",
  "settings": [],
  "postsAndComments": [
    {"content": "<p>Первая строка — хук.</p><p>Вторая строка.</p>", "attachments": ["<url медиа из uploadFromUrlTool>"]},
    {"content": "<p>Второй пост треда.</p>", "attachments": []},
    {"content": "<p>Разбор целиком — в закрепе профиля.</p>", "attachments": []}
  ]
}]}
```

**Ключевые детали:**
- `date` — **строго UTC**, формат `YYYY-MM-DDTHH:MM:SSZ`. Киев летом UTC+3: 09:00 → `06:00:00Z`; Цюрих летом UTC+2: 09:00 → `07:00:00Z`.
- `type`: `"draft"` — черновик для проверки (в Threads не уходит), `"schedule"` — реальная постановка в расписание, `"now"` — сразу (тогда `date` = текущее время).
- `postsAndComments` — массив: **первый элемент это пост, все следующие — комментарии к нему**. Так делаются и треды, и приём «ссылка отдельным комментарием».
- `content` — **HTML: каждая строка/абзац обёрнут в `<p>…</p>`**. Пустая строка = `<p></p>`. Разрешено: `p, strong, u, h1–h3, ul, li`. Для Threads это превращается в обычный текст — не используй жирный, Threads его не покажет.
- `attachments` — массив строк-ссылок (может быть пустым, но поле обязательно).
- `settings` — пустой массив: у Threads доп. настроек нет.
- `isPremium: false` (это поле про X), `shortLink: false` (ссылок в теле всё равно нет).
- Лимит 500 знаков на каждый элемент — тот же, что в самом Threads. Проверь длину **до** вызова.
- Один вызов может ставить несколько постов: `socialPost` — массив, по элементу на слот.

**Шаг 4. Проверка.** В ответе на каждый элемент — `previewUrl`. Покажи пользователю.
`postsListTool` — список того, что стоит в расписании. Если вернулось `output.errors` — поправь и повтори.

**Шаг 5. Очередь.** Запиши в запись очереди `postiz_id`/`previewUrl`, статус → `scheduled`
(при `draft`) или `published` (при `schedule`, после наступления слота).

### Тот же вызов через Postiz CLI (если MCP недоступен)

```bash
npm install -g postiz && postiz auth:login          # один раз
postiz integrations:list                             # взять id канала threads
IMG=$(postiz upload ./cover.jpg | jq -r '.path')     # медиа только через upload
postiz posts:create \
  -c "Первая строка — хук. Вторая строка." -m "$IMG" \
  -c "Второй пост треда." \
  -c "Разбор целиком — в закрепе профиля." \
  -s "2026-09-27T06:00:00Z" -t draft -i "<id канала threads>"
```
Каждый `-c` — отдельная часть треда (первый = пост, дальше комментарии), `-m` относится к
предыдущему `-c`, `-s` — дата в UTC, `-t draft` для проверки, без `-t` — в расписание.

### Чего в режиме A НЕТ

| Нет | Последствие |
|---|---|
| Чтение комментариев и ответы | `threads-engage` цикл A — руками в приложении Threads |
| Статистика отдельных постов | `threads-analytics` не пересчитает веса автоматически; можно вносить цифры вручную |
| Проверка суточной квоты | не критично: 250 постов в сутки не выбрать |

Это не повод не начинать. Когда захочется автоответов и обучения — добавь Graph API
вторым слоем (`GRAPH-API.md`). Режимы совместимы: публикуешь через Postiz, а комментарии
и инсайты читаешь через API.

## Режим B — Threads Graph API (продвинутый)

```bash
# что бы ушло сейчас — ВСЕГДА первым
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/queue.py publish-due --dry-run

# реальная публикация того, что подошло по времени
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/queue.py publish-due

# остаток квоты (250 постов / 1000 ответов в сутки)
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/threads_api.py limits
```

Точечно:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/threads_api.py post --text "..."
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/threads_api.py post --text "..." --image https://...
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/threads_api.py thread --file /tmp/thread.txt   # части через строку ---
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/threads_api.py carousel --text "..." --images URL1 URL2 URL3
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/threads_api.py reply --to <media_id> --text "..."
```

`publish-due` сам: публикует, дожидается обработки видео, пишет `published_id`,
кладёт первый комментарий и переносит запись в `published.jsonl`.

## Режим C — Metricool (MCP)

1. `getBrandSettings` → `blogId` и `timezone`.
2. `createScheduledPost`: `providers:[{"network":"threads"}]`, `text`, `media:[публичные URL]`,
   `publicationDate:{dateTime, timezone}`, `draft:true` для теста, потом `autoPublish:true`.
3. Записать `plannerUrl` в запись очереди, статус → `published`.

Ограничение: бесплатный тариф — один бренд и лимит постов в месяц. Тредов-цепочек и первого комментария нет.

## Режим D — ручная очередь

Выдать в чат готовый блок на день: время, текст (готовый к копированию), ссылка на медиа,
первый комментарий. Статус → `approved`, отметку о публикации ставит человек.

## После публикации

- Записать `published_id` / `previewUrl` — без этого не будет аналитики.
- Сразу поставить напоминание на `threads-engage` через **20–30 минут**:
  ответы в первый час — главный множитель охвата. В режиме A — ответить руками в приложении.

## Обработка ошибок

| Где | Код / текст | Что делать |
|---|---|---|
| Postiz | `output.errors` | прочитать текст, чаще всего: >500 знаков, не UTC дата, не тот `integrationId`, сырой URL в `attachments` |
| Postiz | канал Threads «disabled/expired» | переподключить канал в Postiz (Add channel → Threads) |
| API | 190 | токен протух / нет прав → `GRAPH-API.md`, продлить (60 дней) |
| API | 100 | неверный параметр / user id → проверить `.env` |
| API | 4 / 613 | лимит вызовов → подождать, снизить частоту |
| API | 24 / 25 | лимит публикаций → `limits`, разнести слоты |
| API | контейнер `ERROR` | медиа недоступно по URL → проверить публичность ссылки |

Файлы: `${CLAUDE_PLUGIN_ROOT}/references/algorithm-2026.md`
