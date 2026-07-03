# Умный Геннадий 🧠

Self-hosted Telegram AI bot для владельца и его друзей.
Архитектура и план — в [ARCHITECTURE.md](ARCHITECTURE.md).

## Быстрый старт

1. Создай бота у [@BotFather](https://t.me/BotFather), получи токен.
2. Узнай свой Telegram ID (например, у [@userinfobot](https://t.me/userinfobot)).
3. Настрой окружение:

```bash
cp .env.example .env
# отредактируй .env: BOT_TOKEN, ADMIN_TG_IDS, POSTGRES_PASSWORD (+ тот же пароль в DATABASE_URL)
```

4. Запусти:

```bash
docker compose up --build -d
```

Миграции применяются автоматически при старте контейнера `app`.

## Проверка (Milestone 1–2)

| Что | Как | Ожидание |
|---|---|---|
| Сервисы живы | `docker compose ps` | все `running (healthy)` |
| Health | `curl localhost:8000/health` | `{"status":"ok","db":true,"redis":true}` |
| Бот отвечает | `/start` в личке | приветствие Геннадия |
| Твоя роль | `/whoami` | роль `admin`, workspace `personal` |
| Групповой workspace | добавить бота в группу, `/whoami` там | workspace `group` |
| Сообщения пишутся | см. ниже | строки в таблице `messages` |
| Whitelist | написать боту с чужого аккаунта | отказ + запись `access_denied` в `audit_log` |

Заглянуть в БД:

```bash
docker compose exec postgres psql -U gennady -d gennady \
  -c "SELECT id, workspace_id, role, left(content, 40) AS content, created_at FROM messages ORDER BY id DESC LIMIT 10;"

docker compose exec postgres psql -U gennady -d gennady \
  -c "SELECT action, payload, created_at FROM audit_log ORDER BY id DESC LIMIT 10;"
```

Логи приложения:

```bash
docker compose logs -f app
```

## Статус milestone'ов

- [x] M1 — каркас, Docker Compose, config, FastAPI, aiogram, Postgres/Redis
- [x] M2 — модели, миграции, whitelist, `/start`, `/whoami`, workspace resolver, сохранение сообщений
- [x] M3 — OpenRouter, персона per-workspace, `/persona`, `/model`, `/stats`, учёт расходов (`llm_usage`, API `/stats/usage`)
- [x] M4 — tool-каркас (registry, permissions, audit), память: remember/recall tools, `/memory`, `/forget`, pgvector (semantic при наличии `OPENAI_API_KEY`, иначе текстовый поиск)
- [x] M5 — напоминания: tool `remind`, `/tasks [cancel N]`, arq-worker (sweeper по БД каждые 20 сек)
- [x] M5.5 — инвайты (`/invite`, `/kick`, `/users`), ошибки в чат (global error handler), самопробуждение: tool `schedule_task` (one-shot и cron) — worker выполняет LLM-ход с инструментами и пишет результат в чат
- [x] M6 — tools `web_search` (Tavily) + `fetch_url` (с SSRF-защитой)
- [x] M7 — sandbox-runner: tool `run_python` (выключен по умолчанию — `/tools enable run_python`), изолированный контейнер: отдельная сеть без доступа к БД/Redis, read-only ФС, без root, cap_drop ALL, лимиты CPU/RAM/pids, таймаут 30с
- [x] M8 — markdown-рендеринг ответов (MD→Telegram HTML с фолбэком), месячные лимиты расходов (`/budget`, enforcement в чате и в worker'е), API `GET /logs/audit`
- [x] Итерация 1 (надёжность) — API на localhost, восстановление зависших задач, ON CONFLICT на создании user/workspace, healthchecks всех сервисов, суточные бэкапы Postgres (`./backups`, 7 дней), retry+доиндексация embeddings, лимит кода sandbox 100КБ
- [x] Итерация 2 (медиа) — vision (фото понимает, `VISION_MODEL`), голосовые (транскрипция, `AUDIO_MODEL`), генерация картинок (tool `generate_image`, выкл. по умолчанию, `IMAGE_MODEL`), метаданные форвардов в контексте + `/invite` по reply на пересланное сообщение
- [x] Итерация 3 (интеллект) — tool `read_chat_history` («что я пропустил?»), ежечасное сжатие старой истории в сводку (`history_summary` в settings, экономия токенов), сохраняемые скрипты: tools `save_script`/`run_saved_script`/`list_scripts` (выкл. по умолчанию), `/scripts [show|delete]`, миграция `0002`
