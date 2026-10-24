"""Gatekeeper Desk: Market Overview. Run with `uv run streamlit run app/Home.py`."""

from __future__ import annotations

from datetime import UTC, date, timedelta

import pandas as pd
import streamlit as st

from app.components import charts
from app.components.page import Page, footer, setup_page
from app.components.tables import news_line, pct, price
from gatekeeper import regime, store, yahoo
from gatekeeper.db import session
from gatekeeper.skills._base import read_json
from gatekeeper.skills.models import BrokerRecord

page = setup_page("Market Overview")

st.title("Gatekeeper")
st.caption("Every trade has to earn its way in.")


@st.cache_data(ttl=60, show_spinner=False)
def live_regime(breadth_pct: float | None) -> dict:
    """Live index tiles straight from Yahoo (cached a minute), so they work even without the worker."""
    return regime.snapshot(yahoo.live(), breadth_pct).to_dict()


def latest_breadth(p: Page) -> tuple[float | None, list]:
    with session(p.engine) as s:
        runs = store.scan_runs(s, p.mode, "orb", p.today)
    last = runs[-1] if runs else None
    return (regime.breadth(last.hits_count, last.scanned) if last else None), runs


def market_context(p: Page) -> None:
    breadth_pct, runs = latest_breadth(p)
    if p.mode == "live":
        snap = live_regime(breadth_pct)
    else:
        with session(p.engine) as s:
            row = store.latest_regime(s, "replay")
        snap = row.payload if row else None

    st.subheader("Market context")
    st.info(
        "Day-level Go / No-Go arrives in Phase 5. The context below is information, not a signal.", icon="ℹ️"
    )
    if snap is None:
        st.caption("No market context yet: the worker records it every 5 minutes during the session.")
    else:
        colors = {"supportive": "green", "mixed": "orange", "hostile": "red", "unknown": "gray"}
        lab = snap["label"]
        st.markdown(
            f"Tape: :{colors.get(lab, 'gray')}-badge[{lab.upper()}] score {snap['score']:+d} · "
            + " · ".join(snap["reasons"])
        )
        tiles = [*snap["indexes"].values(), snap["vix"]]
        cols = st.columns(len(tiles))
        for col, t in zip(cols, tiles, strict=True):
            with col:
                name = "VIX" if t["symbol"] == "^VIX" else t["symbol"]
                if not t["available"]:
                    st.metric(name, "n/a", help="No data for this series (in replay: not in the recording).")
                    continue
                st.metric(
                    name,
                    price(t["price"]).lstrip("$") if name == "VIX" else price(t["price"]),
                    pct(t["change_pct"]),
                    delta_color="inverse" if name == "VIX" else "normal",
                )
                st.plotly_chart(
                    charts.sparkline(t["spark"], t["prev_close"]),
                    config={"displayModeBar": False},
                    key=f"spark_{name}",
                )
                if name != "VIX":
                    st.caption(
                        f"VWAP {pct(t['vs_vwap_pct'])} · OR {t['vs_or'] or 'n/a'} · "
                        f"20-day {pct(t['vs_ma20_pct'])}"
                    )

    g, line = st.columns([1, 2])
    with g:
        st.plotly_chart(charts.breadth_gauge(breadth_pct), key="gauge")
    with line:
        if runs:
            st.plotly_chart(charts.breadth_line(runs), key="breadth_line")
        else:
            st.caption("No opening-range scan yet today (the first runs at 09:50 NY, 19:20 IST).")


def budget(p: Page) -> None:
    st.subheader("Today's risk budget")
    cfg = read_json(p.trader_dir / "config.json", {}) or {}
    rows = [
        BrokerRecord.model_validate(r)
        for r in (read_json(p.trader_dir / "state" / "broker.json", {}) or {}).get("orders", [])
    ]
    placed = [r for r in rows if r.day == p.today and r.status == "placed" and r.kind == "entry"]
    used = sum(r.max_loss or 0 for r in placed)
    max_loss, max_trades = cfg.get("max_daily_loss_usd"), cfg.get("max_trades_per_day")
    a, b = st.columns(2)
    with a:
        if max_loss:
            st.progress(
                min(used / max_loss, 1.0), text=f"Risk used: ${used:,.2f} of ${max_loss:,.0f} daily loss"
            )
        else:
            st.caption("No `max_daily_loss_usd` in trader/config.json yet (set it up with /trader-budget).")
    with b:
        if max_trades:
            st.progress(min(len(placed) / max_trades, 1.0), text=f"Trades: {len(placed)} of {max_trades}")
        else:
            st.caption("No `max_trades_per_day` in trader/config.json yet.")


def what_changed(p: Page) -> None:
    st.subheader("What changed")
    since = p.now.astimezone(UTC) - timedelta(hours=24)
    with session(p.engine) as s:
        orb = store.latest_scan(s, p.mode, "orb")
        hits = store.scan_hits(s, orb)[:8] if orb and orb.session_date == p.today else []
        news = [
            n
            for n in store.news_items(s, p.mode, since=since, limit=100)
            if store.is_important(n) and (n.published_at is None or n.published_at <= p.now)
        ][:6]
        fired = store.alerts_for_day(s, p.mode, p.today)[:6]
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Latest breakouts** (matched a rule, not a buy list)")
        if hits:
            st.caption(f"ORB scan {orb.as_of}: {orb.hits_count} of {orb.scanned} usable charts")
            for h in hits:
                st.markdown(f"**{h.symbol}** {price(h.price)} · {pct(h.pct_over)} over · {h.hit_time}")
        else:
            st.caption("No breakouts recorded today.")
    with c2:
        st.markdown("**Important news**")
        for n in news:
            st.markdown(news_line(n))
        if not news:
            st.caption("Nothing flagged in the last 24 hours.")
    with c3:
        st.markdown("**Alerts fired today**")
        for a in fired:
            st.markdown(f"**{a.fired_ny[11:]} NY** · {a.message}")
        if not fired:
            st.caption("No alert rang today.")


def worker_health(p: Page) -> None:
    with session(p.engine) as s:
        beats = store.heartbeats(s, p.mode)
    with st.expander(f"Worker health ({p.mode})", expanded=not beats):
        if not beats:
            st.caption(
                "No job has run yet. Start the worker: `uv run python -m worker`."
                if p.mode == "live"
                else "The replay hasn't run yet."
            )
            return
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Job": h.job,
                        "Last": h.last_status,
                        "At (NY)": (h.last_run_ny or "")[11:],
                        "Runs": h.runs,
                        "Errors": h.errors,
                        "Detail": h.last_detail,
                    }
                    for h in beats
                ]
            ),
            hide_index=True,
        )


def live_parts() -> None:
    market_context(page)
    budget(page)
    what_changed(page)
    worker_health(page)


# Live: refresh every 30 s. Replay: the time only moves with the slider.
st.fragment(run_every="30s" if page.mode == "live" else None)(live_parts)()

if page.mode == "replay" and page.now.date() == date(2026, 10, 19):
    st.caption("Replay: the recorded day has no SPY / QQQ / IWM / VIX charts, so those tiles show n/a.")
footer()
