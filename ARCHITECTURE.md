# Умный Геннадий — Architecture Plan

Self-hosted Telegram AI bot для владельца и его друзей.
Цель: прозрачная система вместо OpenClaw-like бота: Telegram bot + workspaces +
memory + tools + long-running tasks + logs.

## 1. Ключевые решения

| Область | Решение |
|---|---|
| Язык / рантайм | Python 3.12, asyncio |
| Telegram | aiogram 3.x, long polling (webhook — опционально позже) |
| HTTP API | FastAPI (health, admin, logs, статистика расходов) |
| БД | PostgreSQL 16 + расширение **pgvector** (семантическая память) |
| Кэш / очереди | Redis (FSM aiogram, rate limits, очередь фоновых задач) |
| Фоновые задачи | **arq** (лёгкий, поверх Redis) — напоминания, long-running tasks |
| LLM | **OpenRouter**. Дефолт — дешёвая модель; per-workspace/per-задача апгрейд на дорогую |
| Учёт расходов | Таблица `llm_usage`: каждый вызов LLM пишет модель, токены, cost, workspace |
| ORM / миграции | SQLAlchemy 2 (async, asyncpg) + Alembic |
| Конфиг | pydantic-settings, все secrets только из env |
| Деплой | Docker Compose: `app` (FastAPI+bot), `worker` (arq), `postgres`, `redis` |

Процессная модель MVP: один контейнер `app` запускает FastAPI (uvicorn) и
aiogram-поллинг как фоновую asyncio-задачу — минимум движущихся частей.
`worker` добавляется в Milestone 5 (напоминания).

## 2. Доступ и роли

- **Whitelist в БД**: таблица `users`, поле `role` (`admin` | `member`), `is_active`.
- Владелец задаётся через env `ADMIN_TG_IDS` — бутстрапится в БД при старте.
- Админ добавляет друзей: `/invite <tg_id | @username>` или одноразовые invite-коды.
- Незнакомцам бот вежливо отказывает, попытка логируется в `audit_log`.

## 3. Workspaces

Разделение personal / group — фундамент схемы:

- **personal** — личка с ботом: один workspace на пользователя.
- **group** — групповой чат: один workspace на `tg_chat_id`.

`WorkspaceResolver` (middleware aiogram): по типу чата находит/создаёт workspace,
кладёт его в контекст хендлеров. Память, настройки (модель, персона, tools) и
статистика расходов — всё per-workspace. Личная память не утекает в группу.

## 4. Модель данных (ядро)

```
users               tg_id, username, role, is_active, invited_by, created_at
workspaces          id, type(personal|group), tg_chat_id, title, settings(jsonb), created_at
workspace_members   workspace_id, user_id, role
messages            id, workspace_id, user_id?, tg_message_id?, role(user|assistant|tool|system),
                    content, created_at
llm_usage           id, workspace_id, message_id?, model, prompt_tokens, completion_tokens,
                    cost_usd, latency_ms, created_at
memory_entries      id, workspace_id, kind(fact|note), content, embedding vector(1536)?,
                    created_by, created_at, archived_at?
tool_permissions    workspace_id, tool_name, enabled, granted_by, granted_at
audit_log           id, workspace_id?, user_id?, action, payload(jsonb), created_at
scheduled_tasks     id, workspace_id, user_id, kind(reminder|job), payload(jsonb),
                    run_at / cron, status, created_at        # используется с M5
```

`workspaces.settings` (jsonb): `model_override`, `persona`, лимиты — гибкость без миграций.

## 5. LLM-слой

- `llm/client.py` — тонкий клиент OpenRouter (httpx), streaming не в MVP.
- `llm/router.py` — выбор модели: `settings.default_model` (дешёвая) →
  `workspace.settings.model_override` → в будущем эскалация по типу задачи.
- Каждый вызов пишет запись в `llm_usage`; cost берём из ответа OpenRouter
  (`usage` + generation stats). API-эндпоинт `/stats/usage` — расход по чатам.
- Контекст: system prompt (персона Геннадия) + релевантные memory-факты +
  последние N сообщений workspace.

## 6. Tools

- `tools/registry.py` — декларативный реестр: имя, JSON-schema параметров,
  требуемое permission.
- Разрешения per-workspace (`tool_permissions`), включает админ.
- Каждый вызов tool — запись в `audit_log` (кто, где, что, параметры, результат).

