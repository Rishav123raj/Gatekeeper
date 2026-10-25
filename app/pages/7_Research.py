"""Research: what companies reported to the SEC, and what members of Congress disclosed."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st
from sqlmodel import select

from app.components import charts
from app.components.page import Page, footer, setup_page
from app.components.tables import price
from gatekeeper import store
from gatekeeper.db import session
from gatekeeper.skills import analyst, broker, pelosi
from gatekeeper.skills.models import EarningsFacts
from gatekeeper.tables import PelosiFiling

page = setup_page("Research", "🔬")
st.title("Research")
st.caption(
    "Background, not signals: the numbers companies filed, and the trades members of Congress disclosed."
)

REPLAY_EARNINGS = ["AAPL", "KO"]  # the recorded SEC data covers these two


def billions(x: float | None) -> str:
    return "n/a" if x is None else f"${x / 1e9:,.2f}B"


@st.cache_data(ttl=3600, show_spinner=False)
def facts_cached(tickers: tuple[str, ...], mode: str, _p: Page) -> tuple[list[dict], str]:
    """Cached an hour per (tickers, mode); `_p` is left out of the cache key (Streamlit skips _-names)."""
    res_list, res = analyst.facts(list(tickers), quarters=8, runner=_p.runner("research"))
    msg = (
        ""
        if res.status in ("ok",)
        else (res.stderr.strip().splitlines()[-1] if res.stderr.strip() else res.message)
    )
    return [f.model_dump() for f in res_list or []], msg


def earnings(p: Page) -> None:
    if p.mode == "live" and not p.settings.sec_user_agent:
        st.warning(
            "SEC requires a name and email in every request: set SEC_USER_AGENT in .env "
            '("Your Name you@example.com") to load earnings.'
        )
        return
    with session(p.engine) as s:
        pins = store.pinned(s, p.mode)
    options = REPLAY_EARNINGS if p.mode == "replay" else list(dict.fromkeys(pins + p.settings.core_tickers))
    pick = st.multiselect(
        "Companies",
        options,
        default=options[:2],
        key="er_pick",
        help="In replay, the recorded SEC data has AAPL and KO only.",
    )
    if not pick:
        return
    with st.spinner("Reading SEC EDGAR..."):
        data, msg = facts_cached(tuple(pick), p.mode, p)
    if msg:
        st.caption(f"analyst: {msg}")
    for d in data:
        f = EarningsFacts.model_validate(d)
        rows = f.result.rows
        st.markdown(f"#### {f.ticker} · {f.result.entity or ''}")
        if not rows:
            st.caption("No quarterly figures in the filings.")
            continue
        q, ttm = rows[0], f.result.ttm
        m = st.columns(5)
        m[0].metric(
            f"Revenue {q.fiscal or q.end}",
            billions(q.revenue),
            f"{q.revenue_yoy:+.1f} % y/y" if q.revenue_yoy is not None else None,
        )
        m[1].metric(
            "Diluted EPS", price(q.eps_diluted), f"{q.eps_yoy:+.1f} % y/y" if q.eps_yoy is not None else None
        )
        m[2].metric("Net margin", f"{q.net_margin:.1f} %" if q.net_margin is not None else "n/a")
        m[3].metric("Revenue, last 4 quarters", billions(ttm.get("revenue")))
        m[4].metric("EPS, last 4 quarters", price(ttm.get("eps_diluted")))
        a, b, c = st.columns(3)
        a.plotly_chart(
            charts.earnings_bars(rows, "revenue", "revenue ($)", "revenue_yoy"), key=f"rev_{f.ticker}"
        )
        b.plotly_chart(
            charts.earnings_bars(rows, "eps_diluted", "diluted EPS ($)", "eps_yoy"), key=f"eps_{f.ticker}"
        )
        c.plotly_chart(charts.margin_lines(rows), key=f"mar_{f.ticker}")
        flags = [x for x in (f.note,) if x]
        if any(r.derived for r in rows):
            flags.append(
                "a fourth quarter is derived (the 10-K year minus the three 10-Qs); "
                "derived EPS is approximate"
            )
        if q.net_income is not None and q.operating_income is not None and q.net_income > q.operating_income:
            flags.append("net income is above operating income: gains outside the business are inside it")
        for x in flags:
            st.warning(x)
        links = []
        report = (f.filings or {}).get("report") or {}
        eight_k = (f.filings or {}).get("earnings_8k") or {}
        if report.get("url"):
            links.append(f"[{report.get('form')} filed {report.get('filed')}]({report['url']})")
        if eight_k.get("exhibit"):
            links.append(f"[earnings press release, filed {eight_k.get('filed')}]({eight_k['exhibit']})")
        if links:
            st.markdown(" · ".join(links))
        for line in f.changes[:3]:
            st.caption(line)
    st.caption(
        "Growth is against the same quarter a year earlier. The next report date isn't in SEC data: set it "
        "by hand on the Watchlist & News page."
    )


def congress(p: Page) -> None:
    st.info(
        "Members of Congress must disclose trades within 45 days (the STOCK Act). These are public filings, "
        "read quickly: by the time anyone can read one, the trade is days or weeks old. "
        "Not inside information "
        "and not a signal.",
        icon="ℹ️",
    )
    c1, c2, c3 = st.columns([2, 1, 1])
    member = c1.text_input("Member (last name, or blank for all)", value="pelosi", key="ptr_member").strip()
    days = c2.selectbox(
        "Filed in the last", [30, 60, 90, 365], index=1, format_func=lambda d: f"{d} days", key="ptr_days"
    )
    since = (p.now - timedelta(days=days)).date().isoformat()
    filings, res = pelosi.index(member or None, since=since, limit=200, runner=p.runner("research"))
    if filings is None:
        st.error(res.message or res.status)
        return
    pf = broker.portfolio(p.runner("research"))
    with session(p.engine) as s:
        watched = set(store.pinned(s, p.mode)) | {x.ticker for x in (pf.positions if pf else [])}
        stored = {f.doc_id: f for f in s.exec(select(PelosiFiling).where(PelosiFiling.mode == p.mode))}
    rows = []
    for f in filings:
        known = stored.get(f.doc_id)
        tickers = sorted({r.get("ticker") for r in (known.rows or []) if r.get("ticker")}) if known else []
        rows.append(
            {
                "Filed": f.filed,
                "Member": f.name,
                "District": f.district,
                "Report": f.url,
                "Tickers": ", ".join(tickers) if tickers else "open the PDF",
                "You watch": "yes" if watched & set(tickers) else "",
            }
        )
    c3.metric("Filings", len(rows))
    if not rows:
        st.caption("No matching filings in that window.")
        return
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        column_config={"Report": st.column_config.LinkColumn(display_text="PTR (PDF)")},
    )
    st.caption(
        "Tickers show once a report has been read (the worker's Congress job, or ptr.py fetch). "
        "'You watch' flags a pinned ticker or a holding. Amounts in the reports are ranges, never exact."
    )


tab_e, tab_c = st.tabs(["Earnings", "Congress"])
with tab_e:
    earnings(page)
with tab_c:
    congress(page)
footer()
