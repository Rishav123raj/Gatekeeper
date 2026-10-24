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
    changed = [n for n, d in fresh.items()
               if json.loads((committed / f"{n}.json").read_text(encoding="utf-8")) != d]
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
    return (False, "; ".join(bad)) if bad else (
        True, "41 hits · 364.18 · 358.32/370.04 · 29.4/25.5/45.1 % · 8 sh $46.88 · PASS")


def check_calendar():
    from datetime import date

    from gatekeeper.clock import market_day, session_phase

    thanks = market_day(date(2026, 11, 26))
    early = market_day(date(2026, 11, 27))
    ok = (
        thanks is not None and session_phase(datetime(2026, 11, 26, 10, 15), day=thanks) == "closed"
        and early is not None and session_phase(datetime(2026, 11, 27, 12, 45), day=early) == "late"
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
                print(f"  SKIP  {name:34} (add --live)")
                continue
            t0 = time.perf_counter()
            try:
                ok, detail = fn()
            except Exception as e:  # a check that crashes is a failed check
                ok, detail = False, f"{type(e).__name__}: {e}"
            failed += not ok
            print(f"  {'PASS' if ok else 'FAIL'}  {name:34} {time.perf_counter() - t0:5.1f}s  {detail}")
    print(f"\n{'All checks passed.' if not failed else f'{failed} check(s) failed.'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
