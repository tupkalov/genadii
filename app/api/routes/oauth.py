"""OAuth-callback для MCP-серверов: сюда провайдер возвращает пользователя
после «Разрешить». Резолвит ожидающий флоу по state (бот и FastAPI — один
процесс и event loop)."""

import html

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.services import mcp_auth

router = APIRouter(prefix="/oauth")

PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>Умный Геннадий</title>
<style>body{{font-family:system-ui,sans-serif;background:#0f1115;color:#e6e6e6;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
div{{text-align:center}}</style></head>
<body><div><h2>{title}</h2><p>{text}</p></div></body></html>"""


@router.get("/callback")
async def oauth_callback(
    state: str = "", code: str = "", error: str = "", error_description: str = ""
) -> HTMLResponse:
    if error:
        # Пользователь отказал или провайдер вернул ошибку — флоу истечёт по таймауту
        return HTMLResponse(
            PAGE.format(
                title="Авторизация не удалась 😔",
                text=html.escape(error_description or error),
            ),
            status_code=400,
        )
    if not state or not code or not mcp_auth.resolve_callback(state, code):
        return HTMLResponse(
            PAGE.format(
                title="Ссылка устарела 🤷",
                text="Начни подключение заново командой /mcp auth в Telegram.",
            ),
            status_code=400,
        )
    return HTMLResponse(
        PAGE.format(
            title="Готово ✅",
            text="Доступ выдан. Возвращайся в Telegram — Геннадий уже подключается.",
        )
    )
