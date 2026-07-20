"""Когда в группе сообщение адресовано боту (триггер ответа)."""
from types import SimpleNamespace

from app.bot.handlers.chat import _addressed_to_bot

BOT = "smartgenadii_bot"


def _msg(text=None, reply_from=None):
    reply = None
    if reply_from is not None:
        reply = SimpleNamespace(from_user=SimpleNamespace(username=reply_from))
    return SimpleNamespace(text=text, caption=None, reply_to_message=reply)


def test_direct_mention_addressed():
    assert _addressed_to_bot(_msg(f"@{BOT} привет"), BOT) is True


def test_reply_to_bot_without_mention_addressed():
    assert _addressed_to_bot(_msg("а подробнее?", reply_from=BOT), BOT) is True


def test_mention_other_user_not_addressed():
    # обычное упоминание другого участника — не к боту
    assert _addressed_to_bot(_msg("@zatopeeelo видишь"), BOT) is False


def test_reply_to_bot_but_mentions_other_not_addressed():
    # реальный баг: реплай на сообщение бота, но текст адресован другому
    assert _addressed_to_bot(
        _msg("@zatopeeelo видишь как я вас ценить стал", reply_from=BOT), BOT
    ) is False


def test_mention_bot_and_other_addressed():
    # если среди упоминаний есть бот — отвечаем
    assert _addressed_to_bot(_msg(f"@zatopeeelo @{BOT} гляньте"), BOT) is True


def test_email_not_treated_as_mention():
    # e-mail не должен считаться упоминанием (иначе съел бы реплай на бота)
    assert _addressed_to_bot(_msg("пиши на a@b.com", reply_from=BOT), BOT) is True


def test_plain_message_no_reply_not_addressed():
    assert _addressed_to_bot(_msg("просто болтаю"), BOT) is False
