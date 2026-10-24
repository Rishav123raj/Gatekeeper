"""Table and list formatting used by the pages."""

from datetime import UTC, date, datetime

from app.components import charts
from app.components.tables import (
    dual_time,
    earnings_badge,
    hit_time_dual,
    hits_frame,
    news_badge,
    news_line,
    pct,
    price,
    tag_chips,
)
from gatekeeper.tables import EarningsSnapshot, NewsItem, ScanHit, ScanRun

DAY = date(2026, 10, 19)


def news(symbol="TSLA", tags=(), important=False, items=()):
    return NewsItem(
        mode="replay",
        key="k",
        item_id="i",
        symbol=symbol,
        title="Tesla [beats]",
        link="https://x",
        source="Yahoo Finance",
        kind="headline",
        tags=list(tags),
        important=important,
        items_8k=list(items),
        published_at=datetime(2026, 10, 19, 12, 4, tzinfo=UTC),
    )


def test_formats():
    assert price(364.18) == "$364.18" and price(None) == "n/a"
    assert pct(0.55) == "+0.55 %" and pct(-1.2, signed=False) == "-1.20 %"
    assert dual_time(datetime(2026, 10, 19, 14, 15, tzinfo=UTC)) == "10:15 NY · 19:45 IST"
    assert hit_time_dual("10:15 AM", DAY) == "10:15 NY · 19:45 IST"
    assert hit_time_dual("10:15 AM", date(2026, 11, 2)) == "10:15 NY · 20:45 IST"


def test_badges():
    items = [news(tags=["earnings"]), news(important=True), news(symbol="AAPL")]
    assert news_badge("TSLA", items) == "! 2 items"
    assert news_badge("AAPL", items) == "1 item"
    assert news_badge("NVDA", items) == ""
    soon = {"TSLA": EarningsSnapshot(mode="r", symbol="TSLA", next_report_date="2026-10-22")}
    assert earnings_badge("TSLA", soon, [], DAY) == "reports Thu 22 Oct"
    far = {"TSLA": EarningsSnapshot(mode="r", symbol="TSLA", next_report_date="2026-12-22")}
    assert earnings_badge("TSLA", far, items, DAY) == "earnings in the news"
    assert earnings_badge("AAPL", far, items, DAY) == ""


def test_hits_frame():
    hits = [
        ScanHit(
            scan_run_id=1,
            rank=1,
            symbol="TSLA",
            setups="orb",
            price=364.18,
            hit_time="10:15 AM",
            or_high=362.18,
            or_low=354.47,
            pct_over=0.55,
        )
    ]
    df = hits_frame(hits, DAY, [news(tags=["earnings"])], {})
    row = df.iloc[0]
    assert (row["Symbol"], row["Range"], row["Broke out at"], row["News"], row["Earnings"]) == (
        "TSLA",
        "354.47 – 362.18",
        "10:15 NY · 19:45 IST",
        "1 item",
        "earnings in the news",
    )


def test_news_line():
    line = news_line(news(tags=["earnings", "deal"], important=True, items=["2.02"]))
    assert line.startswith(":red-badge[! 8-K 2.02] **TSLA** · [Tesla (beats)](https://x)")
    assert "08:04 NY · 17:34 IST" in line
    assert tag_chips(["earnings", "deal"]) == ":red-badge[earnings] :violet-badge[deal]"


def test_charts_build():
    assert len(charts.sparkline([1, 2, 3], ref=2).data) == 1
    assert charts.breadth_gauge(18.5).data[0].value == 18.5
    runs = [
        ScanRun(
            mode="r",
            scan_mode="orb",
            session_date="2026-10-19",
            as_of="2026-10-19 10:15 ET",
            scanned=222,
            hits_count=41,
        )
    ]
    fig = charts.breadth_line(runs)
    assert list(fig.data[0].x) == ["10:15"] and list(fig.data[0].y) == [18.5]
