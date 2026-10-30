"""What every page shares: config, the sidebar (mode, replay time, worker health), the clock
bar, and the footer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import streamlit as st
from sqlalchemy.engine import Engine

from app import state
from app.components import demo
from app.components.clock_bar import clock_bar
from gatekeeper import store, yahoo
from gatekeeper.clock import fmt_dual
from gatekeeper.db import get_engine, session
from gatekeeper.runner import SkillRunner
from gatekeeper.settings import Settings, get_settings
from worker.jobs import JobContext

REPLAY_FROM, REPLAY_TO = time(7, 0), time(16, 10)
FOOTER = "Data: Yahoo (free, delayed, unofficial) · Not financial advice."


@dataclass
class Page:
    settings: Settings
    engine: Engine
    mode: str
    now: datetime  # New York

    @property
    def today(self) -> str:
        return f"{self.now:%Y-%m-%d}"

    @property
    def trader_dir(self) -> Path:
        s = self.settings
        return (s.resolve(s.replay_workspace) if self.mode == "replay" else s.root_path) / "trader"

    def job_context(self) -> JobContext:
        """A worker context for running a job from the page ("Run scan now")."""
        from worker.scheduler import live_context, replay_context

        if self.mode == "live":
            return live_context(self.settings, self.engine)
        ctx, _ = replay_context(self.settings, self.engine, self.now.date(), self.now.time(), fresh=False)
        return ctx

    def runner(self, job: str = "dashboard") -> SkillRunner:
        """A skill runner at the page's clock (the replay time in replay), logging each run."""
        return self.job_context().runner(job)

    def yahoo(self) -> yahoo.Source:
        """Bars for charts: live Yahoo, or the recordings cut at the replay time."""
        return self.job_context().yahoo()


def setup_page(title: str, icon: str = "🛡️") -> Page:
    st.set_page_config(page_title=f"{title} · Gatekeeper", page_icon=icon, layout="wide")
    settings = get_settings()
    if settings.public_demo:
        settings, engine = demo.session_copy(settings)
    else:
        engine = get_engine()
    sidebar(settings, engine)
    clock_bar()
    return Page(settings, engine, state.mode(), state.now())


def sidebar(settings: Settings, engine: Engine) -> None:
    with st.sidebar:
        st.markdown("### 🛡️ Gatekeeper")
        st.caption("Every trade has to earn its way in.")
        if settings.public_demo:
            st.info(
                "**Public demo.** A recorded trading day (Mon 19 Oct 2026), played back without the "
                "internet. Everything you do stays in your own copy, removed after a few hours."
            )
        else:
            choice = st.segmented_control(
                "Mode",
                ["LIVE", "REPLAY"],
                default=state.mode().upper(),
                key="mode_choice",
                help="REPLAY plays back the recorded day (Mon 2026-10-19) without the internet.",
            )
            st.session_state["mode"] = (choice or state.mode().upper()).lower()

        if state.mode() == "replay":
            t = st.slider(
                "Replay time (New York)",
                min_value=REPLAY_FROM,
                max_value=REPLAY_TO,
                value=state.replay_time(),
                step=timedelta(minutes=5),
                format="HH:mm",
                key="replay_slider",
            )
            st.session_state["replay_time"] = t
            st.caption(f"{state.replay_day():%a %d %b %Y} · {fmt_dual(state.now())}")
            replay_sync(settings, engine)
        else:
            worker_dot(engine)


def replay_sync(settings: Settings, engine: Engine) -> None:
    """Fast-forwards the recorded day to the slider's time (the dashboard is the worker in replay)."""
    from worker.scheduler import sync_replay

    target = state.now()
    if st.session_state.get("replay_synced") == target:
        return
    with st.spinner(f"Replaying the day up to {target:%H:%M} NY..."):
        msg = sync_replay(settings, engine, target)
    st.session_state["replay_synced"] = target
    st.toast(msg)


def worker_dot(engine: Engine) -> None:
    with session(engine) as s:
        beats = store.heartbeats(s, "live")
    last = max((h.last_run_at for h in beats if h.last_run_at), default=None)
    if last is None:
        st.markdown(":red[●] Worker: never ran")
        st.caption("Start it in another window: `uv run python -m worker`")
        return
    age = datetime.now(UTC) - (last if last.tzinfo else last.replace(tzinfo=UTC))
    color = "green" if age < timedelta(minutes=3) else "orange" if age < timedelta(minutes=15) else "red"
    mins = int(age.total_seconds() // 60)
    st.markdown(f":{color}[●] Worker: last run {mins} min ago")
    if color != "green":
        st.caption("Is it running? `uv run python -m worker`")


def footer() -> None:
    st.divider()
    st.caption(FOOTER)
