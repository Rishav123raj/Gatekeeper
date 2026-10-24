"""Shared formatting for the dashboard's tables and lists. Pure functions, so they are tested."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from gatekeeper.clock import as_ny, to_ist
from gatekeeper.tables import EarningsSnapshot, NewsItem, ScanHit

TAG_COLORS = {
    "earnings": "red",
    "halt": "red",
    "legal": "orange",
    "regulatory": "orange",
    "risk": "orange",
    "deal": "violet",
    "analyst": "blue",
    "capital": "blue",
    "people": "gray",
    "macro": "gray",
}


def price(x: float | None) -> str:
    return "n/a" if x is None else f"${x:,.2f}"


def pct(x: float | None, signed: bool = True) -> str:
    return "n/a" if x is None else (f"{x:+.2f} %" if signed else f"{x:.2f} %")


def dual_time(dt: datetime | None) -> str:
    """'10:15 NY · 19:45 IST'"""
    if dt is None:
        return ""
    return f"{as_ny(dt):%H:%M} NY · {to_ist(dt):%H:%M} IST"


def hit_time_dual(hit_time: str | None, day: date) -> str:
    """A scanner time like '10:15 AM' (New York) on `day`, shown in both zones."""
    if not hit_time:
        return ""
    t = datetime.strptime(hit_time, "%I:%M %p").time()
    return dual_time(datetime.combine(day, t))


def earnings_badge(
    symbol: str, earnings: dict[str, EarningsSnapshot], news: list[NewsItem], today: date
) -> str:
    """A next report date within 10 days, else 'in the news' when today's news is tagged earnings."""
    snap = earnings.get(symbol)
    if snap and snap.next_report_date:
        d = date.fromisoformat(snap.next_report_date)
        if 0 <= (d - today).days <= 10:
            return f"reports {d:%a %d %b}"
    if any(n.symbol == symbol and "earnings" in (n.tags or []) for n in news):
        return "earnings in the news"
    return ""


def news_badge(symbol: str, news: list[NewsItem]) -> str:
    mine = [n for n in news if n.symbol == symbol]
    if not mine:
        return ""
    important = any(n.important for n in mine)
    return f"{'! ' if important else ''}{len(mine)} item{'s' if len(mine) != 1 else ''}"


def hits_frame(
    hits: list[ScanHit], day: date, news: list[NewsItem], earnings: dict[str, EarningsSnapshot]
) -> pd.DataFrame:
    rows = []
    for h in hits:
        rows.append(
            {
                "#": h.rank,
                "Symbol": h.symbol,
                "Setups": h.setups.replace(",", ", ").replace("_", " "),
                "Price": h.price,
                "Range": f"{h.or_low:.2f} – {h.or_high:.2f}"
                if h.or_low is not None and h.or_high is not None
                else "",
                "% over": h.pct_over,
                "Broke out at": hit_time_dual(h.hit_time, day),
                "RSI": h.rsi,
                "News": news_badge(h.symbol, news),
                "Earnings": earnings_badge(h.symbol, earnings, news, day),
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "#",
            "Symbol",
            "Setups",
            "Price",
            "Range",
            "% over",
            "Broke out at",
            "RSI",
            "News",
            "Earnings",
        ],
    )


def tag_chips(tags: list[str] | None) -> str:
    """Streamlit markdown badges, e.g. ':red-badge[earnings]'."""
    return " ".join(f":{TAG_COLORS.get(t, 'gray')}-badge[{t}]" for t in tags or [])


def news_line(item: NewsItem) -> str:
    when = dual_time(item.published_at)
    title = item.title.replace("[", "(").replace("]", ")")
    link = f"[{title}]({item.link})" if item.link else title
    bang = ""
    if item.important:
        codes = ", ".join(item.items_8k or [])
        bang = f":red-badge[! 8-K {codes}] " if codes else ":red-badge[!] "
    who = f"**{item.symbol}** · " if item.symbol else ""
    return f"{bang}{who}{link}  \n:gray[{when} · {item.source}] {tag_chips(item.tags)}"
