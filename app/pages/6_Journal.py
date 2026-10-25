"""Journal: every decision and its result in R, and whether following Gatekeeper helped."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlmodel import col, select

from app.components import charts
from app.components.page import Page, footer, setup_page
from gatekeeper import journal, store
from gatekeeper.db import session
from gatekeeper.tables import Decision, Plan, TradeJournal
from worker.jobs import run_job

page = setup_page("Journal", "📓")
st.title("Journal")
st.caption(
    "Every plan's result in R (1R = the plan's risk a share): real for trades you took, simulated on the "
    "day's bars for the ones you skipped. Past results don't predict the next trade."
)


def decision_log(p: Page) -> None:
    st.subheader("Decisions")
    with session(p.engine) as s:
        rows = s.exec(
            select(Decision, Plan)
            .join(Plan, isouter=True)
            .where(Decision.mode == p.mode)
            .order_by(col(Decision.id).desc())
            .limit(200)
        ).all()
        journal_by_plan = {
            j.plan_id: j for j in s.exec(select(TradeJournal).where(TradeJournal.mode == p.mode))
        }
    if not rows:
        st.caption("No decisions yet: log Taken or Skipped from the Trade Lab's Go / No-Go panel.")
        return
    df = pd.DataFrame(
        [
            {
                "id": d.id,
                "Day": plan.date if plan else "",
                "Ticker": d.symbol or (plan.symbol if plan else ""),
                "Decision": d.action,
                "Go / No-Go": (d.overall or "").replace("_", " "),
                "Rules followed": d.followed_rules,
                "Result (R)": (
                    journal_by_plan.get(d.plan_id).r_result if journal_by_plan.get(d.plan_id) else None
                ),
                "Note": d.reason_note,
            }
            for d, plan in rows
        ]
    )
    edited = st.data_editor(
        df,
        hide_index=True,
        disabled=[c for c in df.columns if c != "Note"],
        key="decisions",
        column_config={"id": None, "Result (R)": st.column_config.NumberColumn(format="%+.2f")},
    )
    changed = [
        (int(r["id"]), r["Note"])
        for r, o in zip(edited.to_dict("records"), df.to_dict("records"), strict=True)
        if r["Note"] != o["Note"]
    ]
    if changed and st.button(f"Save {len(changed)} note change(s)", key="save_notes"):
        with session(p.engine) as s:
            for did, note in changed:
                store.update_decision_note(s, did, note or "")
        st.success("Notes saved.")


def tiles(label: str, s: dict) -> None:
    st.markdown(f"**{label}**")
    m = st.columns(7)
    m[0].metric("Trades", s["n"])
    m[1].metric("Won", f"{100 * s['win_rate']:.0f} %" if s["win_rate"] is not None else "n/a")
    m[2].metric("Expectancy", f"{s['expectancy_r']:+.2f}R" if s["expectancy_r"] is not None else "n/a")
    m[3].metric("Avg win / loss", f"{s['avg_win_r'] or 0:+.2f} / {s['avg_loss_r'] or 0:+.2f}R")
    m[4].metric("Profit factor", s["profit_factor"] if s["profit_factor"] is not None else "n/a")
    m[5].metric("Max drawdown", f"{s['max_dd_r']:+.2f}R")
    m[6].metric("Losing streak", s["longest_losing_streak"])


def results(p: Page) -> list[journal.Trade]:
    st.subheader("Results")
    with session(p.engine) as s:
        trades = store.journal_trades(s, p.mode)
    c1, c2 = st.columns([3, 1])
    c1.caption(
        "The end-of-day journal runs at 16:10 NY (01:40 IST; 02:40 IST after Nov 1) and fills in every "
        "plan of the day. Rows marked 'needs fill' wait for you to record the fills (Positions & Alerts)."
    )
    if c2.button("Run the end-of-day journal now", key="eod_now"):
        status, detail = run_job(p.job_context(), "eod_journal")
        (st.success if status == "ok" else st.info if status == "skipped" else st.error)(
            f"{status}: {detail}"
        )
        with session(p.engine) as s:
            trades = store.journal_trades(s, p.mode)
    taken = [t for t in trades if t.taken and not t.simulated]
    tiles("Trades you took (real fills)", journal.stats(taken))
    tiles("Every plan, skipped ones simulated", journal.stats(trades))
    adherence = journal.stats(trades)["adherence_rate"]
    st.caption(
        f"Rules followed: {f'{100 * adherence:.0f} %' if adherence is not None else 'n/a'} of decisions · "
        f"{sum(1 for t in trades if t.r is None)} row(s) without a result yet"
    )
    done = [t for t in trades if t.r is not None]
    if done:
        a, b = st.columns([3, 2])
        a.plotly_chart(
            charts.cumulative_r(
                {
                    "taken": [t.r for t in taken if t.r is not None],
                    "every plan (incl. simulated)": [t.r for t in done],
                }
            ),
            key="cum",
        )
        b.plotly_chart(charts.r_histogram([t.r for t in done]), key="hist")
    return trades


def calibration(trades: list[journal.Trade]) -> None:
    st.subheader("Did the Time Machine's verdicts hold up?")
    rows = journal.calibration(trades)
    n = sum(r["n"] for r in rows)
    if n < journal.MIN_TRADES:
        st.info(
            f"Not enough trades yet: {n} of the {journal.MIN_TRADES} needed before these numbers mean much. "
            "Keep logging every plan, taken or skipped."
        )
    if rows:
        st.plotly_chart(charts.calibration_bar(rows), key="calib")
        st.caption(
            "If 'Leans target' doesn't win more often than 'Coin flip' over 40+ trades, the filter isn't "
            "helping you yet."
        )


def breakdowns(trades: list[journal.Trade]) -> None:
    st.subheader("Breakdowns")
    cols = st.columns(3)
    for col_, (by, title) in zip(
        cols,
        (("setup", "By setup"), ("entry_bucket", "By entry time (NY)"), ("weekday", "By weekday")),
        strict=True,
    ):
        col_.markdown(f"**{title}**")
        rows = journal.breakdown(trades, by)
        if rows:
            col_.dataframe(pd.DataFrame(rows), hide_index=True)
        else:
            col_.caption("No results yet.")


def readiness(trades: list[journal.Trade]) -> None:
    st.subheader("Paper → live readiness (display only)")
    for c in journal.readiness_card(trades):
        st.markdown(
            f"{'✅' if c['ok'] else '⬜'} {c['check']} · now: "
            + (str(c["value"]) if c["value"] is not None else "n/a")
        )
    st.caption(
        "This only shows the checklist from the guide. Going live is your own decision, made in "
        "trader/config.json yourself; Gatekeeper never switches it."
    )


def export(p: Page) -> None:
    with session(p.engine) as s:
        rows = s.exec(
            select(TradeJournal).where(TradeJournal.mode == p.mode).order_by(col(TradeJournal.id))
        ).all()
    if rows:
        df = pd.DataFrame([r.model_dump(exclude={"created_at"}) for r in rows])
        st.download_button(
            "Download the journal (CSV)",
            df.to_csv(index=False).encode("utf-8"),
            file_name=f"gatekeeper-journal-{p.mode}.csv",
            mime="text/csv",
            key="csv",
        )


decision_log(page)
all_trades = results(page)
calibration(all_trades)
breakdowns(all_trades)
readiness(all_trades)
export(page)
footer()
