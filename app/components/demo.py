"""The public demo: each browser session gets its own replay database, workspace and settings.

Turned on with PUBLIC_DEMO=true (for a hosted copy anyone can open). Visitors never share
state, never reach live data, and their folders are removed after DEMO_TTL_HOURS.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import streamlit as st
from sqlalchemy.engine import Engine

from gatekeeper.db import init_db, make_engine
from gatekeeper.settings import ROOT, Settings


def root(settings: Settings) -> Path:
    return Path(settings.demo_root) if settings.demo_root else Path(tempfile.gettempdir()) / "gatekeeper-demo"


def cleanup(base: Path, ttl_hours: float, now: float | None = None) -> list[Path]:
    """Removes visitor folders older than the TTL. Returns what it removed."""
    if not base.is_dir():
        return []
    cutoff = (now or time.time()) - ttl_hours * 3600
    gone = [d for d in base.iterdir() if d.is_dir() and d.stat().st_mtime < cutoff]
    for d in gone:
        shutil.rmtree(d, ignore_errors=True)
    return gone


def visitor_settings(settings: Settings, folder: Path) -> Settings:
    """The app's settings pointed at one visitor's folder: replay only, nothing shared."""
    return settings.model_copy(
        update={
            "mode": "replay",
            "db_url": f"sqlite:///{(folder / 'demo.db').as_posix()}",
            "replay_workspace": folder / "ws",
            "env_path": folder / "demo.env",
            "backups_dir": folder / "backups",
            "notify": "none",
        }
    )


@st.cache_resource(show_spinner="Fetching the day-trader skills...")
def ensure_skills(skills_path: Path) -> str:
    """Hosts that clone without submodules get the pinned skills on first use."""
    if (skills_path / "trader-entry").is_dir():
        return "present"
    proc = subprocess.run(
        ["git", "submodule", "update", "--init", "--depth", "1"], cwd=ROOT, capture_output=True, text=True
    )
    return "fetched" if proc.returncode == 0 else f"failed: {proc.stderr.strip()[-200:]}"


def session_copy(settings: Settings) -> tuple[Settings, Engine]:
    """This browser session's settings and database, made on its first page view."""
    if "demo_settings" not in st.session_state:
        ensure_skills(settings.skills_path)
        base = root(settings)
        cleanup(base, settings.demo_ttl_hours)
        folder = base / uuid.uuid4().hex
        folder.mkdir(parents=True)
        mine = visitor_settings(settings, folder)
        st.session_state["demo_settings"] = mine
        st.session_state["demo_engine"] = init_db(make_engine(mine.db_url))
    return st.session_state["demo_settings"], st.session_state["demo_engine"]
