import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

logger = logging.getLogger("gennady.commands")

COMMON_COMMANDS = [
    BotCommand(command="start", description="Знакомство и настройка"),
    BotCommand(command="whoami", description="Кто ты для меня и какой это workspace"),
    BotCommand(command="persona", description="Мой характер в этом чате"),
    BotCommand(command="memory", description="Что я помню в этом чате"),
    BotCommand(command="forget", description="Забыть факт: /forget номер"),
    BotCommand(command="tasks", description="Напоминания и отложенные задачи"),
    BotCommand(command="tools", description="Мои инструменты в этом чате"),
    BotCommand(command="model", description="Какая модель думает за меня"),
    BotCommand(command="scripts", description="Сохранённые скрипты этого чата"),
    BotCommand(command="proactive", description="Болтливость в группе (0–100%)"),
    BotCommand(command="heartbeat", description="Мой пульс: просыпаюсь ли сам (on/off)"),
    BotCommand(command="initiative", description="Насколько пишу сам: 0–100%"),
    BotCommand(command="digest", description="Ежедневный отчёт расходов в личку"),
    BotCommand(command="stats", description="Расходы этого чата"),
    BotCommand(command="budget", description="Месячный лимит расходов"),
    BotCommand(command="skill", description="Скиллы этого чата (сценарии /имя)"),
    BotCommand(command="mcp", description="MCP-серверы этого чата"),
    BotCommand(command="hook", description="Входящие вебхуки этого чата"),
    BotCommand(command="undo", description="Стереть последний обмен из истории"),
    BotCommand(command="retry", description="Перегенерировать ответ (/retry smart)"),
    BotCommand(command="search", description="Поиск по памяти и переписке"),
]

ADMIN_COMMANDS = [
    BotCommand(command="invite", description="Добавить в whitelist: id или reply"),
    BotCommand(command="kick", description="Убрать из whitelist: id или reply"),
    BotCommand(command="users", description="Список пользователей"),
    BotCommand(command="dashboard", description="Как открыть веб-дашборд"),
]


async def setup_bot_commands(bot: Bot, admin_ids: set[int]) -> None:
    """Регистрирует меню команд: общее — всем, админам в личке — расширенное."""
    await bot.set_my_commands(COMMON_COMMANDS, scope=BotCommandScopeDefault())
    for admin_id in admin_ids:
        try:
            await bot.set_my_commands(
                COMMON_COMMANDS + ADMIN_COMMANDS,
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except TelegramBadRequest as exc:
            # админ ещё ни разу не писал боту — Telegram не знает такой чат
            logger.warning("Не смог задать команды для админа %s: %s", admin_id, exc)
