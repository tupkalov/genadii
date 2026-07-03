import httpx

from app.config import get_settings
from app.tools.registry import Tool, ToolContext, register

RESULT_LIMIT = 3500
CODE_LIMIT = 100_000  # синхронно с sandbox/runner.py


async def _run_python(ctx: ToolContext, code: str) -> str:
    if len(code) > CODE_LIMIT:
        return f"Ошибка: код длиннее {CODE_LIMIT} символов — сократи его."

    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=70) as client:
            response = await client.post(
                f"{settings.sandbox_url}/run", json={"code": code, "timeout": 30}
            )
    except httpx.HTTPError as exc:
        return f"Ошибка: sandbox недоступен ({exc})"

    if response.status_code != 200:
        return f"Ошибка sandbox: HTTP {response.status_code}"

    data = response.json()
    parts = [f"exit_code: {data['exit_code']}"]
    if data.get("stdout"):
        parts.append(f"stdout:\n{data['stdout']}")
    if data.get("stderr"):
        parts.append(f"stderr:\n{data['stderr']}")
    result = "\n".join(parts)
    return result[:RESULT_LIMIT] + ("…" if len(result) > RESULT_LIMIT else "")


register(
    Tool(
        name="run_python",
        description=(
            "Выполнить Python-код в изолированной песочнице (нет доступа к серверу, "
            "данным бота и интернету). Для данных из сети сначала возьми их через "
            "fetch_url/web_search и передай в код. Результат печатай в stdout. "
            "Доступна стандартная библиотека. Лимиты: 30 сек, 512 МБ. Состояние "
            "между запусками не сохраняется."
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python-код целиком"}
            },
            "required": ["code"],
        },
        handler=_run_python,
        hourly_limit=40,
        default_enabled=True,  # песочница изолирована; выключить: /tools
    )
)
