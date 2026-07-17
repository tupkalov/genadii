from types import SimpleNamespace

from app.services.messages import _decorate


def _msg(**kwargs):
    defaults = dict(
        text="привет",
        caption=None,
        photo=None,
        quote=None,
        forward_origin=None,
        reply_to_message=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _user(first_name=None, username=None, id=1, is_bot=False):
    return SimpleNamespace(
        first_name=first_name, username=username, id=id, is_bot=is_bot
    )


def test_reply_target_text_is_included():
    reply = _msg(text="в пятницу едем на дачу", caption=None)
    reply.from_user = _user(first_name="Ари")
    message = _msg(text="@bot а во сколько?", reply_to_message=reply)

    decorated = _decorate(message, message.text)
    assert "[в ответ на сообщение Ари: «в пятницу едем на дачу»]" in decorated
    assert decorated.endswith("@bot а во сколько?")


def test_reply_quote_takes_priority_over_full_text():
    reply = _msg(text="длинное сообщение про всё сразу и про дачу тоже")
    reply.from_user = _user(username="ari")
    message = _msg(
        text="@bot поясни",
        reply_to_message=reply,
        quote=SimpleNamespace(text="про дачу"),
    )

    decorated = _decorate(message, message.text)
    assert "[в ответ на сообщение ari: «про дачу»]" in decorated
    assert "длинное сообщение" not in decorated


def test_reply_to_photo_without_text():
    reply = _msg(text=None, caption=None, photo=[object()])
    reply.from_user = _user(first_name="Тимми")
    message = _msg(text="@bot что на фото?", reply_to_message=reply)

    decorated = _decorate(message, message.text)
    assert "[в ответ на сообщение Тимми: «[фото]»]" in decorated


def test_long_reply_text_is_truncated():
    reply = _msg(text="х" * 1000)
    reply.from_user = _user(first_name="Леха")
    message = _msg(text="@bot tl;dr", reply_to_message=reply)

    decorated = _decorate(message, message.text)
    assert "х" * 400 + "…" in decorated
    assert "х" * 401 not in decorated


def test_reply_to_bot_own_message_is_directive():
    # Реплай на сообщение самого бота — директивный якорь темы, а не пассивная
    # метка. Реальный сбой: «Ещё раз давай» в ответ на ресёрч → офтоп из свежей
    # истории. Модель должна держаться процитированной темы.
    reply = _msg(text="Окей, поищу варианты доставки продуктов в Подгорице…")
    reply.from_user = _user(first_name="Умный Геннадий", is_bot=True)
    message = _msg(text="Ещё раз давай", reply_to_message=reply)

    decorated = _decorate(message, message.text)
    assert "на ТВОЁ прошлое сообщение" in decorated
    assert "доставки продуктов в Подгорице" in decorated
    assert "не на то, что писали в чате перед этим" in decorated
    assert decorated.endswith("Ещё раз давай")
    # Пассивная формулировка для чужих сообщений тут не используется
    assert "[в ответ на сообщение" not in decorated


def test_reply_to_human_stays_passive():
    # Реплай на человека — прежняя нейтральная метка (бот лишь наблюдатель)
    reply = _msg(text="в пятницу едем на дачу")
    reply.from_user = _user(first_name="Ари", is_bot=False)
    message = _msg(text="@bot а во сколько?", reply_to_message=reply)

    decorated = _decorate(message, message.text)
    assert "[в ответ на сообщение Ари:" in decorated
    assert "ТВОЁ прошлое сообщение" not in decorated


def test_no_reply_no_label():
    message = _msg(text="просто сообщение")
    assert _decorate(message, message.text) == "просто сообщение"
