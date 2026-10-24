"""Validate a Gatekeeper phase end to end and print PASS / FAIL per check.

    uv run python scripts/validate.py            # every phase built so far (offline)
    uv run python scripts/validate.py --phase 1  # one phase
    uv run python scripts/validate.py --live     # also the live smoke checks (internet)

Exit code 0 when every check passed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "day-trader-skill"


def sh(*cmd: str, cwd: Path = ROOT) -> tuple[bool, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (proc.stdout + proc.stderr).strip().splitlines()
    return proc.returncode == 0, (out[-1] if out else "")


def pytest(*files: str) -> Callable[[], tuple[bool, str]]:
    return lambda: sh(sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *files)


# --- Phase 0 ---------------------------------------------------------------------------------


def check_lint():
    return sh(sys.executable, "-m", "ruff", "check", ".")


def check_upstream():
    return sh(sys.executable, "-I", "-m", "unittest", "discover", "-s", "tests", cwd=VENDOR)


def check_home_page():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "app" / "Home.py"), default_timeout=30).run()
    if at.exception:
        return False, str(at.exception[0].value)
    clock = next((m.value for m in at.markdown if "IST" in m.value), "")
    return bool(clock) and at.title[0].value == "Gatekeeper", clock.replace("**", "")


# --- Phase 1 ---------------------------------------------------------------------------------


def check_contracts_unchanged():
    """Regenerate the contracts in a temp folder and compare them with the committed ones."""
    import json

    from gatekeeper.contracts import generate
    from gatekeeper.settings import get_settings

    with tempfile.TemporaryDirectory() as tmp:
        fresh = generate(Path(tmp), get_settings().skills_path)
    committed = ROOT / "tests" / "contracts"
    changed = [
        n for n, d in fresh.items() if json.loads((committed / f"{n}.json").read_text(encoding="utf-8")) != d
    ]
    if changed:
        return False, "changed: " + ", ".join(changed)
    return True, f"{len(fresh)} contracts identical to tests/contracts/"


def check_replay_trade():
    """The documented TSLA trade through the wrappers, in a throwaway replay workspace."""
    from gatekeeper.replay import prepare_workspace
    from gatekeeper.runner import SkillRunner
    from gatekeeper.settings import get_settings
    from gatekeeper.skills import budget, entry, exit, risk, scanner, timemachine

    with tempfile.TemporaryDirectory() as tmp:
        ctx = prepare_workspace(datetime(2026, 10, 19, 10, 15), Path(tmp), get_settings().skills_path)
        r = SkillRunner.from_settings(replay=ctx)
        scan, _ = scanner.orb(runner=r)
        e, _ = entry.check("TSLA", write=True, runner=r)
        p, _ = exit.plan(stop="or-mid", target="1R", runner=r)
        tm, _ = timemachine.run(runner=r)
        s, _ = budget.size(runner=r)
        k, res = risk.check(runner=r)
    got = {
        "orb hits": len(scan.hits),
        "trigger": e.trigger.price,
        "stop/target": (p.stop, p.target),
        "odds": (tm.mc.p_target, tm.mc.p_stop, tm.mc.p_neither),
        "shares/max loss": (s.sizing.qty, s.sizing.max_loss),
        "risk": (res.status, k.results[0].verdict),
    }
    want = {
        "orb hits": 41,
        "trigger": 364.18,
        "stop/target": (358.32, 370.04),
        "odds": (0.2938, 0.2548, 0.4514),
        "shares/max loss": (8, 46.88),
        "risk": ("ok", "PASS"),
    }
    bad = [f"{k}: {got[k]} != {want[k]}" for k in want if got[k] != want[k]]
    return (
        (False, "; ".join(bad))
        if bad
        else (True, "41 hits · 364.18 · 358.32/370.04 · 29.4/25.5/45.1 % · 8 sh $46.88 · PASS")
    )


def check_calendar():
    from datetime import date

    from gatekeeper.clock import market_day, session_phase

    thanks = market_day(date(2026, 11, 26))
    early = market_day(date(2026, 11, 27))
    ok = (
        thanks is not None
        and session_phase(datetime(2026, 11, 26, 10, 15), day=thanks) == "closed"
        and early is not None
        and session_phase(datetime(2026, 11, 27, 12, 45), day=early) == "late"
    )
    return ok, "Thanksgiving closed; Nov 27 early close cuts entries at 12:30"


def check_live_smoke():
    from gatekeeper.clock import fmt_dual, now_ny
    from gatekeeper.skills import alerts, entry

    c, r1 = alerts.clock()
    e, r2 = entry.check("SPY")
    if c is None or e is None:
        return False, f"clock {r1.status} {r1.message} / entry {r2.status} {r2.message}"
    return True, f"{fmt_dual(now_ny())}: NYSE {'open' if c.open else 'closed'} ({c.reason}); SPY {e.status}"


# --- Phase 2 ---------------------------------------------------------------------------------


def check_worker_replay():
    """The worker CLI fast-forwards 10:10 to 10:16 of the recorded day into a throwaway database."""
    from sqlmodel import select

    from gatekeeper import store, tables
    from gatekeeper.db import init_db, make_engine, session

    with tempfile.TemporaryDirectory() as tmp:
        db = f"sqlite:///{(Path(tmp) / 'v.db').as_posix()}"
        ok, last = sh(
            sys.executable,
            "-m",
            "worker",
            "--replay",
            "--from",
            "10:10",
            "--to",
            "10:16",
            "--db",
            db,
            "--quiet",
        )
        if not ok:
            return False, last
        engine = init_db(make_engine(db))
        with session(engine) as s:
            sig = store.latest_entry(s, "replay", "TSLA", "2026-10-19")
            scan = store.latest_scan(s, "replay", "orb")
            runs = len(s.exec(select(tables.SkillRun)).all())
        engine.dispose()
    got = (sig.status, sig.trigger_price, sig.checked_ny[11:16], scan.hits_count)
    want = ("triggered", 364.18, "10:15", 41)
    return got == want, f"TSLA {got[0]} at {got[1]} ({got[2]}), ORB {got[3]} hits, {runs} skill runs logged"


def check_schedule():
    from datetime import datetime, time

    from gatekeeper.clock import NY
    from worker.jobs import JOBS, SCHEDULE
    from worker.scheduler import fire_times

    d = datetime(2026, 10, 19).date()
    t0, t1 = datetime.combine(d, time(0, 0), NY), datetime.combine(d, time(23, 59), NY)
    orb = fire_times("orb_scan", t0, t1)
    ok = set(JOBS) == set(SCHEDULE) and len(orb) == 25 and f"{orb[0]:%H:%M}" == "09:50"
    return ok, f"{len(JOBS)} jobs; ORB 25 times a day from 09:50 NY (19:20 IST)"


def check_worker_live_once():
    with tempfile.TemporaryDirectory() as tmp:
        db = f"sqlite:///{(Path(tmp) / 'live.db').as_posix()}"
        ok, last = sh(sys.executable, "-m", "worker", "--once", "clock", "--db", db, "--quiet")
        if not ok:
            return False, last
        from gatekeeper import store
        from gatekeeper.db import init_db, make_engine, session

        engine = init_db(make_engine(db))
        with session(engine) as s:
            (hb,) = store.heartbeats(s, "live")
        engine.dispose()
    return hb.last_status == "ok", f"clock job: {hb.last_status}, {hb.last_detail}"


# --- Phase 3 ---------------------------------------------------------------------------------


def check_server():
    """Starts the dashboard on a spare port and asks it for its health and its pages."""
    import httpx

    port = 8599
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app/Home.py", "--server.port", str(port)],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(60):
            try:
                if httpx.get(f"http://127.0.0.1:{port}/_stcore/health", timeout=1).text == "ok":
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        else:
            return False, "the server did not answer within 30 s"
        pages = httpx.get(f"http://127.0.0.1:{port}/", timeout=5).status_code
        return pages == 200, f"health ok, http://127.0.0.1:{port}/ answered {pages}"
    finally:
        proc.terminate()
        proc.wait(10)


def check_live_home():
    """The Home page in live mode with real index tiles (a throwaway database)."""
    import os

    from streamlit.testing.v1 import AppTest

    from gatekeeper.db import get_engine
    from gatekeeper.settings import get_settings

    with tempfile.TemporaryDirectory() as tmp:
        old = {k: os.environ.get(k) for k in ("GATEKEEPER_MODE", "DB_URL")}
        os.environ.update(GATEKEEPER_MODE="live", DB_URL=f"sqlite:///{(Path(tmp) / 'h.db').as_posix()}")
        get_settings.cache_clear()
        get_engine.cache_clear()
        try:
            at = AppTest.from_file(str(ROOT / "app" / "Home.py"), default_timeout=120).run()
            tiles = {m.label: m.value for m in at.metric}
        finally:
            get_engine().dispose()
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
            get_settings.cache_clear()
            get_engine.cache_clear()
    if at.exception:
        return False, str(at.exception[0].value)
    real = {k: v for k, v in tiles.items() if v != "n/a"}
    return len(real) == 4, " · ".join(f"{k} {v}" for k, v in tiles.items())


# --- Phase 4 ---------------------------------------------------------------------------------


def check_live_trade_lab():
    """The Trade Lab live: a real TSLA chart on its own session's day, and a live entry status."""
    import json
    import os

    from streamlit.testing.v1 import AppTest

    from gatekeeper.db import get_engine
    from gatekeeper.settings import get_settings

    with tempfile.TemporaryDirectory() as tmp:
        old = {k: os.environ.get(k) for k in ("GATEKEEPER_MODE", "DB_URL")}
        os.environ.update(GATEKEEPER_MODE="live", DB_URL=f"sqlite:///{(Path(tmp) / 't.db').as_posix()}")
        get_settings.cache_clear()
        get_engine.cache_clear()
        try:
            at = AppTest.from_file(str(ROOT / "app" / "pages" / "3_Trade_Lab.py"), default_timeout=120).run()
            if at.exception:
                return False, str(at.exception[0].value)
            spec = json.loads(at.get("plotly_chart")[0].proto.spec)
            at.button(key="lab_check").click().run()
            status = next((m.value for m in at.markdown if "badge[" in m.value and "checked" in m.value), "")
        finally:
            get_engine().dispose()
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
            get_settings.cache_clear()
            get_engine.cache_clear()
    candles = spec["data"][0]
    bars_day = candles["x"][-1][:10] if candles.get("x") else ""
    window_day = spec["layout"]["xaxis"].get("range", [""])[0][:10]
    ok = len(candles.get("x", [])) > 0 and bars_day == window_day and bool(status)
    entry = status.split("]")[0].split("[")[-1] if status else "no status"
    return ok, f"{len(candles.get('x', []))} bars of {bars_day}, window {window_day}, entry {entry}"


