import asyncio
import base64
import html
import logging
import random
import time
from dataclasses import dataclass, field

from aiogram import F, Router
from aiogram.types import BufferedInputFile, Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.formatting import reply_rendered, send_rendered
from app.config import get_settings
from app.db.models import User, Workspace, WorkspaceType
from app.db.session import session_factory
from app.llm import client
from app.llm.client import LlmError
from app.services import alerts, budget, documents, llm_chat, messages

_redis = Redis.from_url(get_settings().redis_url)

logger = logging.getLogger("gennady.chat")

router = Router(name="chat")

ERROR_REPLY = "😔 Что-то мозги отказали (ошибка LLM). Попробуй ещё раз, а админ пусть глянет логи."
# Пока бот недавно отвечал в чате, proactive-встревания подавляются
BOT_ACTIVE_SECONDS = 180


async def _mark_bot_active(chat_id: int) -> None:
    try:
        await _redis.set(f"botactive:{chat_id}", "1", ex=BOT_ACTIVE_SECONDS)
    except Exception as exc:
        logger.debug("Не смог поставить метку активности бота: %s", exc)
NO_KEY_REPLY = "🧠 Мозги ещё не подключены: админ не задал OPENROUTER_API_KEY."
BUDGET_REPLY = (
    "⛔ Месячный бюджет чата исчерпан (${spend:.2f} из ${limit:.2f}). "
    "Молчу до нового месяца — или админ поднимет лимит: /budget"
)

TRANSCRIBE_PROMPT = (
    "Транскрибируй это голосовое сообщение дословно, на языке оригинала. "
    "Верни только текст, без комментариев."
)


def _addressed_to_bot(message: Message, bot_username: str) -> bool:
    content = message.text or message.caption or ""
    if f"@{bot_username}" in content:
        return True
    reply = message.reply_to_message
    return bool(
        reply and reply.from_user and reply.from_user.username == bot_username
    )


async def _check_budget(message: Message, session: AsyncSession, workspace: Workspace) -> bool:
    over, spend, limit = await budget.check(session, workspace)
    if over:
        await message.answer(BUDGET_REPLY.format(spend=spend, limit=limit))
    return over


class _StreamEditor:
    """Троттлит правки Telegram-сообщения по мере стриминга ответа."""

    def __init__(self, placeholder: Message, interval: float) -> None:
        self.placeholder = placeholder
        self.interval = interval
        self.latest = ""
        self.last_edit = 0.0
        self._lock = asyncio.Lock()
        # Флаг вместо проверки _lock.locked(): между create_task и захватом
        # лока таском следующая feed успела бы создать дубль-flush
        self._flush_scheduled = False

    def feed(self, text: str) -> None:
        self.latest = text
        if time.monotonic() - self.last_edit >= self.interval and not self._flush_scheduled:
            self._flush_scheduled = True
            asyncio.create_task(self._flush())

    async def _flush(self) -> None:
        async with self._lock:
            self._flush_scheduled = False
            self.last_edit = time.monotonic()
            text = self.latest.strip()[:3900]
            if not text:
                return
            try:
                await self.placeholder.edit_text(text + " ▍", parse_mode=None)
            except Exception as exc:
                # 429/not-modified — не критично, финальная правка всё поправит
                logger.debug("Stream-правка не прошла: %s", exc)


async def _send_attachments(
    message: Message, workspace: Workspace, session: AsyncSession, images: list[bytes]
) -> None:
    for image in images[:2]:
        try:
            photo_msg = await message.answer_photo(
                BufferedInputFile(image, filename="gennady.png")
            )
            await messages.save_assistant(
                session, workspace, "[картинка]", tg_message_id=photo_msg.message_id
            )
        except Exception:
            logger.exception("Не смог отправить сгенерированную картинку")


