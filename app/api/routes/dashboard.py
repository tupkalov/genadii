from datetime import datetime, timedelta, timezone
from html import escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from sqlalchemy import case, func, select

from app.db.models import (
    AuditLog,
    LlmUsage,
    MemoryEntry,
    Message,
    ScheduledTask,
    Workspace,
)
from app.db.session import session_factory

router = APIRouter()

PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Умный Геннадий — дашборд</title>
<style>
 body{{font-family:system-ui,sans-serif;margin:0;background:#0f1115;color:#e6e6e6}}
 header{{padding:16px 24px;background:#171a21;font-size:20px;font-weight:600}}
 main{{padding:24px;max-width:1100px;margin:0 auto}}
 .cards{{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:24px}}
 .card{{background:#171a21;border-radius:12px;padding:16px 20px;flex:1;min-width:160px}}
 .card .n{{font-size:28px;font-weight:700}}
 .card .l{{color:#9aa0aa;font-size:13px;margin-top:4px}}
 h2{{font-size:15px;color:#9aa0aa;margin:24px 0 8px;text-transform:uppercase;letter-spacing:.5px}}
 table{{width:100%;border-collapse:collapse;background:#171a21;border-radius:12px;overflow:hidden}}
 th,td{{text-align:left;padding:10px 14px;border-bottom:1px solid #23262e;font-size:14px}}
 th{{color:#9aa0aa;font-weight:500}}
 tr:last-child td{{border-bottom:none}}
 .muted{{color:#9aa0aa}}
</style></head><body>
<header>🧠 Умный Геннадий — дашборд</header>
<main>
 <div class="cards">
  <div class="card"><div class="n">{workspaces}</div><div class="l">чатов</div></div>
  <div class="card"><div class="n">{messages}</div><div class="l">сообщений</div></div>
  <div class="card"><div class="n">{facts}</div><div class="l">фактов в памяти</div></div>
  <div class="card"><div class="n">{tasks}</div><div class="l">активных задач</div></div>
  <div class="card"><div class="n">${cost30:.2f}</div><div class="l">расход за 30 дней</div></div>
 </div>
 <h2>Расходы по чатам (30 дней)</h2>
 <table><tr><th>Чат</th><th>Тип</th><th>Вызовов</th><th>Токены</th><th>Стоимость</th></tr>{usage_rows}</table>
 <h2>Расход по моделям (30 дней)</h2>
 <table><tr><th>Модель</th><th>Вызовов</th><th>Вход</th><th>Выход</th><th>Стоимость</th></tr>{model_rows}</table>
 <h2>Инициатива — хартбит (30 дней)</h2>
 <p class="muted">Размышлений: <b>{hb_total}</b> — заговорил первым <b>{hb_spoke}</b>, смолчал {hb_silent}.</p>
 <table><tr><th>Время</th><th>Чат</th><th>Итог</th><th>Инициатива</th></tr>{hb_rows}</table>
 <h2>Последние действия (audit)</h2>
 <table><tr><th>Время</th><th>Действие</th><th>Чат</th><th>Детали</th></tr>{audit_rows}</table>
</main></body></html>"""


@router.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    since = datetime.now(timezone.utc) - timedelta(days=30)

    async with session_factory() as session:
        n_ws = await session.scalar(select(func.count(Workspace.id)))
        n_msg = await session.scalar(select(func.count(Message.id)))
        n_facts = await session.scalar(
            select(func.count(MemoryEntry.id)).where(MemoryEntry.archived_at.is_(None))
        )
        n_tasks = await session.scalar(
            select(func.count(ScheduledTask.id)).where(ScheduledTask.status == "pending")
        )
        cost30 = await session.scalar(
            select(func.coalesce(func.sum(LlmUsage.cost_usd), 0)).where(
                LlmUsage.created_at >= since
            )
        )

        usage = (
            await session.execute(
                select(
                    Workspace.title,
                    Workspace.type,
                    func.count(LlmUsage.id),
                    func.coalesce(func.sum(LlmUsage.prompt_tokens + LlmUsage.completion_tokens), 0),
                    func.coalesce(func.sum(LlmUsage.cost_usd), 0),
                )
                .join(LlmUsage, LlmUsage.workspace_id == Workspace.id)
                .where(LlmUsage.created_at >= since)
                .group_by(Workspace.id)
                .order_by(func.sum(LlmUsage.cost_usd).desc())
            )
        ).all()

        by_model = (
            await session.execute(
                select(
                    LlmUsage.model,
                    func.count(LlmUsage.id),
                    func.coalesce(func.sum(LlmUsage.prompt_tokens), 0),
                    func.coalesce(func.sum(LlmUsage.completion_tokens), 0),
                    func.coalesce(func.sum(LlmUsage.cost_usd), 0),
                )
                .where(LlmUsage.created_at >= since)
                .group_by(LlmUsage.model)
                .order_by(func.sum(LlmUsage.cost_usd).desc())
            )
        ).all()

        # Инициатива: сводка размышлений хартбита и последние события
        hb_total, hb_spoke = (
            await session.execute(
                select(
                    func.count(AuditLog.id),
                    func.coalesce(
                        func.sum(
                            case(
                                (AuditLog.payload["spoke"].astext == "true", 1),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                ).where(
                    AuditLog.action == "heartbeat", AuditLog.created_at >= since
                )
            )
        ).one()
        hb_events = (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.action == "heartbeat")
                .order_by(AuditLog.id.desc())
                .limit(15)
            )
        ).scalars().all()

        audit = (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.action != "heartbeat")  # хартбит — в своей секции
                .order_by(AuditLog.id.desc())
                .limit(20)
            )
        ).scalars().all()

    usage_rows = "".join(
        f"<tr><td>{escape(title or '—')}</td><td class='muted'>{t.value}</td>"
        f"<td>{calls}</td><td>{tokens}</td><td>${float(cost):.4f}</td></tr>"
        for title, t, calls, tokens, cost in usage
    ) or "<tr><td colspan=5 class='muted'>пока пусто</td></tr>"

    model_rows = "".join(
        f"<tr><td>{escape(model or '—')}</td><td>{calls}</td>"
        f"<td class='muted'>{pin:,}</td><td class='muted'>{pout:,}</td>"
        f"<td>${float(cost):.4f}</td></tr>"
        for model, calls, pin, pout, cost in by_model
    ) or "<tr><td colspan=5 class='muted'>пока пусто</td></tr>"

    audit_rows = "".join(
        f"<tr><td class='muted'>{a.created_at:%m-%d %H:%M}</td><td>{escape(a.action)}</td>"
        f"<td class='muted'>{a.workspace_id or '—'}</td>"
        f"<td class='muted'>{escape(str(a.payload)[:80])}</td></tr>"
        for a in audit
    ) or "<tr><td colspan=4 class='muted'>пока пусто</td></tr>"

    def _hb_row(a: AuditLog) -> str:
        payload = a.payload or {}
        spoke = payload.get("spoke")
        outcome = "🗣 написал" if spoke else "🤐 смолчал"
        pct = payload.get("initiative")
        pct_txt = f"{pct}%" if pct is not None else "—"
        return (
            f"<tr><td class='muted'>{a.created_at:%m-%d %H:%M}</td>"
            f"<td class='muted'>{a.workspace_id or '—'}</td>"
            f"<td>{outcome}</td><td class='muted'>{pct_txt}</td></tr>"
        )

    hb_rows = "".join(_hb_row(a) for a in hb_events) or (
        "<tr><td colspan=4 class='muted'>пока не размышлял</td></tr>"
    )

    return PAGE.format(
        workspaces=n_ws, messages=n_msg, facts=n_facts, tasks=n_tasks,
        cost30=float(cost30), usage_rows=usage_rows, model_rows=model_rows,
        audit_rows=audit_rows,
        hb_total=hb_total, hb_spoke=hb_spoke, hb_silent=hb_total - hb_spoke,
        hb_rows=hb_rows,
    )
