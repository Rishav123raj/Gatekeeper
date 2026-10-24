"""Watchlist & News: the pinned tickers, how far each has moved, its entry status, and the news."""

from __future__ import annotations

from datetime import UTC, date, timedelta

import pandas as pd
import streamlit as st

from app.components.page import Page, footer, setup_page
from app.components.tables import dual_time, news_line
from gatekeeper import store
from gatekeeper.db import session

page = setup_page("Watchlist & News", "📰")
st.title("Watchlist & News")
st.caption("Headlines are leads, not facts: open the story or the filing before acting on it.")


def watchlist(p: Page) -> list[str]:
    st.subheader("Pinned tickers")
    with session(p.engine) as s:
        pins = store.pinned(s, p.mode)
        moves = store.latest_moves(s, p.mode)
        entries = store.entries_for_day(s, p.mode, p.today)
        earnings = store.latest_earnings(s, p.mode)

    add, rem = st.columns(2)
    with add.form("pin_form", clear_on_submit=True, border=False):
        new = st.text_input("Pin tickers (comma-separated)", placeholder="TSLA, NVDA")
        if st.form_submit_button("Pin") and new.strip():
            with session(p.engine) as s:
                for sym in [x.strip().upper() for x in new.split(",") if x.strip()]:
                    store.pin(s, sym, p.mode)
            st.rerun()
    if pins:
        gone = rem.multiselect("Unpin", pins, key="unpin")
        if rem.button("Unpin selected", disabled=not gone):
            with session(p.engine) as s:
                for sym in gone:
                    store.unpin(s, sym, p.mode)
            st.rerun()

    if not pins:
        st.info(
            "Nothing pinned yet. Pin tickers here or from the Scanner; the worker's entry watch follows them."
        )
        return []
    rows = []
    for sym in pins:
        mv, e, er = moves.get(sym), entries.get(sym), earnings.get(sym)
        rows.append(
            {
                "Symbol": sym,
                "Last": mv.price if mv else None,
                "vs yesterday": mv.pct if mv else None,
                "MOVING": "MOVING" if mv and mv.moving else "",
                "Price as of": dual_time(mv.quote_time) if mv else "",
                "Entry": (
                    f"{e.status} at {e.trigger_price} ({e.trigger_time})"
                    if e and e.trigger_price
                    else e.status
                    if e
                    else "not checked yet"
                ),
                "Next earnings": er.next_report_date if er and er.next_report_date else "",
            }
        )
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        column_config={
            "Last": st.column_config.NumberColumn(format="$%.2f"),
            "vs yesterday": st.column_config.NumberColumn(format="%+.2f %%"),
        },
    )
    st.caption(
        "Price from the latest news check (MOVING = 3 % or more from yesterday's close). "
        "Entry from the worker's entry watch."
    )

    with st.expander("Next earnings date (by hand)"):
        st.caption(
            "SEC data has no report dates: take it from the news or the company's investor-relations page."
        )
        c1, c2, c3 = st.columns([1, 1, 1])
        sym = c1.selectbox("Ticker", pins, key="er_sym")
        current = earnings.get(sym)
        default = (
            date.fromisoformat(current.next_report_date) if current and current.next_report_date else None
        )
        d = c2.date_input("Reports on", value=default, key=f"er_date_{sym}")
        c3.write("")
        if c3.button("Save date", key="er_save"):
            with session(p.engine) as s:
                store.set_next_report_date(s, sym, p.mode, d.isoformat() if d else None)
            st.toast(f"{sym}: next report {d or 'cleared'}")
            st.rerun()
    return pins


def news_stream(p: Page, pins: list[str]) -> None:
    st.subheader("News")
    f1, f2, f3, f4 = st.columns([2, 2, 1, 1])
    hours = f4.selectbox("Last", [6, 12, 24, 48, 168], index=2, format_func=lambda h: f"{h} h", key="news_h")
    since = p.now.astimezone(UTC) - timedelta(hours=hours)
    with session(p.engine) as s:
        items = [
            n
            for n in store.news_items(s, p.mode, since=since, limit=500)
            if n.published_at is None or n.published_at <= p.now
        ]
    symbols = sorted({n.symbol for n in items if n.symbol})
    tags = sorted({t for n in items for t in n.tags or []})
    pick = f1.multiselect(
        "Tickers",
        symbols,
        default=[x for x in pins if x in symbols],
        key="news_sym",
        placeholder="All tickers",
    )
    pick_tags = f2.multiselect("Tags", tags, key="news_tags", placeholder="All tags")
    only = f3.toggle(
        "Important only",
        key="news_imp",
        help="8-K items marked !, and earnings, halt, legal, regulatory or risk tags",
    )
    shown = [
        n
        for n in items
        if (not pick or n.symbol in pick)
        and (not pick_tags or set(n.tags or []) & set(pick_tags))
        and (not only or store.is_important(n))
    ]
    st.caption(
        f"{len(shown)} of {len(items)} items in the last {hours} hours, newest first "
        "(New York and IST times)."
    )
    for n in shown[:100]:
        st.markdown(news_line(n))
    if not shown:
        st.caption("No news matches. The worker checks news at 08:45 NY and every 15 minutes in the session.")


pins = watchlist(page)
news_stream(page, pins)
footer()
