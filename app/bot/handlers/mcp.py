import html
from urllib.parse import urlparse

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import delete, select

from app.db.models import McpServer, User, UserRole, Workspace
from app.services import audit, mcp, messages

router = Router(name="mcp")

USAGE = (
    "MCP-серверы этого чата. Команды:\n"
    "<code>/mcp add имя url [токен]</code> — подключить\n"
    "<code>/mcp list</code> — список\n"
    "<code>/mcp on|off имя</code> — включить/выключить\n"
    "<code>/mcp refresh</code> — перечитать инструменты\n"
    "<code>/mcp remove имя</code> — удалить"
)


async def _get_server(session, workspace: Workspace, name: str) -> McpServer | None:
    return await session.scalar(
        select(McpServer).where(
            McpServer.workspace_id == workspace.id, McpServer.name == name
        )
    )


async def _cmd_add(session, workspace, user, args: list[str]) -> str:
    if len(args) < 2:
        return "Формат: <code>/mcp add имя url [токен]</code>"
    name, url = args[0].lower(), args[1]
    token = args[2] if len(args) > 2 else None

    if not mcp.NAME_RE.match(name):
        return "Имя: латиница/цифры/дефис/подчёркивание, до 32 символов."
    if urlparse(url).scheme not in ("http", "https"):
        return "URL должен начинаться с http:// или https://"
    if await _get_server(session, workspace, name) is not None:
        return f"Сервер «{html.escape(name)}» уже есть — сначала /mcp remove."

    try:
        tools = await mcp.test_connect(url, token)
    except Exception as exc:  # noqa: BLE001 — показываем причину админу
        return (
            f"Не смог подключиться к {html.escape(url)}:\n"
            f"<code>{html.escape(str(exc)[:300])}</code>"
        )

    server = McpServer(
        workspace_id=workspace.id,
        name=name,
        url=url,
        auth_token=token,
        tools_cache=tools,
        created_by_id=user.id,
    )
    session.add(server)
    await session.flush()
    await mcp.refresh_server(session, server)
    await audit.log(
        session,
        action="mcp_server_added",
        payload={"name": name, "url": url, "tools": len(tools)},
        workspace_id=workspace.id,
        user_id=user.id,
    )
    names = ", ".join(html.escape(t["name"]) for t in tools[:10])
    more = f" и ещё {len(tools) - 10}" if len(tools) > 10 else ""
    return (
        f"Подключил «{html.escape(name)}»: {len(tools)} инструментов.\n"
        f"{names}{more}\n\nОни уже доступны мне в этом чате."
    )


async def _cmd_list(session, workspace) -> str:
    servers = (
        await session.scalars(
            select(McpServer)
            .where(McpServer.workspace_id == workspace.id)
            .order_by(McpServer.name)
        )
    ).all()
    if not servers:
        return "MCP-серверы не подключены.\n" + USAGE
    lines = ["<b>MCP-серверы этого чата:</b>"]
    for s in servers:
        count = len(s.tools_cache or [])
        state = "🟢" if s.enabled else "⚪"
        cached = f", обновлено {s.cached_at:%Y-%m-%d %H:%M}" if s.cached_at else ""
        lines.append(
            f"{state} <b>{html.escape(s.name)}</b> — {count} инстр.{cached}\n"
            f"   <code>{html.escape(s.url)}</code>"
        )
    return "\n".join(lines)


async def _cmd_toggle(session, workspace, user, name: str, enabled: bool) -> str:
    server = await _get_server(session, workspace, name)
    if server is None:
        return f"Сервера «{html.escape(name)}» в этом чате нет."
    server.enabled = enabled
    await mcp.invalidate(server.id)
    await audit.log(
        session,
        action="mcp_server_toggled",
        payload={"name": name, "enabled": enabled},
        workspace_id=workspace.id,
        user_id=user.id,
    )
    return f"«{html.escape(name)}» {'включён 🟢' if enabled else 'выключен ⚪'}"


async def _cmd_remove(session, workspace, user, name: str) -> str:
    server = await _get_server(session, workspace, name)
    if server is None:
        return f"Сервера «{html.escape(name)}» в этом чате нет."
    await mcp.invalidate(server.id)
    await session.execute(delete(McpServer).where(McpServer.id == server.id))
    await audit.log(
        session,
        action="mcp_server_removed",
        payload={"name": name},
        workspace_id=workspace.id,
        user_id=user.id,
    )
    return f"Удалил «{html.escape(name)}»."


async def _cmd_refresh(session, workspace, user) -> str:
    servers = (
        await session.scalars(
            select(McpServer).where(
                McpServer.workspace_id == workspace.id, McpServer.enabled.is_(True)
            )
        )
    ).all()
    if not servers:
        return "Обновлять нечего — включённых серверов нет."
    lines = []
    for server in servers:
        try:
            count = await mcp.refresh_server(session, server)
            lines.append(f"🟢 {html.escape(server.name)}: {count} инстр.")
        except Exception as exc:  # noqa: BLE001
            lines.append(
                f"🔴 {html.escape(server.name)}: <code>{html.escape(str(exc)[:150])}</code>"
            )
    await audit.log(
        session,
        action="mcp_servers_refreshed",
        payload={"count": len(servers)},
        workspace_id=workspace.id,
        user_id=user.id,
    )
    return "Обновил:\n" + "\n".join(lines)


@router.message(Command("mcp"))
async def cmd_mcp(
    message: Message,
    user: User,
    workspace: Workspace,
    session,
    command: CommandObject,
) -> None:
    if user.role != UserRole.admin:
        text = "Управлять MCP-серверами может только админ. 🙅"
    else:
        args = (command.args or "").split()
        sub = args[0].lower() if args else "list"
        rest = args[1:]
        if sub == "add":
            text = await _cmd_add(session, workspace, user, rest)
        elif sub == "list":
            text = await _cmd_list(session, workspace)
        elif sub in ("on", "off") and rest:
            text = await _cmd_toggle(session, workspace, user, rest[0].lower(), sub == "on")
        elif sub == "remove" and rest:
            text = await _cmd_remove(session, workspace, user, rest[0].lower())
        elif sub == "refresh":
            text = await _cmd_refresh(session, workspace, user)
        else:
            text = USAGE

    sent = await message.answer(text)
    await messages.save_assistant(session, workspace, text, tg_message_id=sent.message_id)
