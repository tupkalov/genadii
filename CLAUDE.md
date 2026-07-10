# CLAUDE.md — рабочие инструкции для Claude Code

Умный Геннадий — self-hosted Telegram AI-бот (личный + групповые чаты).
Стек: Python 3.12, aiogram 3, FastAPI, SQLAlchemy 2 async + asyncpg,
PostgreSQL 16 + pgvector, Redis, arq (worker/cron), OpenRouter (LLM),
mcp SDK (MCP-клиент), Docker Compose (+ Caddy для публичного HTTPS).
Обзор фич — `app/llm/capabilities.py` (единственный источник правды,
он же отдаётся боту инструментом `bot_help`). Дизайн — `ARCHITECTURE.md`.

## Рабочий цикл

```bash
# Сборка и деплой (после ЛЮБОЙ правки app/ — код запечён в образ):
docker compose build app worker && docker compose up -d app worker

# Тесты гоняются ВНУТРИ контейнера app (нужна БД/Redis):
docker compose exec -u root app pip install -q -e ".[dev]"   # только -u root!
docker compose exec app pytest -q

# Быстрая итерация без пересборки (один файл в работающий контейнер):
docker compose cp path/to/file.py app:/srv/path/to/file.py
# …но перед коммитом всё равно пересобери образ — иначе фикс потеряется
# при пересоздании контейнера.

# Миграции применяются сами при старте app (alembic upgrade head в compose).
# Логи/БД:
docker compose logs app --since 1h | grep -i error
docker compose exec postgres psql -U gennady -d gennady -c "..."
```

Грабли:
- Контейнеры app/worker работают под non-root `gennady` → `pip install`
  и запись в /srv — только `docker compose exec -u root`.
- `.env` — chmod 600, root; не печатать содержимое, дописывать через
  `grep -q || echo >> .env`.
- pytest-asyncio настроен на session-scoped loop (`pyproject.toml`) —
  модульный engine SQLAlchemy привязан к одному event loop; не менять.
- Фикстуры тестов (tests/conftest.py) работают с РЕАЛЬНОЙ БД: teardown
  каждой фикстуры обязан сам подчищать ссылающиеся на неё строки
  (порядок финализации независимых фикстур не гарантирован). Новая
  таблица с FK на users → добавь очистку в фикстуру `user`.

## Конвенции кода

- Пользовательский/внешний контент в HTML-ответах — всегда `html.escape`
  (parse_mode HTML; образец — handlers/scripts.py).
- Каждый ответ хендлера сохраняется в историю: `messages.save_assistant`.
- Значимые действия — в `audit.log(session, action=..., payload=...)`.
- Всё per-workspace: память, скиллы, MCP, вебхуки, скрипты, бюджет,
  настройки. Изоляция чатов — инвариант.
- Ошибки наружу — через `alerts.safe_error_text()` (редактирует секреты,
  затем html.escape). Сырой `str(exc)` в чат не отдавать.
- MCP/anyio заворачивают ошибки в ExceptionGroup — для текста/анализа
  использовать `mcp.unwrap_error()/error_text()`.
- Миграции: `alembic/versions/000N_имя.py`, ручной стиль (op.*), нумерация
  сквозная; создал модель → не забудь экспорт в `app/db/models/__init__.py`.
- Новая команда бота → добавь в `app/bot/commands.py` И в
  `app/llm/capabilities.py` (тест-страж test_capabilities это проверяет),
  роутер — в `app/bot/setup.py` ДО chat.router (catch-all), слэш-скиллы
  (`skills_cmd.invoke_router`) — после.
- LLM-поведение чинится структурно, а не только промптом: инструкции в
  результатах инструментов (см. FAILURE_NUDGE в tools/sandbox.py) держат
  модель сильнее системного промпта.

## Архитектура — куда смотреть

- `app/services/llm_chat.py` — ядро: tool-цикл, эскалация на smart_model
  (3+ итерации или упавший инструмент), фильтр allowed_tools (скиллы),
  стриминг с накоплением раундов, детектор утечек tool-синтаксиса.
- `app/tools/registry.py` + `app/tools/*` — статические инструменты
  (register()); `app/services/mcp.py` — динамические MCP-инструменты
  (кэш в Redis + tools_cache в БД); executor получает per-turn tools_map.
- `app/services/mcp_auth.py` + `app/api/routes/oauth.py` — OAuth MCP
  (DbTokenStorage, интерактивный флоу: ссылка в чат → callback по state).
- `app/api/routes/hooks.py` — вебхуки: notify → сразу в чат; agent/skill →
  ScheduledTask, воркер подхватит ≤20с.
- `app/services/skills.py` — скиллы: build_prompt, filter_tools (fnmatch),
  enqueue_run; слэш-вызов — handlers/skills_cmd.py.
- `app/worker.py` — крон: свип задач (атомарный захват claim_task),
  дайджесты, сжатие истории, доиндексация памяти.
- `app/bot/middlewares/` — цепочка db → throttle → auth (whitelist,
  is_active) → workspace (+ сохранение входящих, метки реплаев/форвардов);
  callback_query идёт через ту же цепочку.
- Публичный вход: Caddy (Caddyfile) проксирует ТОЛЬКО /hooks/* и /oauth/*
  на app:8000; дашборд и /stats — только localhost.

## Проверка перед коммитом

1. `python3 -m py_compile` изменённых файлов.
2. Пересборка + `docker compose ps` (оба healthy) + `pytest -q` зелёный.
3. Что можно — проверить вживую (curl роутов, python в контейнере,
   EXPLAIN для индексов, реальный MCP-сервер).
4. Коммит на каждый логический блок, сообщения по-русски, с «почему».
