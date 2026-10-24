"""Positions & Alerts: what's open, how far from the stop and target in R, the flat-by countdown,
the closing ticket, fills recorded by hand, and the alert rules. Nothing here places an order."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st
from sqlmodel import col, select

from app.components.gates import claude_ticket
from app.components.page import Page, footer, setup_page
from app.components.tables import dual_time, price
from gatekeeper import store
from gatekeeper.clock import IST, NY, load_session_times, market_day
from gatekeeper.db import session
from gatekeeper.skills import alerts, broker, risk
from gatekeeper.skills._base import read_json
from gatekeeper.skills.models import ExitPlan
from gatekeeper.tables import AlertFired

page = setup_page("Positions & Alerts", "🔔")
st.title("Positions & Alerts")
st.caption(
    "Open positions in R, the flat-by countdown, the closing ticket, fills you record by hand, and your "
    "alert rules. Gatekeeper never places, cancels or changes an order."
)

KINDS = {
    "stop": "price at or below (a stop)",
    "target": "price at or above (a target)",
    "below": "price below",
    "above": "price above",
    "pct": "% move from yesterday's close",
    "at": "a time (HH:MM NY)",
    "opening_bell": "the opening bell",
}


def flat_by_countdown(p: Page) -> datetime:
    times = load_session_times(p.trader_dir)
    day = market_day(p.now.date())
    flat = datetime.combine(p.now.date(), times.flat_by, NY)
    if day is not None and day.closes and day.closes < "16:00":  # an early close moves flat-by up too
        flat -= datetime.combine(date.min, datetime.strptime("16:00", "%H:%M").time()) - datetime.combine(
            date.min, datetime.strptime(day.closes, "%H:%M").time()
        )
    left = flat - p.now
    when = f"{flat:%H:%M} NY · {flat.astimezone(IST):%H:%M} IST"
    if day is not None and not day.trading_day:
        st.info(f"No session today ({day.reason}). Flat by is {when} on trading days.")
    elif left <= timedelta(0):
        st.warning(f"Past flat-by ({when}): close anything still open.")
    else:
        mins = int(left.total_seconds() // 60)
        text = f"Flat by {when}: **{mins // 60} h {mins % 60:02d} min** left"
        (st.error if left < timedelta(minutes=10) else st.info)(text)
    return flat


def plan_for(p: Page, symbol: str) -> ExitPlan | None:
    with session(p.engine) as s:
        row = store.latest_plan(s, p.mode, symbol, p.today)
    if row is not None:
        return ExitPlan.model_validate(row.payload)
    doc = read_json(p.trader_dir / "plan.json")
    return ExitPlan.model_validate(doc) if doc and doc.get("symbol") == symbol else None


def positions(p: Page) -> list[str]:
    st.subheader("Open positions")
    pf = broker.portfolio(p.runner("positions"))
    held = [x for x in (pf.positions if pf else []) if x.shares]
    if pf is not None:
        st.caption(
            f"Cash {price(pf.cash)} · from trader/portfolio.json (fills recorded below or by /trader-broker)"
        )
    if not held:
        st.caption("No open position.")
        return []
    src = p.yahoo()
    rows = []
    for x in held:
        chart = src.chart(x.ticker)
        last = round(chart.price, 2) if chart and chart.price is not None else None
        plan = plan_for(p, x.ticker)
        risk_ps = plan.risk_per_share if plan else None
        row = {"Ticker": x.ticker, "Shares": x.shares, "Avg cost": x.avg_cost, "Last": last}
        if plan and last is not None and risk_ps:
            row.update(
                {
                    "Stop": plan.stop,
                    "Target": plan.target,
                    "P&L (R)": round((last - (x.avg_cost or plan.entry)) / risk_ps, 2),
                    "To stop (R)": round((last - plan.stop) / risk_ps, 2),
                    "To target (R)": round((plan.target - last) / risk_ps, 2),
                }
            )
        rows.append(row)
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        column_config={
            "Avg cost": st.column_config.NumberColumn(format="$%.2f"),
            "Last": st.column_config.NumberColumn(format="$%.2f"),
            "Stop": st.column_config.NumberColumn(format="$%.2f"),
            "Target": st.column_config.NumberColumn(format="$%.2f"),
        },
    )
    st.caption(
        "In R: 1R is the plan's risk a share. Prices are free and delayed; the broker's price is the one "
        "that fills, and a stop can fill worse than its price in a fast market."
    )
    return [x.ticker for x in held]


def flatten_helper(p: Page, held: list[str]) -> None:
    st.subheader("Close a position (the ticket)")
    if not held:
        st.caption("Nothing to close.")
        return
    pf = broker.portfolio(p.runner("positions"))
    c1, c2 = st.columns([1, 3])
    sym = c1.selectbox("Position", held, key="flat_sym")
    shares = next((x.shares for x in pf.positions if x.ticker == sym), None) if pf else None
    c2.caption(
        "Writes a market order that closes the whole position to trader/orders.json (replacing the "
        "proposal there) and runs the risk check. An order that only closes what you hold is never "
        "blocked by the day limits. No order is sent."
    )
    if c2.button("Prepare the closing ticket", key="flat_go"):
        r = p.runner("positions")
        orders, res = broker.flatten(sym, shares, runner=r)
        if orders is None:
            st.error(res.message or res.stdout.strip() or res.status)
            return
        report, _ = risk.check(runner=r)
        tickets, _ = broker.show(runner=r)
        st.session_state["flat_result"] = (sym, report, tickets)
    found = st.session_state.get("flat_result")
    if found and found[0] == sym:
        _, report, tickets = found
        for v in report.results if report else []:
            (st.success if v.verdict == "PASS" else st.error)(
                f"check.py {v.verdict}: {v.side} {v.symbol} {v.amount} ({v.kind})"
            )
        st.markdown(
            "**Then, in your broker (or Claude chat with /trader-broker):**\n"
            "1. Cancel the bracket's open stop-loss and take-profit orders for this position (they hold the "
            "shares, so the broker rejects a new closing order until they're cancelled).\n"
            "2. Place the closing market order from the ticket below, after your explicit yes.\n"
            "3. Record the fill below, so the portfolio and today's ledger stay right."
        )
        claude_ticket(tickets)


def record_fills(p: Page) -> None:
    st.subheader("Record a fill by hand")
    st.caption(
        "If a fill happened outside Claude chat, record it here: it updates trader/portfolio.json (cash and "
        "shares) and today's ledger, through the skills' own ticket.py."
    )
    left, right = st.columns(2)
    with left.form("fill_form", clear_on_submit=True):
        st.markdown("**A fill** (a bracket's stop or target, or a closing order you placed)")
        a, b = st.columns(2)
        sym = a.text_input("Ticker").strip().upper()
        side = b.selectbox("Side", ["sell", "buy"])
        qty = a.number_input("Shares", min_value=0.0, value=0.0, step=1.0)
        px = b.number_input("Price", min_value=0.0, value=0.0, step=0.01, format="%.2f")
        if st.form_submit_button("Record fill") and sym and qty and px:
            res = broker.fill(sym, side, qty, px, date=p.today, runner=p.runner("positions"))
            (st.success if res.ok else st.error)(
                res.stdout.strip().splitlines()[0] if res.ok else res.message
            )
    with right.form("result_form", clear_on_submit=True):
        st.markdown("**What happened to an approved order** (after Claude's Allow once / Deny card)")
        a, b = st.columns(2)
        index = int(a.number_input("Order #", min_value=1, value=1, step=1))
        status = b.selectbox("Status", ["placed", "denied", "failed"])
        broker_id = a.text_input("Broker order id")
        fq = b.number_input("Filled shares", min_value=0.0, value=0.0, step=1.0)
        fp = a.number_input("Filled price", min_value=0.0, value=0.0, step=0.01, format="%.2f")
        note = b.text_input("Note")
        if st.form_submit_button("Record result"):
            res = broker.result(
                index,
                status,
                broker_id=broker_id or None,
                note=note or None,
                filled_qty=fq or None,
                filled_price=fp or None,
                runner=p.runner("positions"),
            )
            (st.success if res.ok and res.exit_code == 0 else st.error)(
                res.stdout.strip().splitlines()[0] if res.stdout.strip() else res.message or res.status
            )


def rule_level(x) -> str:
    """A rule's level as text: a price, a percent or a time (one column, so all text)."""
    if x.price is not None:
        return f"{x.price:.2f}"
    if x.pct is not None:
        return f"{x.pct:g} %"
    return x.at or ""


