"""Markdown от LLM -> Telegram HTML, с фолбэком на plain text."""
import html
import re

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

TG_LIMIT = 3500  # запас до 4096 на HTML-теги


def md_to_html(text: str) -> str:
    tokens: list[str] = []

    def stash(content: str, tag: str) -> str:
        tokens.append(f"<{tag}>{html.escape(content)}</{tag}>")
        return f"\x00{len(tokens) - 1}\x00"

    # Код прячем до эскейпа, чтобы не форматировать его содержимое
    text = re.sub(
        r"```[a-zA-Z0-9_+~-]*\n?(.*?)```",
        lambda m: stash(m.group(1).rstrip(), "pre"),
        text,
        flags=re.S,
    )
    text = re.sub(r"`([^`\n]+)`", lambda m: stash(m.group(1), "code"), text)

    text = html.escape(text)

    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', text
    )
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.S)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text, flags=re.S)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text, flags=re.S)
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.M)
    text = re.sub(r"^(\s*)[*-]\s+", r"\1• ", text, flags=re.M)
    # Одиночные звёздочки-курсив — после жирного и списков
    text = re.sub(r"(?<![\w*])\*([^*\n]+?)\*(?![\w*])", r"<i>\1</i>", text)

    return re.sub(r"\x00(\d+)\x00", lambda m: tokens[int(m.group(1))], text)


def _truncate(text: str) -> str:
    return text[:TG_LIMIT] + "…" if len(text) > TG_LIMIT else text


async def reply_rendered(message: Message, text: str, as_reply: bool = False) -> Message:
    """Ответ в чат с рендерингом markdown; при кривой разметке — plain text."""
    text = _truncate(text)
    send = message.reply if as_reply else message.answer
    try:
        return await send(md_to_html(text), parse_mode="HTML")
    except TelegramBadRequest:
        return await send(text, parse_mode=None)


async def send_rendered(bot: Bot, chat_id: int, text: str) -> Message:
    text = _truncate(text)
    try:
        return await bot.send_message(chat_id, md_to_html(text), parse_mode="HTML")
    except TelegramBadRequest:
        return await bot.send_message(chat_id, text, parse_mode=None)
