"""The dashboard's own chart reader: parsing, the replay cut, and polite live fetching (mocked)."""

import json
from datetime import datetime

import httpx
import pytest

from gatekeeper import yahoo
from gatekeeper.clock import NY
from gatekeeper.settings import get_settings

FIX = get_settings().skills_path / "tests" / "fixtures"
TSLA = FIX / "trader-entry" / "TSLA-2026-10-19-5m.json"


def replay(h, m):
    return yahoo.ReplayYahoo(FIX, datetime(2026, 10, 19, h, m, tzinfo=NY))


def test_parse_chart():
    c = yahoo.parse_chart(json.loads(TSLA.read_text(encoding="utf-8")))
    assert c.symbol == "TSLA" and c.prev_close == 354.72
    assert list(c.bars.columns) == yahoo.BAR_COLUMNS
    assert f"{c.bars['ts'].iloc[0]:%H:%M}" == "09:30" and str(c.bars["ts"].iloc[0].tz) == "America/New_York"


def test_parse_bad_document():
    assert yahoo.parse_chart({}) is None
    assert yahoo.parse_chart({"chart": {"result": []}}) is None


def test_replay_shows_only_closed_bars():
    c = replay(10, 15).chart("TSLA")
    assert f"{c.bars['ts'].iloc[-1]:%H:%M}" == "10:10"  # the 10:10 bar closed at 10:15
    assert c.price == pytest.approx(364.18, abs=0.01)
    assert c.change_pct == pytest.approx(2.67, abs=0.01)
    assert len(replay(10, 12).chart("TSLA").bars) == 8  # 10:10 still forming


def test_replay_wall_and_unknowns():
    assert replay(10, 15).chart("AAPL") is not None
    assert replay(10, 15).chart("SPY") is None  # not in the recording
    assert replay(10, 15).chart("TSLA", "3mo", "1d") is None
    assert len(replay(10, 15).chart("TSLA", "60d", "5m").bars) > 4000
    assert yahoo.bars("SPY", src=replay(10, 15)).empty


def test_quote_from_replay():
    q = yahoo.quote(["tsla", "SPY"], src=replay(10, 15))
    assert q["TSLA"].price == pytest.approx(364.18, abs=0.01) and q["SPY"].price is None


def mock_live(handler):
    return yahoo.LiveYahoo(httpx.Client(transport=httpx.MockTransport(handler)), pause=0)


def test_live_falls_back_to_query1_and_caches():
    calls = []
    doc = json.loads(TSLA.read_text(encoding="utf-8"))

    def handler(req):
        calls.append(req.url.host)
        return httpx.Response(429) if req.url.host.startswith("query2") else httpx.Response(200, json=doc)

    src = mock_live(handler)
    assert src.chart("TSLA").price == 366.07
    assert calls == ["query2.finance.yahoo.com", "query1.finance.yahoo.com"]
    src.chart("TSLA")
    assert len(calls) == 2  # served from the cache


def test_live_not_found_is_none_without_retry():
    calls = []

    def handler(req):
        calls.append(req.url.host)
        return httpx.Response(404)

    assert mock_live(handler).chart("NOPE") is None
    assert len(calls) == 1


def test_live_network_error_is_none():
    def handler(req):
        raise httpx.ConnectError("offline")

    assert mock_live(handler).chart("TSLA") is None


def test_user_agent():
    assert yahoo.live().client.headers["User-Agent"].startswith("gatekeeper/0.1")
