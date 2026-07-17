from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    bot_token: str
    admin_tg_ids: str = ""  # comma-separated Telegram IDs

    database_url: str = "postgresql+asyncpg://gennady:gennady@postgres:5432/gennady"
    redis_url: str = "redis://redis:6379/0"

    # LLM (Milestone 3)
    openrouter_api_key: str = ""
    default_model: str = "deepseek/deepseek-v4-flash"
    # Эскалация при зацикливании на инструментах (Ит.10) — reasoning-версия
    # того же класса, не топовый флагман. ID именно OpenRouter'а
    # («deepseek-reasoner» — это имя из нативного API DeepSeek, тут его нет)
    smart_model: str = "deepseek/deepseek-r1-0528"
    history_limit: int = 30  # сколько последних сообщений чата отдаём в контекст
    # Пауза после последнего сообщения перед ответом: серия сообщений/форвардов
    # получает один общий ответ вместо ответа на каждое
    reply_debounce_seconds: float = 3.0
    # База для публичных URL вебхуков (https://bot.example.com, без слэша в
    # конце) — прокси пользователя форвардит /hooks/* на 127.0.0.1:8000
    webhook_base_url: str = ""
    rate_limit_per_minute: int = 20  # мягкий лимит сообщений на пользователя, 0 = выкл
    proactive_cooldown: int = 300  # мин. пауза между проактивными репликами в чате, сек

    stream_responses: bool = True  # печатать ответ постепенно (правка сообщения)
    stream_edit_interval: float = 1.7  # как часто править сообщение при стриминге, сек

    # Guard: перед отправкой длинного ответа проверять, что он по теме последнего
    # сообщения (ловит не-sequitur слабой модели). Одна дешёвая доп-проверка.
    guard_offtopic: bool = True

    # Хартбит: бот сам по таймеру просыпается на чат и решает, не написать ли
    # первым (напоминания, оборванные темы, факты из памяти, изредка чек-ин).
    # Сильный уклон в молчание — «сбалансированно» ≈ пара сообщений в день при
    # реальном поводе. Включено по умолчанию, отключается per-chat (/heartbeat).
    heartbeat_default_on: bool = True
    heartbeat_interval_minutes: int = 180  # как часто РАЗМЫШЛЯТЬ (не «говорить»)
    heartbeat_min_silence_minutes: int = 45  # не встревать, пока чат «живой»
    heartbeat_quiet_start_hour: int = 22  # тихие часы (по settings.timezone): не пишем
    heartbeat_quiet_end_hour: int = 9

    # Субъектность (отдельно от пульса): 0–100% — вероятность, что «тик» хартбита
    # обернётся реальным сообщением, и насколько спонтанно (0 — никогда не пишет
    # первым, 100 — компаньон). Пульс задаёт частоту размышлений, initiative —
    # шанс заговорить. Меняется per-chat (/initiative) и самим ботом на просьбу.
    initiative_default_percent: int = 30

    # Мультимодальность (Итерация 2): дефолт не умеет картинки/аудио,
    # для них подключаются отдельные модели
    vision_model: str = "google/gemini-2.5-flash"
    audio_model: str = "google/gemini-2.5-flash"
    image_model: str = "google/gemini-2.5-flash-image"

    # Web search (Milestone 6)
    tavily_api_key: str = ""

    # Sandbox-runner (Milestone 7)
    sandbox_url: str = "http://sandbox:8100"

    # Embeddings для семантической памяти — через OpenRouter, тем же ключом.
    # Важно: размерность модели должна совпадать с Vector(1536) в memory_entries.
    embedding_model: str = "openai/text-embedding-3-small"

    timezone: str = "Europe/Moscow"  # локальное время для напоминаний и промпта

    # Дефолтный месячный лимит LLM-расходов на workspace, $. 0 = без лимита.
    # Переопределяется per-workspace командой /budget.
    default_monthly_budget_usd: float = 0

    # Хост сервера для подсказки про дашборд (для SSH-туннеля). Пусто — покажем плейсхолдер.
    server_host: str = ""

    env: str = "dev"

    @property
    def admin_ids(self) -> set[int]:
        return {int(x) for x in self.admin_tg_ids.replace(" ", "").split(",") if x}


@lru_cache
def get_settings() -> Settings:
    return Settings()
