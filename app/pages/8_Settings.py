"""Settings: your trading rules (trader/config.json), the dashboard's own settings (.env), and
diagnostics. Every save backs up the old file first; `paper` can't be changed here."""

from __future__ import annotations

import subprocess
import sys
from collections import Counter

import pandas as pd
import streamlit as st
from pydantic import ValidationError
from sqlmodel import col, select

from app.components.page import Page, footer, setup_page
from gatekeeper import config_edit, envfile
from gatekeeper.db import session
from gatekeeper.settings import ROOT, get_settings
from gatekeeper.tables import SkillRun
from worker.jobs import JOBS

page = setup_page("Settings", "⚙️")
st.title("Settings")


def rules(p: Page) -> None:
    st.subheader("Your trading rules (trader/config.json)")
    path = p.trader_dir / "config.json"
    old = config_edit.load(path)
    if p.mode == "replay":
        st.caption("Replay mode: this edits the replay workspace's copy, not your live trader/config.json.")
    if not old:
        st.info(
            "No trader/config.json yet. Start from the skills' example: /trader-budget in Claude chat "
            "sets it up with you."
        )
        return
    paper = bool(old.get("paper", True))
    st.toggle(
        "Paper account",
        value=paper,
        disabled=True,
        key="cfg_paper",
        help="Read-only. Going live is your own decision, made by editing trader/config.json yourself.",
    )
    with st.form("cfg_form"):
        a, b, c, d = st.columns(4)
        v = {
            "budget": a.number_input(
                "Budget ($)", value=float(old.get("budget", 5000)), min_value=0.0, step=100.0
            ),
            "cash_buffer_pct": b.number_input(
                "Cash buffer (%)", value=float(old.get("cash_buffer_pct", 10)), min_value=0.0, max_value=100.0
            ),
            "max_loss_per_trade_usd": c.number_input(
                "Max loss / trade ($)", value=float(old.get("max_loss_per_trade_usd", 50)), min_value=0.0
            ),
            "max_daily_loss_usd": d.number_input(
                "Max loss / day ($)", value=float(old.get("max_daily_loss_usd", 150)), min_value=0.0
            ),
            "max_trades_per_day": int(
                a.number_input(
                    "Trades / day", value=int(old.get("max_trades_per_day", 3)), min_value=1, step=1
                )
            ),
            "max_orders_per_day": int(
                b.number_input(
                    "Orders / day", value=int(old.get("max_orders_per_day", 10)), min_value=1, step=1
                )
            ),
            "min_reward_risk": c.number_input(
                "Min reward : risk", value=float(old.get("min_reward_risk", 1.0)), min_value=0.1, step=0.1
            ),
            "max_position_pct": d.number_input(
                "Max position (%)",
                value=float(old.get("max_position_pct", 75)),
                min_value=1.0,
                max_value=100.0,
            ),
            "max_order_usd": a.number_input(
                "Max order ($)", value=float(old.get("max_order_usd", 4000)), min_value=0.0, step=100.0
            ),
            "min_order_usd": b.number_input(
                "Min order ($)", value=float(old.get("min_order_usd", 5)), min_value=0.0
            ),
            "no_entries_before": c.text_input(
                "No entries before (NY)", value=old.get("no_entries_before") or ""
            ),
            "no_entries_after": d.text_input(
                "No entries after (NY)", value=old.get("no_entries_after") or ""
            ),
            "flat_by": a.text_input("Flat by (NY)", value=old.get("flat_by", "15:55")),
            "blocked": [
                t
                for t in b.text_input("Blocked tickers", value=", ".join(old.get("blocked") or [])).split(",")
                if t.strip()
            ],
            "require_stop": c.checkbox("Require a stop", value=bool(old.get("require_stop", True))),
            "pdt_guard": d.checkbox("PDT guard", value=bool(old.get("pdt_guard", False))),
        }
        preview = st.form_submit_button("Preview changes")
    if preview:
        new = {**old, **{k: (val or None) if k.startswith("no_entries") else val for k, val in v.items()}}
        st.session_state["cfg_new"] = new
    new = st.session_state.get("cfg_new")
    if not new:
        return
    try:
        clean = config_edit.validate(new)
    except ValidationError as e:
        for err in e.errors():
            st.error(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}")
        return
    changes = config_edit.diff(old, clean)
    if not changes:
        st.caption("No changes.")
        return
    st.markdown("**Changes**")
    st.dataframe(
        pd.DataFrame([{"Setting": k, "Now": str(a), "New": str(b)} for k, a, b in changes]), hide_index=True
    )
    if st.button("Save (backs up the current file first)", key="cfg_save"):
        try:
            backup, done = config_edit.save(path, clean, p.settings.resolve(p.settings.backups_dir))
        except config_edit.PaperChangeRefused as e:
            st.error(str(e))
            return
        st.session_state.pop("cfg_new", None)
        st.success(f"Saved {len(done)} change(s). Backup: {backup}")


