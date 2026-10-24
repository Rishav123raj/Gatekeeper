"""Scanner: which charts matched a setup today. A list of charts that match a rule, not a buy list."""

from __future__ import annotations

from datetime import UTC, date, timedelta

import streamlit as st

from app.components import charts
from app.components.page import Page, footer, setup_page
from app.components.tables import hits_frame
from gatekeeper import store
from gatekeeper.db import session
from worker.jobs import run_job

page = setup_page("Scanner", "🔎")
st.title("Scanner")
st.caption(
    "Charts that matched a rule today. A match is not a recommendation: read the news and "
    "check the entry before anything else."
)

SETUP_LABELS = {
    "breakout_20d": "20-day breakout",
    "bull_flag": "bull flag",
    "reclaim_ma20": "reclaimed 20-day avg",
    "oversold": "oversold",
    "oversold_bounce": "oversold bounce",
    "orb": "opening-range breakout",
}


def run_now(p: Page, job: str) -> None:
    st.session_state["scan_running"] = True
    try:
        with st.spinner(f"Running {job.replace('_', ' ')}..."):
            status, detail = run_job(p.job_context(), job)
    finally:
        st.session_state["scan_running"] = False
    (st.success if status == "ok" else st.warning if status == "skipped" else st.error)(f"{status}: {detail}")


def scan_tab(p: Page, scan_mode: str) -> None:
    with session(p.engine) as s:
        runs = store.scan_runs(s, p.mode, scan_mode, p.today)
        since = p.now.astimezone(UTC) - timedelta(hours=36)
        news = [
            n
            for n in store.news_items(s, p.mode, since=since, limit=500)
            if n.published_at is None or n.published_at <= p.now
        ]
        earnings = store.latest_earnings(s, p.mode)
        runs_hits = {r.id: store.scan_hits(s, r) for r in runs}

    job = "orb_scan" if scan_mode == "orb" else "daily_scan"
    top = st.columns([3, 1])
    with top[1]:
        if st.button(
            "Run scan now",
            key=f"run_{scan_mode}",
            disabled=st.session_state.get("scan_running", False),
            help="Runs the worker's scan job once, now (it checks the session clock first).",
        ):
            run_now(p, job)
            st.rerun()
    if not runs:
        with top[0]:
            when = "09:50 NY (19:20 IST)" if scan_mode == "orb" else "08:30 NY (18:00 IST)"
            st.info(
                f"No {'opening-range' if scan_mode == 'orb' else 'pre-market'} scan today yet. "
                f"The worker runs the first at {when}."
            )
        return

    labels = {r.id: f"{r.as_of} · {r.hits_count} hits" for r in runs}
    with top[0]:
        run_id = st.selectbox(
            "Scan", list(reversed(list(labels))), format_func=labels.get, key=f"pick_{scan_mode}"
        )
    run = next(r for r in runs if r.id == run_id)
    hits = runs_hits[run.id]

    usable = f"{run.scanned:,} usable" if scan_mode == "orb" else f"{run.scanned:,} scanned"
    line = (
        f"**{run.hits_count}** of {usable} charts matched · {run.universe:,} requested · "
        f"{run.failed} failed or had no data"
    )
    if run.partial:
        line += f" · :orange-badge[PARTIAL: {run.unconfirmed} candidates not checked]"
    st.markdown(line)

    f1, f2, f3 = st.columns([2, 1, 2])
    query = f1.text_input("Symbol contains", key=f"q_{scan_mode}").strip().upper()
    min_price = f2.number_input("Min price", min_value=0.0, value=0.0, step=1.0, key=f"mp_{scan_mode}")
    present = sorted({x for h in hits for x in h.setups.split(",")})
    setups = (
        f3.multiselect(
            "Setups",
            present,
            default=present,
            format_func=lambda k: SETUP_LABELS.get(k, k),
            key=f"su_{scan_mode}",
        )
        if len(present) > 1
        else present
    )
    shown = [
        h
        for h in hits
        if (not query or query in h.symbol)
        and h.price >= min_price
        and set(h.setups.split(",")) & set(setups)
    ]

    df = hits_frame(shown, date.fromisoformat(p.today), news, earnings)
    if scan_mode == "orb":
        df = df.drop(columns=["RSI"])
    else:
        df = df.drop(columns=["Range", "% over", "Broke out at"])
    event = st.dataframe(
        df,
        hide_index=True,
        on_select="rerun",
        selection_mode="multi-row",
        key=f"tbl_{scan_mode}",
        column_config={
            "Price": st.column_config.NumberColumn(format="$%.2f"),
            "% over": st.column_config.NumberColumn(format="%+.2f %%"),
            "RSI": st.column_config.NumberColumn(format="%.1f"),
        },
    )
    picked = [shown[i].symbol for i in event.selection.rows] if event and event.selection.rows else []

    b1, b2, b3 = st.columns([1, 1, 3])
    if b1.button(
        "Pin selected",
        key=f"pin_{scan_mode}",
        disabled=not picked,
        help="Adds them to the watchlist and the worker's entry watch.",
    ):
        with session(p.engine) as s:
            for sym in picked:
                store.pin(s, sym, p.mode)
        st.toast(f"Pinned {', '.join(picked)}")
    if b2.button(
        "Open in Trade Lab", key=f"lab_{scan_mode}", disabled=len(picked) != 1, help="Select exactly one row."
    ):
        st.session_state["symbol"] = picked[0]
        st.switch_page("pages/3_Trade_Lab.py")
    b3.caption(
        "Select rows in the table to pin them or open one in the Trade Lab. "
        "A later breakout is closer to the price now; re-check before acting."
    )

    if scan_mode == "orb" and len(runs) > 1:
        st.plotly_chart(charts.breadth_line(runs), key="scanner_breadth")


tab_daily, tab_orb = st.tabs(["Pre-market (daily)", "Opening-range breakouts"])
with tab_daily:
    scan_tab(page, "daily")
with tab_orb:
    scan_tab(page, "orb")
footer()
