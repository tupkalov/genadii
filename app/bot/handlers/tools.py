from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserRole, Workspace
from app.services import audit, messages
from app.tools import TOOLS, permissions

router = Router(name="tools")

HEADER = (
    "<b>Инструменты этого чата</b>\n"
    "Все включены по умолчанию; админ переключает кнопками ниже."
)


def _keyboard(enabled_names: set[str]) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=f"{'🟢' if name in enabled_names else '⚪'} {name}",
            callback_data=f"tooltoggle:{name}",
        )
        for name in TOOLS
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _enabled_names(session: AsyncSession, workspace: Workspace) -> set[str]:
    return {t.name for t in await permissions.enabled_tools(session, workspace)}


@router.message(Command("tools"))
async def cmd_tools(
    message: Message,
    user,
    workspace: Workspace,
    session: AsyncSession,
    command: CommandObject,
) -> None:
    # Текстовый фолбэк: /tools enable|disable имя (устойчив к пробелам вместо _)
    args = (command.args or "").lower().split()
    if args:
        if user.role != UserRole.admin:
            text = "Управлять инструментами может только админ. 🙅"
        elif len(args) >= 2 and args[0] in ("enable", "disable"):
            tool_name = "_".join(args[1:])
            if tool_name not in TOOLS:
                text = f"Не знаю инструмент «{tool_name}». Есть: {', '.join(TOOLS)}"
            else:
                enabled = args[0] == "enable"
                await permissions.set_permission(
                    session, workspace, tool_name, enabled, granted_by_id=user.id
                )
                await audit.log(
                    session,
                    action="tool_permission_set",
                    payload={"tool": tool_name, "enabled": enabled},
                    workspace_id=workspace.id,
                    user_id=user.id,
                )
                text = f"<code>{tool_name}</code> {'включён 🟢' if enabled else 'выключен ⚪'}"
        else:
            text = "Формат: <code>/tools enable|disable имя</code> — или без аргументов, кнопками."
        sent = await message.answer(text)
        await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)
        return

    enabled = await _enabled_names(session, workspace)
    sent = await message.answer(HEADER, reply_markup=_keyboard(enabled))
    await messages.save_assistant(session, workspace, HEADER, tg_message_id=sent.message_id)


@router.callback_query(F.data.startswith("tooltoggle:"))
async def cb_tool_toggle(
    callback: CallbackQuery,
    user,
    workspace: Workspace,
    session: AsyncSession,
) -> None:
    # Whitelist (включая is_active) и workspace — из общей цепочки middleware
    tool_name = callback.data.split(":", 1)[1]
    if tool_name not in TOOLS or callback.message is None:
        await callback.answer("Такого инструмента больше нет", show_alert=False)
        return
    if user.role != UserRole.admin:
        await callback.answer("Только админ 🙅", show_alert=False)
        return

    enabled_now = tool_name in await _enabled_names(session, workspace)
    await permissions.set_permission(
        session, workspace, tool_name, not enabled_now, granted_by_id=user.id
    )
    await audit.log(
        session,
        action="tool_permission_set",
        payload={"tool": tool_name, "enabled": not enabled_now},
        workspace_id=workspace.id,
        user_id=user.id,
    )
    enabled = await _enabled_names(session, workspace)

    await callback.message.edit_reply_markup(reply_markup=_keyboard(enabled))
    await callback.answer(
        f"{tool_name}: {'выключен ⚪' if enabled_now else 'включён 🟢'}"
    )