# --- Phase 5 ---------------------------------------------------------------------------------


def check_db_upgrade():
    """A copy of data/gatekeeper.db gets the new columns, keeps its rows; a second run adds nothing."""
    import shutil

    from sqlalchemy import text
    from sqlmodel import SQLModel

    from gatekeeper.db import add_missing_columns, make_engine

    real = ROOT / "data" / "gatekeeper.db"
    if not real.exists():
        return True, "no data/gatekeeper.db yet (a new database gets every column)"
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "copy.db"
        shutil.copyfile(real, copy)
        eng = make_engine(f"sqlite:///{copy.as_posix()}")
        with eng.connect() as c:
            before = c.execute(text("SELECT count(*) FROM skillrun")).scalar()
        SQLModel.metadata.create_all(eng)
        added = add_missing_columns(eng)
        again = add_missing_columns(eng)
        with eng.connect() as c:
            after = c.execute(text("SELECT count(*) FROM skillrun")).scalar()
        eng.dispose()
    ok = before == after and not again
    return ok, f"added {len(added)} column(s) {added or ''}; {after} skill runs kept; idempotent"


def check_live_day_panel():
    """The Home page's day-level Go / No-Go, live (a throwaway database)."""
    import os

    from streamlit.testing.v1 import AppTest

    from gatekeeper.db import get_engine
    from gatekeeper.settings import get_settings

    with tempfile.TemporaryDirectory() as tmp:
        old = {k: os.environ.get(k) for k in ("GATEKEEPER_MODE", "DB_URL")}
        os.environ.update(GATEKEEPER_MODE="live", DB_URL=f"sqlite:///{(Path(tmp) / 'd.db').as_posix()}")
        get_settings.cache_clear()
        get_engine.cache_clear()
        try:
            at = AppTest.from_file(str(ROOT / "app" / "Home.py"), default_timeout=120).run()
            panel = next((m.value for m in at.markdown if m.value.startswith("#### Today")), "")
            first = next((m.value for m in at.markdown if "**Market open**" in m.value), "")
        finally:
            get_engine().dispose()
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
            get_settings.cache_clear()
            get_engine.cache_clear()
    if at.exception:
        return False, str(at.exception[0].value)
    verdict = panel.split("[")[-1].rstrip("]") if panel else "no panel"
    return bool(panel), f"Today: {verdict} · {first.split('·', 1)[-1].strip()}"