GATE_FIELDS = [k for k in type(get_settings()).model_fields if k.startswith("gate_")]


def dashboard(p: Page) -> None:
    st.subheader("Dashboard settings (.env)")
    s = p.settings
    st.caption(
        f"Writes {s.resolve(s.env_path)} (backed up first). Keys and tokens are never shown or written here. "
        "Restart the worker and the dashboard to apply."
    )
    with st.form("env_form"):
        a, b, c = st.columns(3)
        tickers = a.text_input("Core tickers", value=",".join(s.core_tickers))
        awake = b.text_input("Awake hours (IST)", value=s.awake_ist, help="e.g. 18:30-23:30 or 18:30-01:30")
        notify = c.selectbox(
            "Notifications",
            ["none", "toast", "telegram"],
            index=["none", "toast", "telegram"].index(s.notify),
        )
        off = a.multiselect(
            "Jobs switched off", list(JOBS), default=[j for j in s.disabled_jobs if j in JOBS]
        )
        full = b.checkbox("Universe-wide ORB scan at 10:15", value=s.full_universe_orb)
        with st.expander("Go / No-Go thresholds"):
            cols = st.columns(3)
            gates = {
                k: cols[i % 3].number_input(
                    k.removeprefix("gate_").replace("_", " "), value=float(getattr(s, k))
                )
                for i, k in enumerate(GATE_FIELDS)
            }
        save = st.form_submit_button("Save to .env")
    if save:
        values = {
            "CORE_TICKERS": tickers.replace(" ", ""),
            "AWAKE_IST": awake.strip(),
            "NOTIFY": notify,
            "DISABLED_JOBS": ",".join(off),
            "FULL_UNIVERSE_ORB": str(full).lower(),
        }
        for k, val in gates.items():
            if val != float(getattr(s, k)):
                values[k.upper()] = f"{int(val)}" if float(val).is_integer() else f"{val}"
        try:
            backup = envfile.update(s.resolve(s.env_path), values, s.resolve(s.backups_dir))
        except ValueError as e:
            st.error(str(e))
            return
        get_settings.cache_clear()
        st.success(
            f"Saved. Backup: {backup or 'none (new file)'}. Restart the worker and the dashboard to apply."
        )


def diagnostics(p: Page) -> None:
    st.subheader("Diagnostics")
    with session(p.engine) as s:
        runs = s.exec(
            select(SkillRun).where(SkillRun.mode == p.mode).order_by(col(SkillRun.id).desc()).limit(200)
        ).all()
    commit = (
        subprocess.run(
            ["git", "-C", str(p.settings.skills_path), "log", "-1", "--format=%h %cs %s"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        or "unknown"
    )
    st.markdown(f"**Pinned skills:** `{commit}` · mode **{p.mode}** · {len(runs)} recent skill runs")
    errors = [r for r in runs if r.status == "error"]
    if errors:
        last = {}
        for r in errors:
            last.setdefault(r.tool, r)
        st.markdown("**Last error per tool**")
        st.dataframe(
            pd.DataFrame(
                [
                    {"Tool": t, "At (UTC)": f"{r.started_at:%Y-%m-%d %H:%M}", "Message": r.message}
                    for t, r in last.items()
                ]
            ),
            hide_index=True,
        )
    else:
        st.caption("No skill errors in the recent runs.")
    if runs:
        counts = Counter((r.tool, r.status) for r in runs)
        st.dataframe(
            pd.DataFrame([{"Tool": t, "Status": st_, "Runs": n} for (t, st_), n in sorted(counts.items())]),
            hide_index=True,
        )
    if st.button(
        "Run the contract self-test",
        key="selftest",
        help="Re-checks that the pinned skills still print what Gatekeeper expects (about 40 s).",
    ):
        with st.spinner("Running tests/test_models_contract.py..."):
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    "tests/test_models_contract.py",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
        last_line = (proc.stdout.strip().splitlines() or ["no output"])[-1]
        (st.success if proc.returncode == 0 else st.error)(f"Contract self-test: {last_line}")


tab_r, tab_d, tab_x = st.tabs(["Trading rules", "Dashboard", "Diagnostics"])
with tab_r:
    rules(page)
with tab_d:
    dashboard(page)
with tab_x:
    diagnostics(page)
footer()
