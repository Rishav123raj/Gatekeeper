"""Risk & Size: your limits, how the current plan is sized, what the risk check says, today's
ledger, and a 'what if' sandbox that never touches trader/."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.components import charts
from app.components.page import Page, footer, setup_page
from app.components.tables import price
from gatekeeper.readiness import broker_records
from gatekeeper.sandbox import what_if
from gatekeeper.skills import budget, risk
from gatekeeper.skills._base import read_json
from gatekeeper.skills.models import RiskReport, SizeResult

page = setup_page("Risk & Size", "📏")
st.title("Risk & Size")
st.caption(
    "Your limits, how the current plan is sized, and what the risk check says. Read-only: nothing here "
    "changes an order, and the 'what if' runs on a throwaway copy."
)


def limits_card(p: Page) -> dict:
    st.subheader("Your limits")
    cfg = read_json(p.trader_dir / "config.json", {}) or {}
    if not cfg:
        st.info(
            "No trader/config.json yet. Set your rules once with /trader-budget in Claude chat "
            "(or copy the skills' config.example.json)."
        )
        return cfg
    budget_usd = cfg.get("budget") or 0
    m = st.columns(5)
    m[0].metric(
        "Budget", price(budget_usd), f"{cfg.get('cash_buffer_pct', 0)} % kept in cash", delta_color="off"
    )
    m[1].metric("Max loss / trade", price(cfg.get("max_loss_per_trade_usd")))
    m[2].metric("Max loss / day", price(cfg.get("max_daily_loss_usd")))
    m[3].metric("Trades / day", cfg.get("max_trades_per_day", "n/a"))
    m[4].metric("Min reward : risk", cfg.get("min_reward_risk", "n/a"))
    m = st.columns(5)
    m[0].metric("Max position", f"{cfg.get('max_position_pct', 'n/a')} %")
    m[1].metric("Max order", price(cfg.get("max_order_usd")))
    m[2].metric("Entries", f"{cfg.get('no_entries_before', '?')}–{cfg.get('no_entries_after', '?')} NY")
    m[3].metric("Flat by", f"{cfg.get('flat_by', '?')} NY")
    m[4].metric(
        "Account",
        "PAPER" if cfg.get("paper", True) else "LIVE",
        help="Change this only in trader/config.json yourself; Gatekeeper never switches it.",
    )
    blocked = ", ".join(cfg.get("blocked") or []) or "none"
    allow = [k.replace("allow_", "") for k in ("allow_options", "allow_margin", "allow_short") if cfg.get(k)]
    st.caption(
        f"Blocked tickers: {blocked} · options / margin / short: {', '.join(allow) or 'all off'} · "
        f"PDT guard: {'on' if cfg.get('pdt_guard') else 'off'}"
    )
    return cfg


def sizing_panel(p: Page) -> tuple[SizeResult | None, RiskReport | None]:
    st.subheader("Sizing and the risk check")
    plan = read_json(p.trader_dir / "plan.json")
    if not plan:
        st.info("No plan yet: plan the exit in the Trade Lab first.")
        return None, None
    r = p.runner("risk_page")
    size, sres = budget.size(write=False, runner=r)  # read-only: shows the sizing, writes no order
    report, rres = risk.check(no_write=True, runner=r)  # read-only: checks trader/orders.json as it is
    left, right = st.columns(2)
    with left:
        st.markdown(
            f"**Plan:** {plan.get('symbol')} entry {price(plan.get('entry'))} · stop "
            f"{price(plan.get('stop'))} · target {price(plan.get('target'))} ({plan.get('date')})"
        )
        if size is None:
            st.error(sres.message or "size.py gave no answer")
        else:
            z = size.sizing
            if z.limits:
                st.plotly_chart(charts.size_limits_bar(z), key="limits_bar")
            if size.refused:
                st.error(z.refusal)
            else:
                st.markdown(
                    f"**{z.qty} shares** · {price(z.cost)} · {price(z.max_loss)} at the stop · "
                    f"bound by **{z.bound_by}**"
                )
            for n in size.notes:
                st.caption(n)
    with right:
        st.markdown("**trader/orders.json, checked now** (without recording)")
        if report is None:
            st.info(rres.message or "No orders to check yet: use Size & check in the Trade Lab.")
        else:
            for v in report.results:
                box = st.success if v.verdict == "PASS" else st.error
                box(
                    f"{v.verdict} #{v.index} {v.side} {v.symbol} {v.amount} ({v.kind}): max loss "
                    f"{price(v.max_loss)}, reward:risk {v.reward_risk}"
                )
                for reason in v.reasons:
                    st.markdown(f"- {reason}")
                for w in v.warnings:
                    st.warning(w)
            st.caption(
                f"Checked at {report.now_new_york} NY · {'PAPER' if report.paper else 'LIVE'} account"
                + (f" · cash after: {price(report.cash_after)}" if report.cash_after is not None else "")
            )
    return size, report


def what_if_panel(p: Page, size: SizeResult | None, report: RiskReport | None) -> None:
    st.subheader("What if")
    if size is None:
        st.caption("Plan the exit first.")
        return
    z = size.sizing
    st.caption(
        "Runs size.py and check.py on a throwaway copy of trader/ with your price and share count. "
        "Your trader/ folder is not changed."
    )
    c1, c2, c3 = st.columns([1, 1, 1])
    px = c1.number_input(
        "Price",
        min_value=0.01,
        value=float(z.entry or z.entry_plan or 1.0),
        step=0.10,
        format="%.2f",
        key="wi_price",
    )
    order_qty = int(report.results[0].amount.split()[0]) if report and report.results else (z.qty or 1)
    qty = int(
        c2.number_input("Shares in the order", min_value=1, value=max(order_qty, 1), step=1, key="wi_qty")
    )
    c3.write("")
    if c3.button("Run what if", key="wi_run"):
        fixtures = p.settings.skills_path / "tests" / "fixtures" if p.mode == "replay" else None
        w = what_if(p.trader_dir, p.settings, p.now, z.symbol, price=px, qty=qty, replay_fixtures=fixtures)
        st.session_state["wi_result"] = w
    w = st.session_state.get("wi_result")
    if w is None:
        return
    a, b = st.columns(2)
    with a:
        st.markdown(f"**size.py at {price(w.price)}**")
        if w.size is None:
            st.error(w.size_message)
        elif w.size.refused:
            st.error(w.size.sizing.refusal)
        else:
            ws = w.size.sizing
            st.markdown(
                f"{ws.qty} shares · {price(ws.max_loss)} at the stop · reward:risk {ws.reward_risk} · "
                f"bound by {ws.bound_by}"
            )
    with b:
        st.markdown(f"**check.py on {w.qty} shares at {price(w.price)}**")
        if w.risk is None:
            st.error(w.risk_message)
        else:
            for v in w.risk.results:
                box = st.success if v.verdict == "PASS" else st.error
                box(
                    f"{v.verdict}: max loss {price(v.max_loss)}, reward:risk {v.reward_risk}"
                    + (" · " + "; ".join(v.reasons) if v.reasons else "")
                )


def ledger(p: Page) -> None:
    st.subheader("Today's ledger")
    rows = [r for r in broker_records(p.trader_dir) if r.day == p.today]
    if not rows:
        st.caption("Nothing recorded today: no ticket approved, placed or filled.")
        return
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "At (NY)": (r.at or "")[11:16],
                    "Status": r.status,
                    "Order": r.plain,
                    "Max loss": r.max_loss,
                    "Reply": r.reply or "",
                    "Broker id": r.broker_order_id or "",
                }
                for r in rows
            ]
        ),
        hide_index=True,
        column_config={"Max loss": st.column_config.NumberColumn(format="$%.2f")},
    )
    placed = [r for r in rows if r.status == "placed" and r.kind == "entry"]
    st.caption(f"{len(placed)} entries placed today · {price(sum(r.max_loss or 0 for r in placed))} at risk")


limits_card(page)
size_now, report_now = sizing_panel(page)
what_if_panel(page, size_now, report_now)
ledger(page)
footer()