PHASES: dict[int, list[tuple[str, Callable[[], tuple[bool, str]], bool]]] = {
    # (name, check, needs internet)
    0: [
        ("lint (ruff)", check_lint, False),
        ("skills' own tests (315)", check_upstream, False),
        ("clock and settings tests", pytest("tests/test_clock.py", "tests/test_settings.py"), False),
        ("Home page renders", check_home_page, False),
    ],
    1: [
        ("runner tests", pytest("tests/test_runner.py"), False),
        ("contract tests", pytest("tests/test_models_contract.py"), False),
        ("golden-number e2e tests", pytest("tests/test_replay_e2e.py"), False),
        ("contracts match a fresh run", check_contracts_unchanged, False),
        ("replay TSLA trade", check_replay_trade, False),
        ("NYSE calendar in the clock", check_calendar, False),
        ("live smoke: clock + SPY entry", check_live_smoke, True),
    ],
    2: [
        ("store tests", pytest("tests/test_store.py"), False),
        ("worker tests (replay day, guards, CLI)", pytest("tests/test_worker_replay.py"), False),
        ("schedule", check_schedule, False),
        ("worker replay 10:10 to 10:16", check_worker_replay, False),
        ("live: worker --once clock", check_worker_live_once, True),
    ],
    3: [
        (
            "market context, chart reader, formatting",
            pytest("tests/test_regime.py", "tests/test_yahoo.py", "tests/test_ui_tables.py"),
            False,
        ),
        ("pages in replay at 10:15 (41 hits, headlines)", pytest("tests/test_ui_smoke.py"), False),
        ("dashboard server starts", check_server, False),
        ("live: Home with real index tiles", check_live_home, True),
    ],
    4: [
        ("charts and Trade Lab logic", pytest("tests/test_charts.py", "tests/test_lab.py"), False),
        ("Trade Lab page in replay (golden numbers)", pytest("tests/test_ui_trade_lab.py"), False),
        ("live: Trade Lab chart and entry status", check_live_trade_lab, True),
    ],
    5: [
        ("every gate's boundaries, overall rule, store", pytest("tests/test_readiness.py"), False),
        ("the four replay scenarios", pytest("tests/test_go_no_go_replay.py"), False),
        (
            "panels, decision log, no buy/sell advice",
            pytest("tests/test_ui_trade_lab.py", "tests/test_wording.py"),
            False,
        ),
        ("your database upgrades in place (a copy)", check_db_upgrade, False),
        ("live: Home day-level Go / No-Go", check_live_day_panel, True),
    ],
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--phase", type=int, choices=sorted(PHASES), help="validate one phase (default: all)")
    ap.add_argument("--live", action="store_true", help="also run the checks that need the internet")
    a = ap.parse_args()

    phases = [a.phase] if a.phase is not None else sorted(PHASES)
    failed = 0
    for ph in phases:
        print(f"\nPhase {ph}")
        for name, fn, live in PHASES[ph]:
            if live and not a.live:
                print(f"  SKIP  {name:46} (add --live)")
                continue
            t0 = time.perf_counter()
            try:
                ok, detail = fn()
            except Exception as e:  # a check that crashes is a failed check
                ok, detail = False, f"{type(e).__name__}: {e}"
            failed += not ok
            print(f"  {'PASS' if ok else 'FAIL'}  {name:46} {time.perf_counter() - t0:5.1f}s  {detail}")
    print(f"\n{'All checks passed.' if not failed else f'{failed} check(s) failed.'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
