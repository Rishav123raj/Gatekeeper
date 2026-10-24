"""Bars and quotes for the dashboard's own charts and tiles.

The skills fetch their own data and don't hand back their bars, so the dashboard reads
Yahoo's v8 chart endpoint itself, politely: one request at a time, half a second apart,
a 60-second cache, query2 then query1, and its own user agent. Free and unofficial: it
can lag or refuse, and then a series is simply unavailable ("n/a"), never an error.

In replay it reads the recorded charts instead (the 234-ticker wall and TSLA's charts
for 2026-10-19), cut at the replay time so only bars that had closed by then show.
"""

from __future__ import annotations

import gzip
import json
import logging
import threading
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import httpx
import pandas as pd

from gatekeeper.clock import NY, as_ny

log = logging.getLogger("gatekeeper.yahoo")

USER_AGENT = "gatekeeper/0.1 (personal dashboard; https://github.com/Rishav123raj/Gatekeeper)"
HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")
TIMEOUT = 10.0
PAUSE = 0.5
CACHE_TTL = 60.0
BAR_COLUMNS = ["ts", "open", "high", "low", "close", "volume"]
INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60, "1h": 60, "1d": 24 * 60}


@dataclass
class Chart:
    symbol: str
    bars: pd.DataFrame  # ts (New York, aware), open, high, low, close, volume
    prev_close: float | None = None
    price: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def change_pct(self) -> float | None:
        if self.price is None or not self.prev_close:
            return None
        return round(100 * (self.price / self.prev_close - 1), 2)


def empty_bars() -> pd.DataFrame:
    return pd.DataFrame(columns=BAR_COLUMNS)


def parse_chart(doc: dict[str, Any]) -> Chart | None:
    """A v8 chart document as a Chart (bars with a missing close are dropped)."""
    try:
        r = doc["chart"]["result"][0]
    except (KeyError, IndexError, TypeError):
        return None
    meta = r.get("meta", {}) or {}
    ts = r.get("timestamp") or []
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    df = (
        pd.DataFrame(
            {
                "ts": pd.to_datetime(ts, unit="s", utc=True).tz_convert(NY),
                "open": q.get("open", [None] * len(ts)),
                "high": q.get("high", [None] * len(ts)),
                "low": q.get("low", [None] * len(ts)),
                "close": q.get("close", [None] * len(ts)),
                "volume": q.get("volume", [None] * len(ts)),
            }
        )
        if ts
        else empty_bars()
    )
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    price = meta.get("regularMarketPrice")
    if price is None and len(df):
        price = float(df["close"].iloc[-1])
    prev = meta.get("chartPreviousClose") if meta.get("range") == "1d" else meta.get("previousClose")
    return Chart(str(meta.get("symbol") or ""), df, prev or meta.get("previousClose"), price, meta)


class Source(Protocol):
    def chart(self, symbol: str, range_: str = "1d", interval: str = "5m") -> Chart | None: ...


# --- live ------------------------------------------------------------------------------------


class LiveYahoo:
    """Yahoo's free chart endpoint, one request at a time, cached for a minute."""

    def __init__(self, client: httpx.Client | None = None, ttl: float = CACHE_TTL, pause: float = PAUSE):
        self.client = client or httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
        self.ttl, self.pause = ttl, pause
        self._cache: dict[tuple[str, str, str], tuple[float, Chart | None]] = {}
        self._lock = threading.Lock()
        self._last = 0.0

    def chart(self, symbol: str, range_: str = "1d", interval: str = "5m") -> Chart | None:
        key = (symbol.upper(), range_, interval)
        with self._lock:
            hit = self._cache.get(key)
            if hit and _time.monotonic() - hit[0] < self.ttl:
                return hit[1]
            chart = self._fetch(*key)
            self._cache[key] = (_time.monotonic(), chart)
            return chart

    def _fetch(self, symbol: str, range_: str, interval: str) -> Chart | None:
        params = {"range": range_, "interval": interval, "includePrePost": "false"}
        for host in HOSTS:
            wait = self.pause - (_time.monotonic() - self._last)
            if wait > 0:
                _time.sleep(wait)
            self._last = _time.monotonic()
            try:
                r = self.client.get(f"{host}/v8/finance/chart/{symbol}", params=params)
            except httpx.HTTPError as e:
                log.warning("yahoo %s %s: %s", symbol, host, e)
                continue
            if r.status_code == 200:
                return parse_chart(r.json())
            log.warning("yahoo %s %s: HTTP %s", symbol, host, r.status_code)
            if r.status_code not in (429,) and r.status_code < 500:
                return None  # 404 etc.: another host won't know it either
        return None


@lru_cache(maxsize=1)
def live() -> LiveYahoo:
    return LiveYahoo()


# --- replay ----------------------------------------------------------------------------------


@lru_cache(maxsize=4)
def _load(path: str) -> dict[str, Any]:
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


class ReplayYahoo:
    """The recorded charts of 2026-10-19, showing only bars that had closed by `now`."""

    def __init__(self, fixtures: Path, now: datetime):
        self.fixtures = Path(fixtures)
        self.now = as_ny(now)

    def _doc(self, symbol: str, range_: str) -> dict[str, Any] | None:
        f = self.fixtures
        if range_ == "60d":
            return (
                _load(str(f / "trader-timemachine" / f"{symbol}-60d5m.json.gz")) if symbol == "TSLA" else None
            )
        if range_ != "1d":
            return None
        if symbol == "TSLA":
            return _load(str(f / "trader-entry" / "TSLA-2026-10-19-5m.json"))
        return _load(str(f / "trader-scanner" / "wall5m-2026-10-19.json.gz")).get(symbol)

    def chart(self, symbol: str, range_: str = "1d", interval: str = "5m") -> Chart | None:
        symbol = symbol.upper()
        try:
            doc = self._doc(symbol, range_) if interval == "5m" else None
        except OSError:
            doc = None
        chart = parse_chart(doc) if doc else None
        if chart is None:
            return None
        step = timedelta(minutes=INTERVAL_MINUTES[interval])
        bars = chart.bars[chart.bars["ts"] + step <= self.now].reset_index(drop=True)
        price = float(bars["close"].iloc[-1]) if len(bars) else None
        return Chart(symbol, bars, chart.prev_close, price, chart.meta)


def source(mode: str, now: datetime | None = None, fixtures: Path | None = None) -> Source:
    if mode == "replay":
        from gatekeeper.settings import get_settings

        return ReplayYahoo(
            fixtures or get_settings().skills_path / "tests" / "fixtures", now or datetime.now(NY)
        )
    return live()


def bars(symbol: str, range_: str = "1d", interval: str = "5m", *, src: Source | None = None) -> pd.DataFrame:
    chart = (src or live()).chart(symbol, range_, interval)
    return chart.bars if chart else empty_bars()


@dataclass
class Quote:
    symbol: str
    price: float | None
    prev_close: float | None
    change_pct: float | None
    time: datetime | None


def quote(symbols: list[str], *, src: Source | None = None) -> dict[str, Quote]:
    out = {}
    for sym in symbols:
        c = (src or live()).chart(sym, "1d", "5m")
        t = c.bars["ts"].iloc[-1].to_pydatetime() if c is not None and len(c.bars) else None
        out[sym.upper()] = Quote(
            sym.upper(), c.price if c else None, c.prev_close if c else None, c.change_pct if c else None, t
        )
    return out