def alert_rules(p: Page) -> None:
    st.subheader("Alert rules")
    r = p.runner("positions")
    rules = alerts.list_rules(r)
    if rules:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Id": x.id,
                        "Ticker": x.symbol or "",
                        "Type": x.type,
                        "Level": rule_level(x),
                        "Day": x.date or "every day",
                        "Note": x.note or x.label or "",
                        "Rang": x.rang or "",
                    }
                    for x in rules
                ]
            ),
            hide_index=True,
        )
        rang = [x.id for x in rules if x.rang]
        if rang:
            c1, c2 = st.columns([2, 1])
            pick = c1.selectbox("Re-arm a rule that rang", rang, key="reset_id")
            if c2.button("Reset", key="reset_go"):
                res = alerts.reset(pick, runner=r)
                (st.success if res.ok else st.error)(res.stdout.strip() or res.message)
                st.rerun()
    else:
        st.caption(
            "No rules yet. The Trade Lab's **Add plan alerts** adds the stop, the target and flat-by "
            "in one go."
        )
    with st.form("add_rule", clear_on_submit=True):
        st.markdown("**Add a rule**")
        a, b, c, d = st.columns(4)
        kind = a.selectbox("When", list(KINDS), format_func=KINDS.get)
        sym = b.text_input("Ticker (not for times / the bell)").strip().upper()
        value = c.text_input("Level, % or HH:MM", placeholder="358.32 · 3 · 15:55")
        today_only = d.checkbox("Today only", value=True)
        label = a.text_input("Label (time rules)", placeholder="flat by close")
        before_close = b.checkbox(
            "Earlier on early closes", value=True, help="A time rule moves up with a 1 p.m. close"
        )
        if st.form_submit_button("Add rule"):
            try:
                val = None if kind == "opening_bell" else (value.strip() if kind == "at" else float(value))
            except ValueError:
                st.error("Give a number for a price or percent rule, or HH:MM for a time rule.")
                return
            rules, res = alerts.add_rule(
                kind,
                val,
                symbol=sym or None,
                label=label or None,
                before_close=kind == "at" and before_close,
                date=p.today if today_only else None,
                runner=r,
            )
            (st.success if res.ok else st.error)(
                res.stdout.strip().splitlines()[0] if res.ok else res.message
            )


def fired(p: Page) -> None:
    st.subheader("Alerts that rang")
    with session(p.engine) as s:
        rows = s.exec(
            select(AlertFired).where(AlertFired.mode == p.mode).order_by(col(AlertFired.id).desc()).limit(50)
        ).all()
    if not rows:
        st.caption(
            "None yet. The worker checks your rules every 2 minutes in the session"
            + (" (in replay: as the slider moves)." if p.mode == "replay" else ".")
        )
        return
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Day": a.session_date,
                    "At": dual_time(datetime.strptime(a.fired_ny, "%Y-%m-%d %H:%M").replace(tzinfo=NY)),
                    "Rule": a.rule_id,
                    "Message": a.message,
                    "Notified": "yes" if a.notified else "no",
                }
                for a in rows
            ]
        ),
        hide_index=True,
    )
    st.caption(f"Notifications: NOTIFY={p.settings.notify} in .env (none, toast or telegram).")


def live_parts() -> None:
    flat_by_countdown(page)
    st.session_state["held"] = positions(page)


st.fragment(run_every="30s" if page.mode == "live" else None)(live_parts)()
flatten_helper(page, st.session_state.get("held", []))
record_fills(page)
alert_rules(page)
fired(page)
footer()
