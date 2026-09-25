---
name: threads-setup
description: "Первичная настройка системы Threads: создаёт рабочую папку (~/Claude/threads или $THREADS_HOME), проверяет канал публикации (Postiz — основной; Threads Graph API — продвинутый; ручная очередь — запасной), тянет список каналов и лимиты, ставит первый тестовый пост черновиком. Запускать один раз. Триггеры: настрой threads, подключи threads, threads setup, проверь threads, диагностика threads."
---

# Threads Setup — подключение и диагностика

Задача: за один проход довести систему до состояния «можно постить».
Ничего не публикуй. Итог — таблица-отчёт и следующий шаг.

## 1. Рабочая папка (создай, если нет)

Данные живут отдельно от плагина, чтобы переустановка плагина их не трогала.
Путь берётся из переменной `THREADS_HOME`; если её нет — `~/Claude/threads/`.

```
$THREADS_HOME/  (по умолчанию ~/Claude/threads/)
  profile/     dna.md, voice.md, funnel.md, rubrics.md
  bank/        topics.jsonl, hooks.md, swipe.md, media.jsonl
  queue/       queue.jsonl, published.jsonl
  memory/      patterns.json, weekly/
  inbox/       сюда кидают фото и видео для банка медиа
  .env         только для режима Graph API (токены). Никогда в чат и не в git.
```

```bash
T="${THREADS_HOME:-$HOME/Claude/threads}"
mkdir -p "$T"/{profile,bank,queue,memory/weekly,inbox} && touch "$T/.env" && chmod 600 "$T/.env"
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/queue.py stats
```

Проверка: `queue.py stats` отработал без ошибки, папки на месте.

## 2. Канал публикации — проверь по порядку

| Режим | Как проверить | Что даёт |
|---|---|---|
| **A. Postiz (MCP)** ⭐ основной | вызови `integrationList` → есть запись с `platform: "threads"` | публикация из облака Postiz по расписанию, треды, фото/видео, первый комментарий. Ноутбук может быть выключен |
| B. Threads Graph API — продвинутый | в `.env` есть `THREADS_ACCESS_TOKEN` и `THREADS_USER_ID` → `threads_api.py me` | + ответы на комментарии, инсайты постов, обучение на данных, почасовой автопилот. Настройка 20–30 мин по `GRAPH-API.md` |
| C. Metricool (MCP) | `getBrandSettings` → в списке есть Threads | как A, но без тредов-цепочек |
| D. Ручная очередь | ничего не подключено | система пишет и складывает в очередь, публикуешь руками |

Запиши выбранный режим в `profile/dna.md` строкой `publish_mode: postiz|graph-api|metricool|manual`.

### Если Postiz не виден (нет инструментов `integration*` в чате)

Не пытайся чинить сам. Выдай пользователю три шага и остановись:

1. postiz.com → войти → **Add channel** → Threads → разрешить доступ. ✅ канал Threads виден в Postiz.
2. Claude → Settings → **Connectors** → **Add custom connector** → URL `https://mcp.postiz.com/mcp` → Connect → войти в Postiz → Allow. ✅ коннектор Postiz со статусом Connected.
3. Перезапустить чат / `claude` и снова сказать «настрой threads».

Если в `integrationList` есть каналы, но нет Threads — канал не добавлен в Postiz (шаг 1).

## 3. Режим B: токен получает пользователь, не агент

Ты не создаёшь приложения Meta и не вводишь пароли. Если пользователь хочет режим B —
отправь его в `${CLAUDE_PLUGIN_ROOT}/../GRAPH-API.md` (пошагово, со скриптом `get_token.py`)
и вернись к проверке, когда `.env` заполнен:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/threads_api.py me
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/threads_api.py limits
```

`limits` показывает `quota_usage` и `config.quota_total: 250`. Ошибка 190 — токен протух
или не хватает прав. 100 — не тот user id. Токен живёт 60 дней (см. `threads-autopilot`).

## 4. Первый пост — только черновиком

**Никогда не публикуй ничего без явного «да» пользователя.**

- Режим A: `integrationSchedulePostTool` с `type: "draft"` — один тестовый пост
  «проверка связи», дата завтра 09:00 по времени пользователя, **переведённая в UTC**.
  Покажи `previewUrl`. Это черновик, в Threads он не уйдёт.
- Режим B: `queue.py add` со статусом `draft`, потом `queue.py publish-due --dry-run`.
- Режим D: покажи текст в чате, пометь в очереди `approved`, публикацию отмечает человек.

## 5. Отчёт

Выведи таблицу: режим публикации · имя канала/username · рабочая папка · что создано ·
чего не хватает · **следующий шаг — `threads-dna`** (без него писать нечего).

Файлы: `${CLAUDE_PLUGIN_ROOT}/references/algorithm-2026.md`