async def _generate_and_send(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
    extra_user_message: str | list[dict] | None = None,
    force_model: str | None = None,
) -> None:
    """Общий пайплайн: бюджет -> LLM (с tools, стриминг) -> ответ + вложения -> учёт."""
    if await _check_budget(message, session, workspace):
        return

    # Метка «бот сейчас общается в этом чате» — proactive не должен встревать
    # в живой диалог своей запоздавшей репликой (ставим до генерации: она долгая)
    await _mark_bot_active(message.chat.id)

    settings = get_settings()
    as_reply = workspace.type == WorkspaceType.group

    editor: _StreamEditor | None = None
    on_delta = None
    if settings.stream_responses:
        # Черновик без уведомления: единственный пуш пользователь получит от
        # финального сообщения с готовым текстом, а не от «⌨️ …»
        placeholder = await (
            message.reply("⌨️ …", disable_notification=True)
            if as_reply
            else message.answer("⌨️ …", disable_notification=True)
        )
        editor = _StreamEditor(placeholder, settings.stream_edit_interval)
        on_delta = editor.feed
    else:
        await message.bot.send_chat_action(message.chat.id, "typing")

    async def _drop_placeholder() -> None:
        if editor is None:
            return
        try:
            await editor.placeholder.delete()
        except Exception as exc:
            logger.debug("Не смог удалить стриминговый черновик: %s", exc)

    try:
        outcome = await llm_chat.generate_reply(
            session, workspace, user,
            extra_user_message=extra_user_message,
            bot=message.bot,
            chat_id=message.chat.id,
            target_message_id=message.message_id,
            on_delta=on_delta,
            force_model=force_model,
        )
    except LlmError as exc:
        logger.error("LLM error (workspace=%s): %s", workspace.id, exc)
        await alerts.record_llm_failure(message.bot)
        reply = NO_KEY_REPLY if "OPENROUTER_API_KEY" in str(exc) else ERROR_REPLY
        await _drop_placeholder()
        await message.answer(reply)
        return

    text = outcome.text.strip() or "…"

    # Черновик стримился правками (без пушей) — финал уходит новым сообщением,
    # чтобы пользователю пришло уведомление с готовым текстом
    await _drop_placeholder()
    sent = await reply_rendered(message, text, as_reply=as_reply)

    saved = await messages.save_assistant(
        session, workspace, text, tg_message_id=sent.message_id
    )
    await llm_chat.log_usages(session, workspace, outcome.usages, message_id=saved.id, user_id=user.id)
    await _send_attachments(message, workspace, session, outcome.attachments)


# --- Debounce: серия сообщений получает один общий ответ -------------------
#
# Сообщения уже сохранены middleware'ом, поэтому отложенный ответ собирает
# их все из истории. Новое сообщение в том же чате сдвигает таймер.


@dataclass
class _Pending:
    task: asyncio.Task
    extras: list[dict] = field(default_factory=list)  # мультимодальные части


_pending: dict[int, _Pending] = {}


def _schedule_reply(
    message: Message, user_id: int, workspace_id: int, extras: list[dict] | None = None
) -> None:
    chat_id = message.chat.id
    previous = _pending.get(chat_id)
    combined = list(previous.extras) if previous else []
    if extras:
        combined.extend(extras)
    if previous and not previous.task.done():
        previous.task.cancel()

    task = asyncio.create_task(
        _delayed_reply(message, user_id, workspace_id, combined),
        name=f"debounce-{chat_id}",
    )
    _pending[chat_id] = _Pending(task=task, extras=combined)


async def _delayed_reply(
    message: Message, user_id: int, workspace_id: int, extras: list[dict]
) -> None:
    try:
        await asyncio.sleep(get_settings().reply_debounce_seconds)
    except asyncio.CancelledError:
        return  # пришло новое сообщение — ответит его таймер

    _pending.pop(message.chat.id, None)

    # Отложенный ответ живёт вне middleware — своя сессия и обработка ошибок
    try:
        async with session_factory() as session:
            user = await session.get(User, user_id)
            workspace = await session.get(Workspace, workspace_id)
            await _generate_and_send(
                message, user, workspace, session,
                extra_user_message=extras or None,
            )
            await session.commit()
    except Exception as exc:
        logger.exception("Отложенный ответ упал (chat=%s)", message.chat.id)
        try:
            await message.answer(
                "⚠️ Что-то сломалось: "
                f"<code>{html.escape(alerts.safe_error_text(exc, 100))}</code>. "
                "Попробуй ещё раз."
            )
        except Exception:
            pass


async def _maybe_proactive(
    message: Message, user: User, workspace: Workspace, session: AsyncSession
) -> None:
    """С шансом proactive_percent Геннадий сам вставляет реплику в разговор."""
    percent = (workspace.settings or {}).get("proactive_percent", 0)
    if not percent or random.random() * 100 >= percent:
        return
    # Не встреваем, пока бот и так участвует в разговоре: ждёт debounce-ответ
    # или недавно отвечал — иначе запоздавшая реплика выглядит как второй ответ
    if _pending.get(message.chat.id) is not None:
        return
    if await _redis.exists(f"botactive:{message.chat.id}"):
        return
    # Кулдаун: не чаще раза в proactive_cooldown секунд на чат
    settings = get_settings()
    if not await _redis.set(
        f"proactive:{message.chat.id}", "1", ex=settings.proactive_cooldown, nx=True
    ):
        return
    if await _check_budget(message, session, workspace):
        return

    outcome = await llm_chat.maybe_interject(
        session, workspace, user, message.bot, message.chat.id
    )
    if outcome is None:
        return
    # Пока встревание генерилось, кто-то мог обратиться к боту напрямую —
    # тогда молчим, чтобы не выглядеть «ответил два раза»
    if _pending.get(message.chat.id) is not None or await _redis.exists(
        f"botactive:{message.chat.id}"
    ):
        return
    await _mark_bot_active(message.chat.id)
    sent = await send_rendered(message.bot, message.chat.id, outcome.text.strip())
    saved = await messages.save_assistant(
        session, workspace, outcome.text.strip(), tg_message_id=sent.message_id
    )
    await llm_chat.log_usages(session, workspace, outcome.usages, message_id=saved.id, user_id=user.id)


