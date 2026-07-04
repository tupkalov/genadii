from app.services import messages


async def test_delete_last_exchange_removes_user_and_reply(session, workspace, user):
    await messages.save_user_text(session, workspace, user, "первый вопрос")
    await messages.save_assistant(session, workspace, "первый ответ")
    await messages.save_user_text(session, workspace, user, "второй вопрос")
    await messages.save_assistant(session, workspace, "второй ответ")
    await messages.save_assistant(session, workspace, "[картинка]")
    await session.commit()

    deleted = await messages.delete_last_exchange(session, workspace)
    await session.commit()
    assert deleted == 3  # второй вопрос + два assistant-сообщения

    from sqlalchemy import select

    from app.db.models import Message

    rest = (
        await session.scalars(
            select(Message.content).where(Message.workspace_id == workspace.id)
        )
    ).all()
    assert set(rest) == {"первый вопрос", "первый ответ"}


async def test_delete_last_exchange_empty_history(session, workspace, user):
    assert await messages.delete_last_exchange(session, workspace) == 0


async def test_delete_trailing_assistant_keeps_user_turn(session, workspace, user):
    await messages.save_user_text(session, workspace, user, "вопрос")
    await messages.save_assistant(session, workspace, "ответ 1")
    await messages.save_assistant(session, workspace, "ответ 2")
    await session.commit()

    deleted = await messages.delete_trailing_assistant(session, workspace)
    await session.commit()
    assert deleted == 2

    from sqlalchemy import select

    from app.db.models import Message

    rest = (
        await session.scalars(
            select(Message.content).where(Message.workspace_id == workspace.id)
        )
    ).all()
    assert rest == ["вопрос"]


async def test_delete_trailing_assistant_unanswered_returns_zero(
    session, workspace, user
):
    await messages.save_user_text(session, workspace, user, "вопрос без ответа")
    await session.commit()
    assert await messages.delete_trailing_assistant(session, workspace) == 0


async def test_delete_trailing_assistant_no_user_returns_none(session, workspace, user):
    assert await messages.delete_trailing_assistant(session, workspace) is None
