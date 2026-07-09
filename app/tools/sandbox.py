import httpx

from app.config import get_settings
from app.tools.registry import Tool, ToolContext, register

RESULT_LIMIT = 3500
CODE_LIMIT = 100_000  # синхронно с sandbox/runner.py

# Приклеивается к упавшему запуску: инструкция в последнем tool-сообщении
# держит модель куда крепче, чем правило в далёком системном промпте
FAILURE_NUDGE = (
    "\n\n[Код упал. Причина — в ошибке выше: прочитай её и почини прямо сейчас, "
    "затем запусти снова (та же ошибка повторно = твоя правка не попала в причину, "
    "смени подход). Отвечать пользователю выдуманными данными вместо результата "
    "ЗАПРЕЩЕНО. Не смог починить — покажи пользователю эту ошибку как есть.]"
)

# Эти исключения — всегда баг сгенерированного кода, внешний сервис ни при чём
_CODE_BUG_MARKERS = (
    "NameError",
    "SyntaxError",
    "TypeError",
    "KeyError",
    "AttributeError",
    "IndexError",
    "IndentationError",
    "UnboundLocalError",
)


def failure_nudge(stderr: str) -> str:
    nudge = FAILURE_NUDGE
    if any(marker in stderr for marker in _CODE_BUG_MARKERS):
        nudge += (
            "\n[Судя по типу исключения, это баг в ТВОЁМ коде, а не проблема "
            "внешнего API или сервиса. НЕ говори пользователю, что «сервис "
            "нестабилен» или «API глючит» — почини свой код.]"
        )
    return nudge


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
    result = result[:RESULT_LIMIT] + ("…" if len(result) > RESULT_LIMIT else "")
    if data["exit_code"] != 0:
        result += failure_nudge(data.get("stderr") or "")
    return result


register(
    Tool(
        name="run_python",
        description=(
            "Выполнить Python-код в изолированной песочнице (нет доступа к серверу "
            "и данным бота, но есть интернет — можно ходить в сторонние API, "
            "например requests к внешним сервисам). Результат печатай в stdout. "
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