Состав по milestone'ам:
1. **memory** — remember/recall (факты + pgvector-поиск)
2. **reminders** — «напомни завтра в 10» (arq + scheduled_tasks)
3. **web** — search (Tavily/Brave) + fetch URL (readability-извлечение)
4. **sandbox** — Геннадий пишет и запускает код в изолированном контейнере
   (отдельный runner-контейнер: без доступа к хосту и основной сети, CPU/RAM/время
   ограничены, whitelist pip-пакетов). Сценарии: клиент Todoist, калькуляторы,
   отчёты, планы. **Сознательно вне MVP** (по ТЗ п.8) — но registry и permissions
   проектируются так, чтобы он встал как обычный tool.

## 7. Структура проекта

```
smart-gennady/
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── pyproject.toml
├── alembic.ini
├── alembic/versions/
└── app/
    ├── main.py              # FastAPI + запуск aiogram-поллинга
    ├── config.py            # pydantic-settings
    ├── db/
    │   ├── session.py
    │   └── models/          # user, workspace, message, memory, usage, audit, ...
    ├── bot/
    │   ├── setup.py         # Dispatcher, регистрация роутеров/middleware
    │   ├── middlewares/     # auth (whitelist), workspace resolver, db session
    │   └── handlers/        # start, whoami, chat, admin
    ├── api/routes/          # health, stats, admin
    ├── llm/                 # client, router (с M3)
    ├── tools/               # registry, permissions (каркас с M4)
    ├── memory/              # (с M4)
    └── services/            # бизнес-логика поверх моделей
```

## 8. Milestones

| # | Содержание | Проверка |
|---|---|---|
| **M1** | Структура, Docker Compose, config, FastAPI `/health`, aiogram echo-заглушка, подключение Postgres/Redis | `docker compose up`, `/health` = ok, бот отвечает |
| **M2** | SQLAlchemy-модели, Alembic-миграции, whitelist-auth, `/start`, `/whoami`, workspace resolver, сохранение messages, бутстрап админа | `/whoami` показывает роль и workspace; сообщения видны в БД; чужак получает отказ |
| M3 | OpenRouter: чат с Геннадием, персона, контекст из истории, `llm_usage` + `/stats/usage`, `/model` | диалог работает, расходы считаются по чатам |
| M4 | Tool-каркас: registry, permissions, audit_log; memory-tool + pgvector | «запомни/что ты помнишь», записи в audit |
| M5 | arq-worker, scheduled_tasks, напоминания | «напомни через 2 минуты» срабатывает |
| M6 | Web search + fetch URL | вопрос с поиском в интернете |
| M7 | Sandbox-runner: изолированное исполнение кода | Геннадий пишет и запускает скрипт-калькулятор |
| M8 | Admin/UX: `/invite`, лимиты расходов, просмотр логов через API | — |

## 9. Вне скоупа MVP

- shell/browser automation на хосте (заменено sandbox-runner'ом в M7)
- streaming-ответы, голос, изображения
- веб-UI (только HTTP API)

## 10. Пост-MVP: слой интеграций (итерации 12-13)

Документ выше — исходный план MVP; вне скоупа из §9 давно реализовано
(стриминг, голос, изображения, веб-дашборд). Поверх ядра вырос слой
универсальных интеграций:

| Компонент | Что | Ключевые файлы |
|---|---|---|
| MCP-клиент | Инструменты внешних MCP-серверов (Streamable HTTP) подключаются per-workspace; OAuth-флоу через браузер (DbTokenStorage + /oauth/callback); stdio-серверы — supergateway-sidecar в compose | `services/mcp.py`, `services/mcp_auth.py`, `api/routes/oauth.py` |
| Входящие вебхуки | POST /hooks/{token} → уведомление в чат или агентский ход через очередь задач | `api/routes/hooks.py`, `handlers/webhooks.py` |
| Скиллы | Именованные сценарии (инструкция + allowlist инструментов, fnmatch-маски); запуск: /имя, вебхук, cron, самим ботом | `services/skills.py`, `handlers/skills_cmd.py`, `tools/skills_tools.py` |
| Публичный вход | Caddy (авто-TLS) проксирует только /hooks/* и /oauth/*; остальной API — localhost | `Caddyfile` |
| Самоописание | `llm/capabilities.py` — единый источник правды о функционале, отдаётся боту инструментом bot_help | `tools/help.py` |

Принципы, дополнившие исходные решения:
- **Всё per-workspace** (MCP-серверы, вебхуки, скиллы) и доступно любому
  участнику чата; изоляция чатов — инвариант.
- **Динамические инструменты**: executor получает per-turn карту инструментов
  (статические + MCP + фильтр скилла), а не только глобальный реестр.
- **Поведение LLM чинится структурно**: инструкции в результатах упавших
  инструментов, эскалация на reasoning-модель при ошибках, детектор утечек
  tool-синтаксиса — а не только строчки в системном промпте.
