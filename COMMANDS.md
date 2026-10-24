# Gatekeeper: Command Reference

> **Every trade has to earn its way in.**

Every command you need to set up, run, test and maintain Gatekeeper. Commands are
for **PowerShell on Windows** and are run from the project folder unless stated:

```powershell
cd C:\Users\Lenovo\Desktop\trading_skills
```

Each section says which phase it applies from. Commands for phases that aren't
built yet are listed at the end.

---

## Contents

1. [First-time setup](#1-first-time-setup-phase-0)
2. [Run Gatekeeper](#2-run-gatekeeper-phase-0)
3. [Stop Gatekeeper](#3-stop-gatekeeper)
4. [Tests and lint](#4-tests-and-lint-phase-0)
5. [Run the skills directly](#5-run-the-skills-directly-phase-0)
6. [Replay the recorded day (Oct 19, 2026)](#6-replay-the-recorded-day-oct-19-2026-phase-0)
7. [Git workflow per phase](#7-git-workflow-per-phase)
8. [Maintenance](#8-maintenance)
9. [Troubleshooting](#9-troubleshooting)
10. [Coming in later phases](#10-coming-in-later-phases)

---

## 1. First-time setup (Phase 0)

On a new machine (uv, Git and Python 3.12 needed):

```powershell
# install uv (once per machine)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# get the code, including the pinned skills
git clone --recurse-submodules https://github.com/Rishav123raj/Gatekeeper.git
cd Gatekeeper

# install all dependencies into .venv
uv sync

# create your settings file, then edit it (SEC_USER_AGENT, CORE_TICKERS, AWAKE_IST...)
copy .env.example .env
notepad .env
```

If you cloned without `--recurse-submodules`:

```powershell
git submodule update --init
```

---

## 2. Run Gatekeeper (Phase 0)

| What | Command |
| --- | --- |
| **Dashboard and worker together** (two windows) | `powershell -ExecutionPolicy Bypass -File scripts\dev.ps1` |
| Dashboard only | `uv run streamlit run app/Home.py` |
| Worker only | `uv run python -m worker` |
| Dashboard on another port | `uv run streamlit run app/Home.py --server.port 8502` |

The dashboard opens at **http://127.0.0.1:8501**. It is bound to your own PC only.

### The dashboard (Phase 3)

| Page | What it shows |
| --- | --- |
| **Home** (Market Overview) | SPY / QQQ / IWM / VIX tiles with sparklines, the market-context label and its reasons, breakout breadth (gauge and line), today's risk budget, what changed (breakouts, important news, alerts), worker health. Refreshes every 30 s live |
| **Scanner** | Today's pre-market and opening-range scans: hits with range, % over, breakout time (NY and IST), news and earnings badges. Select rows to **Pin** them or **Open in Trade Lab**; **Run scan now** runs the scan job once |
| **Watchlist & News** | Pinned tickers with last price, % vs yesterday, MOVING, entry status, next earnings date (set by hand); the news stream with tag chips, `!` 8-K badges and links, filterable by ticker, tag and importance |
| **Trade Lab** | One ticker end to end: the 5-minute chart with the opening range, the entry trigger, entry / stop / target lines and the flat-by time; **Check entry** (entry.py); **Plan exit** with a live preview (exit.py, refusals shown as the tool says them); **Run Time Machine** (odds bar, fan chart, closing-price histogram, history and verdict verbatim, seed); **Compare** up to 4 stop / target variants without touching `trader/plan.json`. A banner appears if `trader/plan.json` changes outside the page (Claude chat). Nothing on this page places an order |

**LIVE / REPLAY** is a switch in the sidebar. In REPLAY a time slider (07:00 to 16:10
New York) plays back the recorded day, Mon 2026-10-19, with no internet: moving the
slider forward simulates only the new minutes, and moving it back rebuilds the day
from 07:00 (about 30 seconds). In replay the dashboard does the worker's job itself, so
the worker doesn't need to run. The recording has no index or VIX charts, so those
tiles show n/a in replay. To start in replay, set `GATEKEEPER_MODE=replay` in `.env`.

In LIVE the tiles come straight from Yahoo (cached a minute), and everything else
comes from the worker: start it in a second window (`scripts\dev.ps1` starts both).
The sidebar's worker dot is green when a job ran in the last 3 minutes.

### Go / No-Go (Phase 5)

Two panels answer two questions, each check with its reason (hover a line for its source):

- **Home → Today**: *should I be trading at all right now?* Market open, entry window, your
  awake hours in IST (is the flat-by time inside them?), daily loss budget, trades left, PDT,
  market context, breadth, recent form.
- **Trade Lab → 5 · Size, check and Go / No-Go**: *is this trade worth taking?* **Size & check**
  runs size.py (one bracket order) and check.py (PASS / BLOCK), then: entry triggered (and not
  stale), news clean, earnings outside the trade, plan valid, reward:risk at the fresh price,
  the Time Machine's verdict, history agrees, risk check, size sane.

The rule: any **hard** check failing → **NO TRADE**; otherwise any warning, or a **soft** check
failing → **CAUTION**; otherwise → **GO**. GO means your rules allow it and the honest odds aren't
against it; it is not a recommendation. Then **Log: Taken / Log: Skipped** (with a note and
"I followed my rules") records the decision with the result it had. When the risk check passes,
the panel shows a **ticket for Claude**: paste it into Claude chat, where /trader-broker asks for
your yes and Claude's Allow once card asks again. Gatekeeper itself never places an order.

Thresholds are in `.env` (see `.env.example`, `GATE_*`), for example:

| Setting | Default | Meaning |
| --- | --- | --- |
| `AWAKE_IST` | `18:30-23:30` | Your awake hours in IST; the flat-by time should fall inside them |
| `GATE_BREADTH_WARN_PCT` | `10` | Warn when fewer charts than this % broke out |
| `GATE_TM_NEITHER_WARN_PCT` | `40` | Warn when more replays than this % hit neither side |
| `GATE_ENTRY_STALE_BARS` | `1` | Warn when the trigger is more than this many bars old |
| `GATE_EARNINGS_WARN_SESSIONS` | `3` | Warn when the next report is this close |

### The background worker (Phase 2)

The worker runs the skills on a New York schedule and saves the results in
`data\gatekeeper.db`. It logs to the console and to `data\worker.log`. It never
places, cancels or changes an order.

| What | Command |
| --- | --- |
| **Run the worker** (until Ctrl+C) | `uv run python -m worker` |
| See every job and its next run (NY and IST) | `uv run python -m worker --list` |
| Run one job now | `uv run python -m worker --once orb_scan` (any job name from `--list`) |
| Run for a fixed time, then stop cleanly | `uv run python -m worker --run-for 600` |
| Log to the file only (quiet console) | `uv run python -m worker --quiet` |
| **Fast-forward the recorded day** (no internet) | `uv run python -m worker --replay --from 09:30 --to 10:30` |
| The same, watchable (10 simulated minutes a second) | `uv run python -m worker --replay --from 09:30 --to 10:30 --speed 600` |
| The whole recorded day | `uv run python -m worker --replay --from 07:00 --to 16:10` |
| Replay into a throwaway database | `uv run python -m worker --replay --db sqlite:///data/replay-test.db` |
| Follow the log | `Get-Content data\worker.log -Wait -Tail 20` |

The jobs and when they run (New York time; IST is 9:30 hours ahead until Nov 1, 10:30 after):

| Job | When (NY) | What it does |
| --- | --- | --- |
| `clock` | every minute | NYSE clock and session phase: the worker's pulse |
| `universe` | Sun 18:00 | Rebuilds the list of ~5,900 US stocks |
| `analyst_watchlist` | Mon–Fri 07:00 | Earnings for `CORE_TICKERS` (needs `SEC_USER_AGENT`) |
| `daily_scan` | Mon–Fri 08:30 | Pre-market scan of the whole universe (~2.5 min) |
| `premarket_news` | Mon–Fri 08:45 | News and 8-Ks for core + pinned + scan hits |
| `regime` | every 5 min, session | Market context: SPY / QQQ / IWM vs VWAP and the 20-day average, VIX, breakout breadth, and a supportive / mixed / hostile label (the rule is in `gatekeeper/regime.py`) |
| `orb_scan` | 09:50, 10:00, then every 15 min to the 15:30 cutoff | Opening-range breakouts for core + pinned tickers |
| `intraday_news` | every 15 min, session | New news only |
| `entry_watch` | every minute, 09:45 to 15:30 | Pinned tickers, until each triggers or expires |
| `quotes` | every 5 min, session | Fresh prices, only while a plan for today or a position exists |
| `alerts_check` | every 2 min, session | Rings your alert rules (stop, target, flat-by) |
| `pelosi` | Mon–Fri, hourly 08:00–20:00 | New Congress trade filings |
| `eod_journal` | Mon–Fri 16:10 | End-of-day journal (arrives in Phase 7; skips until then) |

Weekends, NYSE holidays and early closes are handled: a job outside its window
records "skipped" with the reason. Switch jobs off with
`DISABLED_JOBS=pelosi,analyst_watchlist` in `.env`.

The entry watch follows *pinned* tickers. Pin them on the Scanner or the Watchlist page, or here:

| What | Command |
| --- | --- |
| Pin tickers for the entry watch | `uv run python -m worker --add-pin TSLA,NVDA` |
| Unpin | `uv run python -m worker --remove-pin NVDA` |
| List the pins | `uv run python -m worker --pins` |

---

## 3. Stop Gatekeeper

- Press **Ctrl+C** in each window (dashboard and worker), or close the windows.
- If port 8501 is stuck after a crash:
  ```powershell
  Get-NetTCPConnection -LocalPort 8501 | Select-Object OwningProcess
  Stop-Process -Id <OwningProcess>
  ```

---

## 4. Tests and lint (Phase 0)

| What | Command |
| --- | --- |
| All Gatekeeper tests | `uv run pytest` |
| Quiet summary | `uv run pytest -q` |
| One file, verbose | `uv run pytest tests/test_clock.py -v` |
| Tests matching a name | `uv run pytest -k ist` |
| With coverage | `uv run pytest --cov=gatekeeper --cov-report=term-missing` |
| Lint | `uv run ruff check .` |
| Lint and auto-fix | `uv run ruff check . --fix` |
| Format code | `uv run ruff format .` |
| The skills' own tests (315) | see below |

The skills' tests must run from inside their folder:

```powershell
cd vendor\day-trader-skill
uv run --no-project python -m unittest discover -s tests
cd ..\..
```

**Before every commit:** `uv run ruff check . ; uv run pytest`

### Validate a phase (PASS / FAIL per check)

One command checks everything a phase delivered and prints a PASS / FAIL line per check:

| What | Command |
| --- | --- |
| **Validate Phase 5** (offline) | `uv run python scripts/validate.py --phase 5` |
| Validate Phase 5, including the live day panel | `uv run python scripts/validate.py --phase 5 --live` |
| Validate Phase 4 (offline) | `uv run python scripts/validate.py --phase 4` |
| Validate Phase 4, including the live Trade Lab check | `uv run python scripts/validate.py --phase 4 --live` |
| Validate Phase 3 (offline) | `uv run python scripts/validate.py --phase 3` |
| Validate Phase 3, including the live Home check | `uv run python scripts/validate.py --phase 3 --live` |
| Validate Phase 2 (offline) | `uv run python scripts/validate.py --phase 2` |
| Validate Phase 2, including the live check | `uv run python scripts/validate.py --phase 2 --live` |
| Validate Phase 1 (offline) | `uv run python scripts/validate.py --phase 1` |
| Validate Phase 1, including the live checks (internet) | `uv run python scripts/validate.py --phase 1 --live` |
| Validate Phase 0 | `uv run python scripts/validate.py --phase 0` |
| Validate every phase built so far | `uv run python scripts/validate.py --live` |

Phase 1's checks:

| Check | What it proves |
| --- | --- |
| runner tests | Exit codes, errors, timeouts, the `trader/` lock, isolated mode, replay injection |
| contract tests | All 18 saved skill outputs parse into the models, and a fresh run has the same structure |
| golden-number e2e tests | The documented TSLA trade, every number |
| contracts match a fresh run | Re-runs the skills and compares with `tests/contracts/` value by value |
| replay TSLA trade | 41 hits · 364.18 · 358.32 / 370.04 · 29.4 / 25.5 / 45.1 % · 8 shares, $46.88 · PASS |
| NYSE calendar in the clock | Thanksgiving closed; the Nov 27 early close stops entries at 12:30 |
| live smoke (`--live`) | The real NYSE clock and a real SPY entry check answer |

It exits 0 when every check passed. During a US session (from 19:15 IST on
weekdays, 20:15 IST from Nov 2), `--live` shows SPY's real status, for example
`waiting` or `triggered`. On weekends and at night it shows `closed` / `no-data`.

Phase 5's checks:

| Check | What it proves |
| --- | --- |
| every gate's boundaries, overall rule, store | All 18 checks at their PASS / WARN / FAIL edges (window minutes, loss %, trades left, PDT, VIX, breadth, form, trigger age, 8-K items, earnings sessions, risk %, reward:risk, verdicts, history), the GO / CAUTION / NO TRADE rule, repeat-skipping storage, the decision log, and that an older database gets the new columns |
| the four replay scenarios | TSLA 10:15, 8 shares → CAUTION (coin flip; earnings in the news); 9 shares → NO TRADE ($52.74 > $50); 09:40 → NO TRADE (window); 366.48 quote at 10:55 → NO TRADE (reward:risk 0.44, $65.28) |
| panels, decision log, no buy/sell advice | The Trade Lab: NO TRADE before sizing, CAUTION after Size & check, the ticket for Claude, "Log: Skipped" stored with plan, result, note and the rules flag; the Home day panel; no "buy" / "sell" wording as advice anywhere in the app |
| your database upgrades in place | A copy of `data\gatekeeper.db` gets the new columns and keeps every row |
| live: Home day-level Go / No-Go (`--live`) | The day panel live (on a weekend: NO TRADE, closed) |

Phase 4's checks:

| Check | What it proves |
| --- | --- |
| charts and Trade Lab logic | The candle chart's levels, trigger marker and flat-by line; the odds bar, fan and histogram; the stop / target preview matches exit.py's rounding; the comparison never writes `trader/plan.json` and its 1R row equals the main run |
| Trade Lab page in replay | At 10:15: TRIGGERED at $364.18 (bar 8); plan $358.32 / $370.04, risk $5.86; Time Machine to the close 29.4 / 25.5 / 45.1 %, green 51.7 %, avg R +0.034, history 33 fired (13 / 15 / 5), "Close to a coin flip" verbatim, seed 19; compare 1R / 2R / or-low; the external-plan banner and reload |
| live: Trade Lab chart and entry status (`--live`) | A real TSLA chart on its own session's day, and a live entry status from entry.py |

**Trade Lab in replay, step by step:** sidebar → REPLAY, slider at 10:15 → Trade Lab → TSLA →
**Check entry** → Target **1R** → **Plan exit** → End each replay at **the close (16:00)** →
**Run Time Machine** → **Compare**. The page shows every recorded number above. With the
default end (your flat-by time, 15:55) the odds are 29.2 / 24.2 / 46.6 %.

Phase 3's checks:

| Check | What it proves |
| --- | --- |
| market context, chart reader, formatting | The label rule at every threshold; VWAP, opening range and 20-day numbers; the recorded charts show only bars closed by the replay time; live fetching falls back from query2 to query1, caches, and treats failures as n/a; NY / IST times in tables |
| pages in replay at 10:15 | Every page loads with the clock bar and footer; the Scanner shows 41 ORB hits with TSLA 354.47 – 362.18, broke out 10:15 NY · 19:45 IST; News shows the three morning headlines with their tags; pinning works; the replay slider moves forward or rebuilds |
| dashboard server starts | `streamlit run app/Home.py` answers its health check and serves the app |
| live: Home with real index tiles (`--live`) | SPY, QQQ, IWM and VIX tiles show real prices from Yahoo |

Phase 2's checks:

| Check | What it proves |
| --- | --- |
| store tests | Results become rows; news isn't stored twice; an entry is stored only when its status changes; pins, heartbeats, WAL, concurrent writers |
| worker tests | A whole replay day (07:00 to 16:10) with no errors: daily + 23 ORB scans, TSLA waiting at 9:45 then triggered at 10:15, earnings, Congress filings, heartbeats, no overlapping `trader/` writes, the flat-by alert at 15:56; Thanksgiving and weekends skip; the Nov 27 early close cuts the jobs |
| schedule | 13 jobs; the ORB scan fires 25 times a day from 09:50 NY |
| worker replay 10:10 to 10:16 | The CLI fast-forward: TSLA triggered at 364.18 at 10:15, 41 ORB hits |
| live: worker --once clock (`--live`) | The live clock job runs and records its heartbeat |

### Skill contracts and the recorded numbers (Phase 1)

| What | Command |
| --- | --- |
| Every recorded number, end to end (orb → entry → exit → Time Machine → size → risk) | `uv run pytest tests/test_replay_e2e.py -v` |
| The skills' JSON still parses and hasn't changed shape | `uv run pytest tests/test_models_contract.py -v` |
| The runner (exit codes, lock, timeouts, replay) | `uv run pytest tests/test_runner.py -v` |
| Re-save the contract snapshots (after upgrading the skills) | `uv run python scripts/snapshot_contracts.py` |
| See what changed in them | `git diff tests/contracts` |

---

## 5. Run the skills directly (Phase 0)

The 11 skill scripts can be run without the dashboard. Run them from the
project folder, because they read and write `trader\` in the current folder,
the same folder Gatekeeper uses.

Set a shortcut for the session first:

```powershell
$S = "vendor\day-trader-skill"
```

| Skill | Example |
| --- | --- |
| Market clock | `uv run python $S\trader-alerts\alerts.py clock` |
| Delayed quote | `uv run python $S\trader-alerts\alerts.py quote TSLA` |
| Pre-market scan (core list) | `uv run python $S\trader-scanner\scan.py daily --symbols TSLA,NVDA,AMD,AAPL` |
| Opening-range scan (after 9:50 NY) | `uv run python $S\trader-scanner\scan.py orb --symbols TSLA,NVDA,AMD,AAPL` |
| News | `uv run python $S\trader-news\news.py --tickers TSLA NVDA --hours 12` |
| Entry check | `uv run python $S\trader-entry\entry.py check TSLA` |
| Exit plan | `uv run python $S\trader-exit\exit.py plan --stop or-mid --target 2R --write` |
| Time Machine | `uv run python $S\trader-timemachine\timemachine.py run --write` |
| Position size | `uv run python $S\trader-budget\size.py --write` |
| Risk check | `uv run python $S\trader-risk\check.py` |
| Order tickets (no broker calls) | `uv run python $S\trader-broker\ticket.py show` |
| Earnings | `uv run python $S\trader-analyst\facts.py TSLA` |
| Congress filings | `uv run python $S\trader-pelosi\ptr.py index --member pelosi` |

Useful flags on most tools: `--json` (machine-readable), `--help` (all options),
`--now "YYYY-MM-DD HH:MM"` (pretend it's that New York time), `--offline PATH`
(read saved data instead of the internet).

> News and earnings need `SEC_USER_AGENT` set (in `.env`, or `$env:SEC_USER_AGENT = "Your Name you@example.com"`). The exit, Time Machine, size and risk tools need the files written by the step before (`entry.json` → `plan.json` → `orders.json`), and size and risk need `trader\config.json` (copy `$S\trader-budget\config.example.json` to `trader\config.json`).

---

## 6. Replay the recorded day (Oct 19, 2026) (Phase 0)

The skills ship real recorded market data. These commands reproduce the
documented TSLA trade without the internet:

```powershell
$S = "vendor\day-trader-skill"
$F = "$S\tests\fixtures"

# Opening-range scan at 10:15: 41 hits ($5 floor), TSLA among them
uv run python $S\trader-scanner\scan.py orb --offline $F\trader-scanner\wall5m-2026-10-19.json.gz --now "2026-10-19 10:15" --no-write

# Entry at 10:12 (WAITING) and at 10:15 (TRIGGERED at 364.18)
uv run python $S\trader-entry\entry.py check TSLA --offline $F\trader-entry\TSLA-2026-10-19-5m.json --now "2026-10-19 10:12"
uv run python $S\trader-entry\entry.py check TSLA --offline $F\trader-entry\TSLA-2026-10-19-5m.json --now "2026-10-19 10:15"

# Time Machine: target 29.4 %, stop 25.5 %, neither 45.1 % (seed 19)
uv run python $S\trader-timemachine\timemachine.py run --symbol TSLA --date 2026-10-19 --entry 364.18 --stop 358.32 --target 370.04 --entry-time "10:15 AM" --offline $F\trader-timemachine\TSLA-60d5m.json.gz --now "2026-10-19 10:15"
```

### The same replay through Gatekeeper's Python layer (Phase 1)

A replay runs in `replay\workspace\`, so your live `trader\` folder is never touched.
Save this as a file in `scripts\`, for example `scripts\replay_demo.py`, and run
`uv run python scripts\replay_demo.py`:

```python
from datetime import datetime

from gatekeeper.replay import prepare_workspace
from gatekeeper.runner import SkillRunner
from gatekeeper.skills import budget, entry, exit, risk, timemachine

ctx = prepare_workspace(datetime(2026, 10, 19, 10, 15))   # fresh replay workspace at 10:15 NY
r = SkillRunner.from_settings(replay=ctx)

status, _ = entry.check("TSLA", write=True, runner=r)
print(status.status, status.trigger.price)                  # triggered 364.18
plan, _ = exit.plan(stop="or-mid", target="1R", runner=r)
print(plan.stop, plan.target)                              # 358.32 370.04
tm, _ = timemachine.run(runner=r)
print(tm.verdict)                                          # Close to a coin flip: ...
size, _ = budget.size(runner=r)
print(size.sizing.qty, size.sizing.max_loss)               # 8 46.88
report, res = risk.check(runner=r)
print(res.status, report.results[0].verdict)               # ok PASS
```

Every wrapper returns `(model, run_result)`. `run_result.status` is `ok`, `empty`
(a valid "no": no hits, not triggered, market closed), `blocked` (risk BLOCK,
sizing refused), `partial` or `error` (with the reason in `run_result.message`).
Leave out `replay=ctx` to run live.

> Or open the dashboard, switch the sidebar to **REPLAY** and move the time slider (Section 2).

---

## 7. Git workflow per phase

```powershell
# start a phase (from an up-to-date main)
git checkout main
git pull
git checkout -b phase-1-adapter

# save work
git add -A
git commit -m "phase 1: <what changed>"
git push -u origin phase-1-adapter     # CI runs on every push

# when the phase's exit criteria are ticked and CI is green: merge into main
git checkout main
git merge --ff-only phase-1-adapter
git push
```

| What | Command |
| --- | --- |
| Status | `git status` |
| History | `git log --oneline -10` |
| Branches | `git branch -vv` |
| CI results | https://github.com/Rishav123raj/Gatekeeper/actions |

---

## 8. Maintenance

| What | Command |
| --- | --- |
| Add a dependency | `uv add <package>` |
| Add a dev-only dependency | `uv add --dev <package>` |
| Upgrade all dependencies | `uv lock --upgrade ; uv sync` |
| Rebuild the environment from scratch | `Remove-Item -Recurse -Force .venv ; uv sync` |
| Show the pinned skills version | `git -C vendor\day-trader-skill log -1 --oneline` |
| Check for a newer skills version | `git -C vendor\day-trader-skill fetch ; git -C vendor\day-trader-skill log --oneline HEAD..origin/main` |

**Upgrading the skills** (do it on a branch, see the guide's task 9.7):

```powershell
git checkout -b skills-upgrade
git -C vendor\day-trader-skill pull origin main
cd vendor\day-trader-skill ; uv run --no-project python -m unittest discover -s tests ; cd ..\..
uv run pytest
git add vendor\day-trader-skill
git commit -m "skills: upgrade to <commit>"
```

Record the new commit in the Decision log of `IMPLEMENTATION_GUIDE.md`.

---

## 9. Troubleshooting

| Problem | Fix |
| --- | --- |
| `uv` is not recognised | Install it (Section 1), then open a **new** terminal |
| `running scripts is disabled on this system` | Use `powershell -ExecutionPolicy Bypass -File scripts\dev.ps1`, or once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `vendor\day-trader-skill` is empty | `git submodule update --init` |
| `ModuleNotFoundError: gatekeeper` | Run `uv sync`, and start commands with `uv run` |
| Port 8501 already in use | Stop the old process (Section 3) or use `--server.port 8502` |
| `PytestCacheWarning ... Access is denied` | Harmless (Windows folder permissions); tests still run |
| Clock shows the wrong session | Check `trader\config.json` times (`no_entries_before`, `no_entries_after`, `flat_by`, all New York time) |
| News or earnings say SEC is skipped | Set `SEC_USER_AGENT` in `.env` |
| Yahoo returns errors or empty data | The data is free and unofficial; wait a few minutes, use fewer tickers |
| Laptop slept and the worker missed things | Keep the PC awake during the session (Phase 9 adds a script) |

---

## 10. Coming in later phases

These commands will work once their phase is built. This file is updated at the end of each phase.

| Phase | Command | What it does |
| --- | --- | --- |
| 3 | `GATEKEEPER_MODE=replay` in `.env` | Dashboard in replay mode, with a time slider |
| 6 | `uv sync --extra notify` | Windows toast notifications |
| 8 | `uv sync --extra broker` | Alpaca **paper** trading support (optional phase) |
| 9 | `powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1` | Starts the worker automatically at login |
| 9 | `powershell -ExecutionPolicy Bypass -File scripts\keep_awake.ps1` | Keeps the PC awake during the US session |
