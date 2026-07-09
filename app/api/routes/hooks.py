"""Входящие вебхуки: POST /hooks/{token} → уведомление в чат или агентский ход.

Аутентификация — сам токен (случайный, уникальный). Незнакомый и выключенный
токен неразличимы снаружи (оба 404). Агентский режим не выполняет LLM-ход в
запросе: создаёт ScheduledTask kind=agent_task, воркер подхватит за ≤20с — с
инструментами, бюджет-чеком и алертами существующего пайплайна.
"""

import html
import json
import logging
from datetime import datetime, timezone

from aiogram.exceptions import TelegramBadRequest
from fastapi import APIRouter, Request, Response
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import get_settings
from app.db.models import ScheduledTask, Webhook, Workspace
from app.db.session import session_factory
from app.services import audit, messages

logger = logging.getLogger("gennady.hooks")

router = APIRouter(prefix="/hooks")

_redis = Redis.from_url(get_settings().redis_url)

BODY_LIMIT = 65536
RATE_LIMIT_PER_HOUR = 60
NOTIFY_JSON_LIMIT = 1000
AGENT_PAYLOAD_LIMIT = 4000


async def _rate_limited(hook_id: int) -> bool:
    key = f"hooklimit:{hook_id}"
    count = await _redis.incr(key)
    if count == 1:
        await _redis.expire(key, 3600)
    return count > RATE_LIMIT_PER_HOUR


def _pretty(payload) -> str:
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, ensure_ascii=False, indent=1)


@router.post("/{token}")
async def receive_hook(token: str, request: Request) -> Response:
    body = await request.body()
    if len(body) > BODY_LIMIT:
        return Response(status_code=413)

    async with session_factory() as session:
        hook = await session.scalar(select(Webhook).where(Webhook.token == token))
        if hook is None or not hook.enabled:
            return Response(status_code=404)  # не палим существование хука
        if await _rate_limited(hook.id):
            return Response(status_code=429)

        workspace = await session.get(Workspace, hook.workspace_id)
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = body.decode("utf-8", errors="replace")

        if hook.mode == "agent":
            event = _pretty(payload)[:AGENT_PAYLOAD_LIMIT]
            task_payload: dict = {"user_name": f"вебхук «{hook.name}»"}
            if hook.skill_id:
                # Обработчик — скилл: инструкция и allowlist подставятся воркером
                task_payload |= {
                    "skill_id": hook.skill_id,
                    "text": f"вебхук «{hook.name}» → скилл",
                    "event": event,
                }
            else:
                task_payload["text"] = (
                    f"{hook.instruction or 'Обработай событие вебхука и напиши результат.'}"
                    f"\n\nДанные вебхука «{hook.name}»:\n{event}"
                )
            session.add(
                ScheduledTask(
                    workspace_id=hook.workspace_id,
                    user_id=hook.created_by_id,
                    kind="agent_task",
                    payload=task_payload,
                    run_at=datetime.now(timezone.utc),
                    status="pending",
                )
            )
        else:  # notify
            bot = getattr(request.app.state, "bot", None)
            if bot is None:
                return Response(status_code=503)
            note = (
                f"🪝 <b>{html.escape(hook.name)}</b>\n"
                f"<pre>{html.escape(_pretty(payload)[:NOTIFY_JSON_LIMIT])}</pre>"
            )
            try:
                sent = await bot.send_message(
                    workspace.tg_chat_id, note, parse_mode="HTML"
                )
            except TelegramBadRequest:
                sent = await bot.send_message(
                    workspace.tg_chat_id,
                    f"🪝 {hook.name}\n{_pretty(payload)[:NOTIFY_JSON_LIMIT]}",
                    parse_mode=None,
                )
            await messages.save_assistant(
                session,
                workspace,
                f"[вебхук «{hook.name}»]\n{_pretty(payload)[:NOTIFY_JSON_LIMIT]}",
                tg_message_id=sent.message_id,
            )

        hook.last_fired_at = datetime.now(timezone.utc)
        hook.fire_count = (hook.fire_count or 0) + 1
        await audit.log(
            session,
            action="webhook_fired",
            payload={"name": hook.name, "mode": hook.mode},
            workspace_id=hook.workspace_id,
        )
        await session.commit()

    return Response(
        content='{"ok": true}', media_type="application/json", status_code=200
    )
