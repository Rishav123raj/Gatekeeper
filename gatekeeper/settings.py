"""Dashboard settings, read from the environment and `.env`.

Trading rules (budget, max loss, entry window, flat-by) are NOT here: they live in
the skills' own `trader/config.json`, so Claude chat and Gatekeeper share them.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    mode: Literal["live", "replay"] = Field("live", validation_alias="GATEKEEPER_MODE")
    skills_dir: Path = Path("vendor/day-trader-skill")
    project_root: Path = Path(".")
    db_url: str = "sqlite:///data/gatekeeper.db"
    sec_user_agent: str = ""

    core_tickers: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["TSLA", "NVDA", "AMD", "AAPL", "MSFT", "META", "AMZN", "GOOGL", "SPY", "QQQ"]
    )
    awake_ist: str = "18:30-23:30"
    full_universe_orb: bool = False

    # Worker: jobs to switch off (e.g. DISABLED_JOBS=pelosi,analyst_watchlist), and how long a job
    # waits for another run to finish writing trader/ (a whole-universe scan holds it ~3 minutes).
    disabled_jobs: Annotated[list[str], NoDecode] = Field(default_factory=list)
    worker_lock_timeout: float = 300

    notify: Literal["none", "toast", "telegram"] = "none"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Replay mode: the recorded day shipped with the skills' test fixtures, run in its own folder.
    replay_date: str = "2026-10-19"
    replay_workspace: Path = Path("replay/workspace")

    # Go / No-Go gate thresholds (plan Section 9). Override any in .env, e.g. GATE_BREADTH_WARN_PCT=15.
    gate_window_warn_min: int = 15  # WARN when the entry window closes within this many minutes
    gate_daily_loss_warn_pct: float = 66.0  # WARN when this share of the daily loss limit is used
    gate_trades_warn_left: int = 1  # WARN when this many trades (or fewer) are left today
    gate_pdt_warn: int = 2  # WARN at this many day trades in 5 business days (FAIL at 3)
    gate_vix_spike_pct: float = 10.0  # market context WARN: VIX up this much today
    gate_breadth_warn_pct: float = 10.0  # WARN under this share of charts breaking out
    gate_form_trades: int = 5  # recent form looks at the last N journal trades / decisions
    gate_form_r_warn: float = -3.0  # WARN when the last N trades sum to this many R or less
    gate_form_broken_warn: int = 2  # WARN when rules were broken in this many of the last N decisions
    gate_entry_stale_bars: int = 1  # WARN when the trigger is more than this many bars old
    gate_news_hours: int = 24  # news gates look back this far
    gate_earnings_warn_sessions: int = 3  # WARN when the next report is within this many sessions
    gate_min_risk_pct: float = 0.3  # WARN when the stop is closer than this share of the price
    gate_rr_warn_margin_pct: float = 10.0  # WARN when reward:risk is within this % above the minimum
    gate_tm_neither_warn_pct: float = 40.0  # WARN when more replays than this hit neither side
    gate_history_min_fires: int = 15  # WARN when the rule fired fewer times than this in history
    gate_readiness_store_min: int = 5  # store an unchanged evaluation at most every N minutes

    @field_validator("core_tickers", mode="before")
    @classmethod
    def _split_tickers(cls, v: object) -> object:
        if isinstance(v, str):
            return [t.strip().upper() for t in v.split(",") if t.strip()]
        return v

    @field_validator("disabled_jobs", mode="before")
    @classmethod
    def _split_jobs(cls, v: object) -> object:
        if isinstance(v, str):
            return [j.strip() for j in v.split(",") if j.strip()]
        return v

    @field_validator("awake_ist")
    @classmethod
    def _check_awake(cls, v: str) -> str:
        start, sep, end = v.partition("-")
        if not sep or len(start.split(":")) != 2 or len(end.split(":")) != 2:
            raise ValueError("AWAKE_IST must look like 18:30-23:30")
        return v

    def resolve(self, p: Path) -> Path:
        """A configured path, made absolute against the project folder."""
        return p if p.is_absolute() else (ROOT / p).resolve()

    @property
    def skills_path(self) -> Path:
        return self.resolve(self.skills_dir)

    @property
    def root_path(self) -> Path:
        return self.resolve(self.project_root)

    @property
    def trader_path(self) -> Path:
        return self.root_path / "trader"


@lru_cache
def get_settings() -> Settings:
    return Settings()
