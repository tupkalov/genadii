from aiogram.types import ReactionTypeEmoji

from app.tools.registry import Tool, ToolContext, register

# Telegram разрешает ограниченный набор эмодзи для реакций
ALLOWED = {
    "👍", "👎", "❤", "🔥", "🥰", "👏", "😁", "🤔", "🤯", "😱", "🤬",
    "😢", "🎉", "🤩", "🙏", "👌", "🕊", "🤡", "🥱", "🥴", "😍", "🐳",
    "❤‍🔥", "🌚", "🌭", "💯", "🤣", "⚡", "🍌", "🏆", "💔", "🤨", "😐",
    "🍓", "🍾", "💋", "🖕", "😈", "😴", "😭", "🤓", "👻", "👨‍💻", "👀",
    "🎃", "🙈", "😇", "😨", "🤝", "✍", "🤗", "🫡", "🎅", "🎄", "☃",
    "💅", "🤪", "🗿", "🆒", "💘", "🙉", "🦄", "😘", "💊", "🙊", "😎",
    "👾", "🤷‍♂", "🤷", "🤷‍♀", "😡",
}


async def _react(ctx: ToolContext, emoji: str) -> str:
    if ctx.bot is None or ctx.target_message_id is None:
        return "Реакции недоступны в этом контексте (не на сообщение)."
    emoji = emoji.strip()
    if emoji not in ALLOWED:
        return f"Эмодзи «{emoji}» не поддерживается Telegram для реакций."
    try:
        await ctx.bot.set_message_reaction(
            chat_id=ctx.chat_id,
            message_id=ctx.target_message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
        )
    except Exception as exc:  # noqa: BLE001
        return f"Не смог поставить реакцию: {exc}"
    return f"Реакция {emoji} поставлена."


register(
    Tool(
        name="react",
        description=(
            "Поставить эмодзи-реакцию на сообщение пользователя. Используй, когда "
            "реакции достаточно и текстовый ответ не нужен (согласие, смех, лайк), "
            "или в дополнение к короткому ответу. Не злоупотребляй."
        ),
        parameters={
            "type": "object",
            "properties": {
                "emoji": {
                    "type": "string",
                    "description": "Один эмодзи из разрешённых Telegram (👍 ❤ 🔥 😁 🤔 🎉 …)",
                }
            },
            "required": ["emoji"],
        },
        handler=_react,
        default_enabled=True,
    )
)
