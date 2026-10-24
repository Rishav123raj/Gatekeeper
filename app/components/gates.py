"""The Go / No-Go panel (plan 9.3), the decision log form, and the ticket to paste into Claude."""

from __future__ import annotations

import streamlit as st
from sqlalchemy.engine import Engine

from gatekeeper import store
from gatekeeper.db import session
from gatekeeper.readiness import ReadinessResult
from gatekeeper.skills.models import Ticket

ICONS = {"PASS": "✅", "WARN": "⚠️", "FAIL": "⛔"}
BADGE = {"GO": ("green", "GO"), "CAUTION": ("orange", "CAUTION"), "NO_TRADE": ("red", "NO TRADE")}
RULE = (
    "Any hard check failing → NO TRADE. Otherwise any warning (or a soft check failing) → CAUTION. "
    "Otherwise → GO. GO means your rules allow it and the honest odds aren't against it; "
    "it is not a recommendation."
)


def readiness_panel(result: ReadinessResult, title: str) -> None:
    color, label = BADGE[result.overall]
    st.markdown(f"#### {title}: :{color}-badge[{label}]")
    st.caption(RULE)
    for g in result.gates:
        st.markdown(
            f"{ICONS[g.status]} **{g.name}** · {g.reason}", help=f"{g.level} check · source: {g.source}"
        )


def ticket_text(t: Ticket) -> str:
    return (
        "/trader-broker\n"
        f"Order {t.index} in trader/orders.json passed trader-risk ({t.fingerprint}).\n"
        f"Ticket: {t.plain}\n"
        "Show me the ticket and ask me for an explicit yes before calling place_stock_order."
    )


def claude_ticket(tickets: list[Ticket] | None) -> None:
    """Copy-paste text for Claude chat: /trader-broker shows it again and asks for your yes."""
    ready = [t for t in tickets or [] if t.ready]
    if not ready:
        st.caption("No READY ticket: Size & check has to PASS first.")
        return
    st.markdown("**Ticket for Claude** (copy with the icon at the top right)")
    st.code(ticket_text(ready[0]), language=None)
    st.caption(
        "Gatekeeper never places orders. In Claude chat, /trader-broker shows this ticket, asks for your "
        "typed yes, and Claude's own Allow once / Deny card asks again. Paper account by default."
    )


def decision_form(
    engine: Engine, mode: str, result: ReadinessResult, readiness_id: int | None, key: str
) -> None:
    """Log the trade as taken or skipped, with a note and whether you followed your rules."""
    with st.form(key, clear_on_submit=True):
        st.markdown("**Log your decision** (the journal learns from both)")
        note = st.text_input("Note", placeholder="why you took it, or why you skipped it")
        followed = st.checkbox("I followed my rules", value=True)
        c1, c2 = st.columns(2)
        taken = c1.form_submit_button("Log: Taken")
        skipped = c2.form_submit_button("Log: Skipped")
    if taken or skipped:
        action = "TAKEN" if taken else "SKIPPED"
        with session(engine) as s:
            store.save_decision(
                s,
                mode,
                action,
                plan_id=result.plan_id,
                symbol=result.symbol,
                note=note,
                followed_rules=followed,
                readiness_id=readiness_id,
                overall=result.overall,
            )
        st.success(f"Logged {action} for {result.symbol} (Go / No-Go was {BADGE[result.overall][1]}).")