async def _photo_extra(message: Message, file_id: str) -> list[dict]:
    """Скачивает фото и оформляет как мультимодальную часть для vision-модели."""
    file = await message.bot.download(file_id)
    encoded = base64.b64encode(file.read()).decode()
    return [
        {"type": "text", "text": "Изображение из сообщения:"},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
        },
    ]


@router.message(F.text & ~F.text.startswith("/"))
async def on_text(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
    bot_username: str,
) -> None:
    # В группах отвечаем только на упоминание или reply боту;
    # сообщение уже сохранено в WorkspaceMiddleware в любом случае.
    if workspace.type == WorkspaceType.group and not _addressed_to_bot(
        message, bot_username
    ):
        await _maybe_proactive(message, user, workspace, session)
        return

    # Ответ на фото + обращение к боту → подтягиваем то фото в vision-контекст
    extras = None
    reply = message.reply_to_message
    if reply and reply.photo:
        extras = await _photo_extra(message, reply.photo[-1].file_id)

    _schedule_reply(message, user.id, workspace.id, extras=extras)


@router.message(F.photo)
async def on_photo(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
    bot_username: str,
) -> None:
    # «[фото] подпись» уже в истории (middleware); отвечаем только адресату.
    # Без подписи в группе бот молчит, но фото уже в истории — можно ответить
    # позже, зареплаив на него с обращением к боту.
    if workspace.type == WorkspaceType.group and not _addressed_to_bot(
        message, bot_username
    ):
        return

    extras = await _photo_extra(message, message.photo[-1].file_id)
    _schedule_reply(message, user.id, workspace.id, extras=extras)


@router.message(F.document)
async def on_document(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
    bot_username: str,
) -> None:
    doc = message.document
    if workspace.type == WorkspaceType.group and not _addressed_to_bot(
        message, bot_username
    ):
        return  # в группе реагируем на документ только если обратились к боту
    if doc.file_size and doc.file_size > documents.MAX_FILE_BYTES:
        await message.answer("📄 Файл слишком большой (лимит 20 МБ).")
        return

    file = await message.bot.download(doc.file_id)
    text, error = documents.extract_text(file.read(), doc.file_name, doc.mime_type)
    if error:
        await message.answer(f"📄 {error}")
        return

    caption = f" Подпись: {message.caption}" if message.caption else ""
    await messages.save_user_text(
        session,
        workspace,
        user,
        f"[документ «{doc.file_name}»]{caption}\n{text}",
        tg_message_id=message.message_id,
    )
    # Документ уже в истории — общий debounce-пайплайн
    _schedule_reply(message, user.id, workspace.id)


@router.message(F.voice)
async def on_voice(
    message: Message,
    user: User,
    workspace: Workspace,
    session: AsyncSession,
    bot_username: str,
) -> None:
    # Голосовые в группах обрабатываем только reply'ем боту:
    # транскрипция каждого войса — лишние расходы
    if workspace.type == WorkspaceType.group and not _addressed_to_bot(
        message, bot_username
    ):
        return
    if await _check_budget(message, session, workspace):
        return

    await message.bot.send_chat_action(message.chat.id, "typing")

    file = await message.bot.download(message.voice.file_id)
    encoded = base64.b64encode(file.read()).decode()
    try:
        transcription = await client.chat(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": TRANSCRIBE_PROMPT},
                        {
                            "type": "input_audio",
                            "input_audio": {"data": encoded, "format": "ogg"},
                        },
                    ],
                }
            ],
            get_settings().audio_model,
        )
    except LlmError as exc:
        logger.error("Transcribe error (workspace=%s): %s", workspace.id, exc)
        await alerts.record_llm_failure(message.bot)
        await message.answer("🎙 Не расслышал — не смог распознать голосовое. Попробуй ещё раз.")
        return

    transcript = transcription.content.strip()
    saved = await messages.save_user_text(
        session,
        workspace,
        user,
        f"[голосовое] {transcript}",
        tg_message_id=message.message_id,
    )
    await llm_chat.log_usages(session, workspace, [transcription], message_id=saved.id, user_id=user.id)

    # Транскрипт уже в истории — дальше общий debounce-пайплайн
    _schedule_reply(message, user.id, workspace.id)
