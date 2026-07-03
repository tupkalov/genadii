from app.services import memory
from app.tools.registry import Tool, ToolContext, register


FACT_LIMIT = 500


async def _remember(ctx: ToolContext, fact: str) -> str:
    fact = fact.strip()
    if len(fact) > FACT_LIMIT:
        return f"Факт слишком длинный (>{FACT_LIMIT} символов) — сформулируй короче."
    entry = await memory.add_fact(ctx.session, ctx.workspace, ctx.user, fact)
    return f"Запомнил (факт #{entry.id}): {entry.content}"


async def _recall(ctx: ToolContext, query: str) -> str:
    entries = await memory.search(ctx.session, ctx.workspace, query)
    if not entries:
        return "Ничего не нашёл в памяти по этому запросу."
    return "Нашёл в памяти:\n" + "\n".join(
        f"- (#{e.id}) {e.content}" for e in entries
    )


register(
    Tool(
        name="remember",
        description=(
            "Сохранить важный факт в долгую память этого чата. Используй, когда "
            "пользователь просит что-то запомнить или сообщает важное о себе/планах."
        ),
        parameters={
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": "Краткая самодостаточная формулировка факта",
                }
            },
            "required": ["fact"],
        },
        handler=_remember,
        default_enabled=True,
    )
)

register(
    Tool(
        name="recall",
        description=(
            "Поискать в долгой памяти чата факты по запросу. Используй, когда "
            "нужна информация, которой нет в последних сообщениях."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Поисковый запрос"}
            },
            "required": ["query"],
        },
        handler=_recall,
        default_enabled=True,
    )
)
