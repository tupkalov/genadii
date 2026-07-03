from app.config import get_settings
from app.db.models import LlmUsage
from app.llm import client
from app.tools.registry import Tool, ToolContext, register

MAX_IMAGES_PER_TURN = 2


async def _generate_image(ctx: ToolContext, prompt: str) -> str:
    if len(ctx.attachments) >= MAX_IMAGES_PER_TURN:
        return f"Ошибка: не больше {MAX_IMAGES_PER_TURN} картинок за один ответ."

    settings = get_settings()
    try:
        result = await client.generate_image(prompt, settings.image_model)
    except client.LlmError as exc:
        return f"Ошибка генерации: {exc}"

    if not result.images:
        return "Модель не вернула картинку — попробуй переформулировать запрос."

    ctx.attachments.append(result.images[0])
    ctx.session.add(
        LlmUsage(
            workspace_id=ctx.workspace.id,
            model=result.model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            cost_usd=result.cost_usd,
            latency_ms=result.latency_ms,
        )
    )
    await ctx.session.flush()
    return (
        "Готово: картинка сгенерирована и будет приложена к твоему ответу. "
        "Кратко подпиши её, не пересказывая содержимое."
    )


register(
    Tool(
        name="generate_image",
        description=(
            "Сгенерировать изображение по текстовому описанию и отправить в чат. "
            "Используй, когда просят нарисовать/сгенерировать картинку. "
            "Промпт пиши подробно, на английском качество обычно выше."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Детальное описание изображения",
                }
            },
            "required": ["prompt"],
        },
        handler=_generate_image,
        default_enabled=True,  # ~$0.04/шт — расходы ограничивает /budget
    )
)
