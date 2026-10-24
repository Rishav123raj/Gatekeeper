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

    # Go / No-Go gate thresholds (gate_* fields) are added in Phase 5.

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
