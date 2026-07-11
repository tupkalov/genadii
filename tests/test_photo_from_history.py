"""Фото из истории → vision, когда о нём спрашивают позже без реплая."""
from app.bot.handlers.chat import _PHOTO_REF_RE
from app.services import messages


def test_photo_ref_regex_matches_common_phrasings():
    for text in (
        "сколько на фотке глютена",
        "@bot что на фото?",
        "опиши картинку",
        "разбери этот снимок",
        "what's on the image",
    ):
        assert _PHOTO_REF_RE.search(text), text


def test_photo_ref_regex_ignores_unrelated_text():
    for text in ("привет как дела", "посчитай 2+2", "напомни завтра в 9"):
        assert not _PHOTO_REF_RE.search(text), text


async def test_latest_photo_file_id_returns_recent(session, workspace, user):
    await messages.save_user_text(session, workspace, user, "болтовня")
    await messages.save_user_text(
        session, workspace, user, "[фото]", media_file_id="AgACfileid123"
    )
    await messages.save_user_text(session, workspace, user, "ещё болтовня")
    await session.commit()

    assert await messages.latest_photo_file_id(session, workspace) == "AgACfileid123"


async def test_latest_photo_file_id_none_without_photos(session, workspace, user):
    await messages.save_user_text(session, workspace, user, "просто текст")
    await session.commit()
    assert await messages.latest_photo_file_id(session, workspace) is None


async def test_latest_photo_file_id_skips_stale(session, workspace, user):
    from datetime import timedelta

    from sqlalchemy import update

    from app.db.models import Message

    msg = await messages.save_user_text(
        session, workspace, user, "[фото]", media_file_id="oldfile"
    )
    # Сдвигаем во времени за окно свежести — «протухшее» фото не подтягиваем
    await session.execute(
        update(Message)
        .where(Message.id == msg.id)
        .values(created_at=msg.created_at - messages.RECENT_PHOTO_WINDOW - timedelta(minutes=1))
    )
    await session.commit()

    assert await messages.latest_photo_file_id(session, workspace) is None
