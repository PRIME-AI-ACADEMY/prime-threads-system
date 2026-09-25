# Changelog

## 1.1.0 — 2026-09-26

Версия для участников практикума.

### Изменено
- **Postiz — основной путь публикации.** `threads-setup` и `threads-publish` переписаны:
  Postiz режим A, Threads Graph API — продвинутый режим B. Автопилот в режиме Postiz
  не требует задачи публикации.
- `threads-publish`: точная форма `integrationSchedulePostTool` по актуальной схеме
  (`content` в HTML с `<p>` на строку, `attachments` обязателен, `date` в UTC,
  `postsAndComments[0]` = пост, дальше комментарии). Добавлен эквивалент через Postiz CLI
  (`postiz posts:create -c … -c … -s <UTC> -t draft -i <id>`). Первый запуск — всегда черновик.
- `SETUP.md` переписан под участников: установка из GitHub-маркетплейса
  (`/plugin marketplace add PRIME-AI-ACADEMY/prime-threads-system`), Postiz по клику,
  первый запуск с проверками, Graph API — в свёрнутом «продвинутом» разделе.
- Рабочая папка данных настраивается через `THREADS_HOME` (по умолчанию `~/Claude/threads/`);
  `threads_api.py` теперь тоже читает её. `threads-setup` создаёт папку, если её нет.
- Пути к плагину в cron-примерах — через `${CLAUDE_PLUGIN_ROOT}` / путь установки,
  без привязки к домашней папке автора.
- Манифесты: версия 1.1.0, автор PRIME AI Academy, `homepage`/`repository`,
  версия плагина продублирована в `marketplace.json`.

### Добавлено
- `ФОРМАТЫ-ТРЕДОВ-памятка.md` — шпаргалка для раздатки: набор дня 3+1+1+1, 8 рубрик,
  окна публикации, 13 формул хуков, 5 правил анти-ИИ.
- `.gitignore`: `.env`, очередь, банки, профиль, память — не попадают в репозиторий.
- `CHANGELOG.md`.

### Убрано
- Личные пути автора из `CLOUD.md`.

## 1.0.0 — 2026-09

Первая сборка: 12 скиллов, справочники, скрипты Threads Graph API, очередь, банк медиа,
облачный автопилот через GitHub Actions.
