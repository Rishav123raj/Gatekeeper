# Gatekeeper: Phase-wise Implementation Guide

> **Every trade has to earn its way in.**

This is the build tracker for Gatekeeper. It turns
[DASHBOARD_PROJECT_PLAN.md](DASHBOARD_PROJECT_PLAN.md) (the *what* and *why*)
into ordered, checkable tasks (the *how*). Work one phase at a time. Each phase
ends with exit criteria that must all be ticked before the next one starts.

---

## How to use this file

### For you (tracking)
- Tick tasks as they finish: `- [ ]` → `- [x]`.
- Update the **Progress dashboard** row for the phase (status, dates).
- Add a line to the **Progress log** at the bottom after every work session.
- Record any change of plan in the **Decision log** so it isn't lost.

### For Claude (implementing)
Start a phase by saying, for example:

> "Implement Phase 2 from IMPLEMENTATION_GUIDE.md."

Claude will then:
1. Read this file and the plan, and check that the previous phase's exit criteria are all ticked.
2. Do the phase's tasks in order, writing the listed files and tests.
3. Run the phase's verification commands and report the real output.
4. Tick finished tasks, update the dashboard row, and append to the progress log.
5. Stop at the end of the phase, list anything skipped or failed, and wait for your go-ahead.

### Status legend
⬜ Not started · 🟨 In progress · ✅ Done · ⏸ Blocked · ⏭ Skipped (optional phase)

---

## Progress dashboard

| Phase | Name | Plan milestone | Status | Started | Finished | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | Foundation | M0 | ✅ | 2026-10-24 | 2026-10-24 | CI green on Windows + Ubuntu |
| 1 | Skill adapter & contracts | M1 | ✅ | 2026-10-24 | 2026-10-24 | CI run 40065638051 green on Windows + Ubuntu |
| 2 | Storage & background worker | M2 | ✅ | 2026-10-24 | 2026-10-24 | CI run 40074262315 green on Windows + Ubuntu |
| 3 | Market Overview, Scanner, News | M3 | ✅ | 2026-10-24 | 2026-10-24 | CI run 40108052325 green on Windows + Ubuntu (after the Windows pin-order fix, Issue 6) |
| 4 | Trade Lab | M4 | ✅ | 2026-10-24 | 2026-10-24 | CI run 40115151903 green on Windows + Ubuntu |
| 5 | Go / No-Go engine | M5 | ✅ | 2026-10-24 | 2026-10-24 | CI run 40118467980 green on Windows + Ubuntu |
| 6 | Risk, Size, Positions, Alerts | M6 | ✅ | 2026-10-24 | 2026-10-25 | CI run 40127238785 green on Windows + Ubuntu |
| 7 | Journal & Research | M7 | ✅ | 2026-10-25 | 2026-10-25 | CI run 40165361349 green on Windows + Ubuntu |
| P | Paper-trading period (4 to 8 weeks) | — | ⬜ | | | Usage, not code |
| 8 | Alpaca paper execution (optional) | M8 | ⬜ | | | |
| 9 | Hardening & operations | M9 | ⬜ | | | |

---

## Conventions (apply to every phase)

| Topic | Rule |
| --- | --- |
| Python | 3.12, run everything through `uv run ...` |
| Layout | Library code in `gatekeeper/`, background jobs in `worker/`, UI in `app/`, tests in `tests/` |
| Skills | Never edit files under `vendor/day-trader-skill/`. Call them only through `gatekeeper/runner.py` |
| Shell | Commands below are PowerShell (Windows). Use `uv run python`, never `python3` |
| Time | Store UTC; compute in `America/New_York`; display New York time and IST |
| Git | One branch per phase (`phase-0-foundation`, ...), merged to `main` when its exit criteria pass |
| Commits | `phase N: <what>`, small and frequent |
| Tests | Every phase adds tests; `uv run pytest` must be green before a phase is ✅ |
| Network in tests | None. Tests use replay fixtures only |
| Safety | No code path places, cancels or replaces a broker order before Phase 8, and none ever touches a live account |

### Reference: replay fixtures (from the skills repo)

Path prefix: `vendor/day-trader-skill/tests/fixtures/`

| Tool | `--offline` takes | Fixture |
| --- | --- | --- |
| `scan.py universe` | DIR | `trader-scanner/symdir/` |
| `scan.py daily` | PATH | `trader-scanner/daily-spark-2026-10-19.json` |
| `scan.py orb` | PATH | `trader-scanner/wall5m-2026-10-19.json.gz` |
| `entry.py` | PATH | `trader-entry/TSLA-2026-10-19-5m.json` |
| `exit.py plan --stop atr:K` | PATH | `trader-entry/TSLA-2026-10-19-5m.json` |
| `timemachine.py` | FILE | `trader-timemachine/TSLA-60d5m.json.gz` |
| `news.py` | DIR | `trader-news/` |
| `alerts.py` | DIR | `trader-alerts/` |
| `facts.py` | DIR | `trader-analyst/` |
| `ptr.py index/new` | FILE | `trader-pelosi/2026FD.zip` |
| `size.py`, `check.py`, `ticket.py` | (none: read `trader/` files) | seed from `trader-budget/plan-tsla.json`, `trader-risk/orders-tsla.json` |

### Reference: golden numbers (replay day Mon 2026-10-19)

| Check | Expected |
| --- | --- |
| ORB scan at 10:15 (`--min-price 0`) | 42 of 231 usable charts broke out; TSLA range 354.47 to 362.18, close 364.18, +0.55% |
| ORB scan at 10:15 (default `--min-price 5`) | 41 hits |
| Entry at 10:12 | WAITING, last close 361.68, 0.50 under 362.18 |
| Entry at 10:15 | TRIGGERED at 364.18 (the 10:10 bar, bar 8) |
| Entry with `--min-volume-x 1` | trigger moves to 10:35 at 365.75 |
| Exit `--stop or-mid --target 1R` | stop 358.32, target 370.04, risk 5.86 (1.61%) |
| Time Machine (seed 19, until 16:00) | target 29.4%, stop 25.5%, neither 45.1%, green 51.7%, avg R +0.034 |
| Time Machine history | 59 sessions, fired 33: 13 target, 15 stop, 5 neither, avg R −0.062 |
| Budget ($5,000, $50 max loss) | 8 shares, $2,913.44, max loss $46.88, bound by max loss |
| Risk, 8 shares | PASS; cash after $2,086.56 |
| Risk, 9 shares | BLOCK, loss $52.74 > $50 |
| Risk at 9:40 | BLOCK by window |

> If a number differs, first check the pinned skills commit, then the `--now` and `--offline` arguments. Never "fix" a golden number to match the code without recording why in the Decision log.

---

## Phase 0: Foundation

**Goal:** an empty but runnable project: environment, folders, pinned skills, settings, CI, and a Streamlit page that shows the New York / IST clock.

**Prerequisites:** Python 3.12 ✅ (installed), Git, internet access.

### Tasks

- [x] **0.1 Install uv**: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`, then `uv --version`.
- [x] **0.2 Git**: `git init` in the project root, `main` branch, then branch `phase-0-foundation`.
- [x] **0.3 Pin the skills**: `git submodule add https://github.com/Jakeschincariol/day-trader-skill vendor/day-trader-skill`; record the commit hash in the Decision log.
- [x] **0.4 Run the upstream tests** once: `uv run python -m unittest discover -s vendor/day-trader-skill/tests -v` (all pass).
- [x] **0.5 `pyproject.toml`**:
  ```toml
  [project]
  name = "gatekeeper"
  version = "0.1.0"
  requires-python = ">=3.12"
  dependencies = [
    "streamlit>=1.40", "plotly>=5.24", "pandas>=2.2",
    "pydantic>=2.8", "pydantic-settings>=2.4",
    "apscheduler>=3.10,<4", "sqlmodel>=0.0.22",
    "httpx>=0.27", "filelock>=3.15", "tzdata>=2024.1",
  ]
  [project.optional-dependencies]
  notify = ["win11toast>=0.35"]
  broker = ["alpaca-py>=0.30"]
  [dependency-groups]
  dev = ["pytest>=8", "pytest-cov>=5", "freezegun>=1.5", "ruff>=0.6"]
  [tool.ruff]
  line-length = 110
  [tool.pytest.ini_options]
  testpaths = ["tests"]
  ```
  Then `uv sync`.
- [x] **0.6 Folders**: `gatekeeper/`, `gatekeeper/skills/`, `worker/`, `app/pages/`, `app/components/`, `data/cache/`, `replay/workspace/`, `scripts/`, `tests/contracts/`, each package with an `__init__.py`.
- [x] **0.7 `.gitignore`**: `.env`, `.venv/`, `trader/`, `data/`, `replay/workspace/`, `__pycache__/`, `*.db`, `.pytest_cache/`.
- [x] **0.8 `.env.example`**: copy the block from plan Section 13.
- [x] **0.9 `gatekeeper/settings.py`**: a `Settings(BaseSettings)` class with `mode`, `skills_dir`, `project_root`, `db_url`, `sec_user_agent`, `core_tickers: list[str]`, `awake_ist: str`, `full_universe_orb: bool`, `notify`, and gate thresholds (Phase 5 fills these). `get_settings()` is cached.
- [x] **0.10 `gatekeeper/clock.py`**:
  - `NY = ZoneInfo("America/New_York")`, `IST = ZoneInfo("Asia/Kolkata")`
  - `now_ny(replay_now: datetime | None = None) -> datetime`
  - `to_ist(dt) -> datetime`, `fmt_dual(dt) -> "NY 10:15 · IST 19:45"`
  - `session_phase(dt) -> Literal["closed","premarket","opening_range","entry_window","late","after_close"]` using config times. Holidays and early closes come from `alerts.py clock --json` in Phase 1; for now, weekends only.
- [x] **0.11 `.streamlit/config.toml`**: `[server] address = "127.0.0.1"`, `headless = true`; `[theme]` left at defaults.
- [x] **0.12 `app/components/clock_bar.py`** and **`app/Home.py`**: show the clock bar and "Gatekeeper: Every trade has to earn its way in."
- [x] **0.13 `scripts/dev.ps1`**: starts `uv run python -m worker` (placeholder for now) and `uv run streamlit run app/Home.py` in two windows.
- [x] **0.14 CI** `.github/workflows/ci.yml`: matrix `windows-latest`, `ubuntu-latest`; checkout with submodules; `uv sync`; `uv run ruff check .`; `uv run pytest`.
- [x] **0.15 Tests**: `tests/test_clock.py`:
  - 2026-10-19 10:15 NY → 19:45 IST
  - 2026-11-02 10:15 NY → 20:45 IST (after the Nov 1 daylight-saving change)
  - 2027-03-15 10:15 NY → 19:45 IST (after Mar 14)
  - a Saturday → `closed`

### Verify
```powershell
uv sync
uv run ruff check .
uv run pytest
uv run streamlit run app/Home.py      # page opens at http://127.0.0.1:8501
```

### Exit criteria
- [x] `uv run pytest` green; ruff clean
- [x] The upstream skills test suite passes on the pinned commit
- [x] The Home page shows the clock bar with correct NY and IST times
- [x] CI green on Windows and Ubuntu (run 40008407159, commit c7c8c6f)

---

## Phase 1: Skill adapter & contracts

**Goal:** one tested way to call every skill and get a typed Python object back, in live or replay mode. This is the riskiest phase; everything later stands on it.

### Tasks

**Runner**
- [x] **1.1 `gatekeeper/runner.py`**: `RunResult` dataclass (`ok`, `status`, `exit_code`, `data`, `stdout`, `stderr`, `started_at`, `duration_s`, `tool`, `args`).
- [x] **1.2** `SkillRunner.run(tool, args, json_out=True, timeout=300, writes_state=False)`:
  - resolves `<skills_dir>/trader-<tool>/<script>.py` from a fixed map (`scanner→scan.py`, `news→news.py`, `entry→entry.py`, `exit→exit.py`, `timemachine→timemachine.py`, `budget→size.py`, `risk→check.py`, `broker→ticket.py`, `alerts→alerts.py`, `analyst→facts.py`, `pelosi→ptr.py`);
  - runs `[sys.executable, script, *args, "--json"?]` with `cwd` = project root (live) or `replay/workspace` (replay);
  - env adds `PYTHONIOENCODING=utf-8`, `PYTHONUTF8=1`, `SEC_USER_AGENT`;
  - takes `FileLock(trader/.gatekeeper.lock, timeout=60)` when `writes_state`;
  - parses stdout as JSON when asked; non-JSON output is `status="error"` with the text kept.
- [x] **1.3 Exit-code map** per tool → `ok | empty | blocked | error`:
  - scanner: 0 ok, 1 empty
  - news: 0 ok, 1 empty (nothing new)
  - alerts `check`: 0 ok (something rang), 1 empty
  - risk: 0 ok (all PASS), 1 blocked
  - pelosi `new`: 0 ok, 1 empty
  - entry `watch`: 0 triggered, 1 expired
  - Verify each against the script source and record any surprise in the Decision log.
- [x] **1.4 Replay injection**: when `mode == "replay"`, append `--now "<replay_now>"` (where the tool supports it) and the `--offline` path from the fixture table above. Keep the mapping in `gatekeeper/replay.py`.
- [x] **1.5 `gatekeeper/replay.py`**: `prepare_workspace(replay_now)` wipes and recreates `replay/workspace/trader/`, writes a `config.json` copied from `trader-budget/config.example.json` (budget 5000, paper true), and sets the current replay time.

**Contracts**
- [x] **1.6 `scripts/snapshot_contracts.py`**: runs every command below in replay mode and saves stdout JSON to `tests/contracts/<name>.json`:
  `alerts_clock`, `scanner_universe`, `scanner_daily`, `scanner_orb_1015`, `news_tsla`, `entry_tsla_1012`, `entry_tsla_1015`, `exit_plan_or_mid_1r`, `timemachine_run`, `budget_size`, `risk_check_pass`, `broker_show`, `analyst_tsla`, `pelosi_index`.
- [x] **1.7 Read the snapshots** and write `gatekeeper/skills/models.py`, one pydantic model per output (`ClockStatus`, `UniverseResult`, `ScanResult`/`ScanHit`, `NewsResult`/`NewsItem`, `EntryStatus`, `ExitPlan`, `TimeMachineResult` (with `mc` bands, sample paths and histogram), `SizeResult`, `RiskReport`/`RiskVerdict`, `Ticket`, `EarningsFacts`, `PtrFiling`/`PtrRow`). Use `ConfigDict(extra="allow")`. Field names come **from the real JSON**, not guesses.

**Wrappers** (each returns `(model | None, RunResult)`)
- [x] **1.8** `skills/scanner.py`: `universe()`, `daily(symbols=None, limit=None)`, `orb(at=None, symbols=None, watchlist=None, max_confirm=200)`
- [x] **1.9** `skills/news.py`: `check(tickers=None, hours=None, no_sec=False, show_all=False, dry_run=False)`
- [x] **1.10** `skills/entry.py`: `check(symbol, setup="orb", level=None, interval="5m", min_volume_x=None, or_minutes=15, write=False)`, `watchlist()`
- [x] **1.11** `skills/exit.py`: `plan(stop="or-mid", target="2R", flat_by=None, entry=None, write=True)`, `show()`
- [x] **1.12** `skills/timemachine.py`: `run(until=None, replays=10_000, seed=19, write=True)` plus an explicit-plan variant (`symbol, date, entry, stop, target, entry_time`)
- [x] **1.13** `skills/budget.py`: `size(limit=None, write=True)`
- [x] **1.14** `skills/risk.py`: `check(no_write=False)`
- [x] **1.15** `skills/broker.py`: `show()`, `log()`, `flatten(symbol, qty)`, `fill(symbol, side, qty, price)`, `approve(index, reply)`, `result(...)`. **No broker network calls.**
- [x] **1.16** `skills/alerts.py`: `clock()`, `quote(symbols, write=True)`, `add_from_plan()`, `add_rule(...)`, `check()`, `list_rules()`, `reset(rule_id)`
- [x] **1.17** `skills/analyst.py`: `facts(tickers, quarters=4, metrics_path=None)`
- [x] **1.18** `skills/pelosi.py`: `index(member=None, since=None, year=None)`, `new(member=None, read=False)`
- [x] **1.19** Update `clock.session_phase()` to use `alerts.clock()` for holidays and early closes (cached per day).

**Tests**
- [x] **1.20** `tests/test_runner.py`: exit-code mapping (fake scripts in `tmp_path`), timeout, non-JSON stdout, lock contention (two threads), a path containing spaces.
- [x] **1.21** `tests/test_models_contract.py`: every snapshot parses into its model; key fields present.
- [x] **1.22** `tests/test_replay_e2e.py`: chain orb → entry → exit → timemachine → budget → risk in a fresh replay workspace and assert **every golden number** in the reference table.

### Verify
```powershell
uv run python scripts/snapshot_contracts.py
uv run pytest tests/test_runner.py tests/test_models_contract.py tests/test_replay_e2e.py -v
uv run python scripts/validate.py --phase 1 --live   # every Phase 1 check, PASS / FAIL
```

### Exit criteria
- [x] All 11 tools callable through wrappers in replay mode
- [x] Golden-number end-to-end test passes
- [x] One live smoke call works: `alerts.clock()` and `entry.check("SPY")` return models (done by hand, not in CI; run on a Saturday, so "closed" and "no-data", see Issue 2)
- [x] Contract snapshots are committed

---

## Phase 2: Storage & background worker

**Goal:** jobs run on a New York schedule, store results in SQLite, and never write `trader/` at the same time.

### Tasks
- [x] **2.1 `gatekeeper/db.py`**: SQLModel engine from `db_url`, `init_db()`, `session()` context manager; WAL mode (`PRAGMA journal_mode=WAL`) so the UI can read while the worker writes.
- [x] **2.2 Tables** (plan Section 8): `SkillRun`, `ScanRun`, `ScanHit`, `NewsItem`, `EarningsSnapshot`, `RegimeSnapshot`, `EntrySignal`, `Plan`, `TmResult`, `RiskVerdict`, `Readiness`, `Decision`, `TradeJournal`, `AlertFired`, `PelosiFiling`, plus `PinnedTicker` and `JobHeartbeat`. Each result table has a `mode` column (live/replay) and a `payload` JSON column.
- [x] **2.3** The runner writes a `SkillRun` row for every call.
- [x] **2.4 `gatekeeper/store.py`**: functions that turn models into rows: `save_scan(result)`, `save_news(result)` (dedupe on URL), `save_entry(status)` (insert only when the status changes), `save_plan`, `save_tm`, `save_risk`, `save_alert_fired`, `save_pelosi`.
- [x] **2.5 `worker/jobs.py`**: one function per job in plan Section 7: `job_universe`, `job_analyst_watchlist`, `job_daily_scan`, `job_premarket_news`, `job_regime` (stub until Phase 3), `job_orb_scan`, `job_intraday_news`, `job_entry_watch`, `job_alerts_check`, `job_quotes`, `job_pelosi`, `job_eod_journal` (stub until Phase 7). Each:
  1. checks `session_phase()` and returns early when it doesn't apply;
  2. calls the wrapper;
  3. saves the result;
  4. updates `JobHeartbeat(job, last_ok, last_error)`.
- [x] **2.6 `worker/__main__.py`**: `BackgroundScheduler(timezone="America/New_York", job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 120})`, cron triggers per the plan, graceful Ctrl+C shutdown, a log to `data/worker.log`.
- [x] **2.7 Simulated clock for replay**: `worker --replay --from 08:00 --to 16:10 --speed 60` steps a fake clock and fires the due jobs in order (no real waiting). This is used for tests and demos.
- [x] **2.8** Job toggles from settings (for example `FULL_UNIVERSE_ORB=false` skips the universe-wide ORB scan).

### Tests
- [x] **2.9** `tests/test_worker_replay.py`: a replay day from 08:00 to 16:10 → `ScanRun` rows for daily and ORB, `NewsItem` rows for TSLA, `EntrySignal` TSLA flips to TRIGGERED at 10:15, heartbeats for every job, no exceptions.
- [x] **2.10** `tests/test_store.py`: news dedupe; entry status changes only.
- [x] **2.11** Weekend and holiday guard: jobs skip on 2026-11-26 (Thanksgiving); the 2026-11-27 early close cuts the jobs at 13:00.

### Verify
```powershell
uv run pytest tests/test_worker_replay.py tests/test_store.py -v
uv run python -m worker --replay --from 09:30 --to 10:30 --speed 600
uv run python scripts/validate.py --phase 2 --live   # every Phase 2 check, PASS / FAIL
```

### Exit criteria
- [x] A replay day fills every table that should be filled (the worker fills: SkillRun, JobHeartbeat, ScanRun/ScanHit, NewsItem, PriceMove, EarningsSnapshot, EntrySignal, AlertFired, PelosiFiling, PinnedTicker. Regime is Phase 3; Plan, TmResult, RiskVerdict come from the Trade Lab, Phases 4–5; Readiness and Decision Phase 5; TradeJournal Phase 7)
- [x] No two state-writing runs overlap (checked from `SkillRun` timestamps, sequential replay day and 4 concurrent threads)
- [x] The live worker starts, runs `alerts.clock` every minute for 10 minutes, and stops cleanly (`--run-for 600` on 2026-10-24: 10 clock runs on the minute, 01:38 to 01:47 NY, "worker stopped cleanly", exit 0; a Saturday, so the other jobs had nothing to do, see Issue 4)

---

## Phase 3: Market Overview, Scanner, News

**Goal:** the first useful screens: what is the market doing, what matched a setup, what news is out.

### Tasks
- [x] **3.1 `gatekeeper/yahoo.py`**: `bars(symbol, range_="1d", interval="5m") -> pd.DataFrame[ts, open, high, low, close, volume]`, `quote(symbols)`. Uses httpx with a 10 s timeout, the user agent `gatekeeper/0.1`, query2 then query1 fallback, a 0.5 s pause between calls, a 60 s cache; in replay it reads fixture files and is cut at `replay_now`.
- [x] **3.2 `gatekeeper/regime.py`**: `snapshot() -> RegimeSnapshot` for SPY, QQQ, IWM (% change, price vs. session VWAP, vs. the opening range, daily close vs. the 20- and 50-day average) and `^VIX` (level, % change); `breadth` = ORB hits ÷ usable charts from the latest ORB `ScanRun`; a `label` among `supportive | mixed | hostile` with the rule written down in the docstring. In replay, mark any series without a fixture as "n/a" rather than failing.
- [x] **3.3** Turn the Phase 2 `job_regime` stub into the real job.
- [x] **3.4 `app/components/tables.py`**: shared table formatting (price, %, time in dual zones).
- [x] **3.5 `app/components/charts.py` (part 1)**: `sparkline(df)`, `breadth_line(scan_runs)`.
- [x] **3.6 Sidebar (all pages)**: mode badge (LIVE/REPLAY), replay date and time slider (writes `replay_now` to session state and settings), worker heartbeat dot.
- [x] **3.7 `app/Home.py`**: index tiles with sparklines, VIX tile, breadth gauge, today's budget bars (from `trader/state/broker.json` via `broker.log()`), the "What changed" feed (latest hits, important news, fired alerts), the worker-health table. A `st.fragment(run_every="30s")` wraps the live parts. The day-level Go / No-Go panel is a placeholder until Phase 5.
- [x] **3.8 `app/pages/1_Scanner.py`**: tabs for Pre-market and ORB; filters; a table with news and earnings badges; buttons **Pin**, **Open in Trade Lab** (sets `st.session_state.symbol` and calls `st.switch_page`), **Run scan now** (disabled while running).
- [x] **3.9 `app/pages/2_Watchlist_News.py`**: pinned tickers with last price, % change, MOVING flag, latest `EntrySignal`; a news stream with tag chips, `!` badges and links, filterable by ticker and tag; a manual "next earnings date" field per ticker (stored in `EarningsSnapshot.next_report_date`).
- [x] **3.10** Every page footer: "Data: Yahoo (free, delayed, unofficial) · Not financial advice."

### Tests
- [x] **3.11** `tests/test_regime.py`: label rule on synthetic data.
- [x] **3.12** `tests/test_ui_smoke.py` (`streamlit.testing.v1.AppTest`): Home, Scanner and News load in replay at 10:15 without exceptions; the Scanner table contains TSLA.

### Verify
```powershell
uv run pytest tests/test_regime.py tests/test_ui_smoke.py -v
uv run streamlit run app/Home.py      # switch to REPLAY, slide to 10:15
uv run python scripts/validate.py --phase 3 --live   # every Phase 3 check, PASS / FAIL
```

### Exit criteria
- [x] Replay 10:15: the Scanner shows 41 ORB hits (default $5 floor), including TSLA with range 354.47 to 362.18 (`test_scanner_shows_41_orb_hits_with_tsla`)
- [x] Replay: the TSLA news stream shows the three documented morning headlines with tags (earnings; earnings + deal; macro)
- [x] Live: Home loads with real index tiles (SPY $759.97, QQQ $704.40, IWM $275.75, VIX 19.45, label "hostile"; checked on Saturday 2026-10-24 with Friday's session data, so a re-check during a session is folded into Issue 4)

---

## Phase 4: Trade Lab

**Goal:** the core page: see the setup on a chart, plan the exit, and get the honest odds.

### Tasks
- [x] **4.1 `charts.candles_with_levels(df, or_high, or_low, entry, stop, target, trigger_ts, flat_by)`**: Plotly candlesticks plus a volume subplot, a shaded opening-range band, a trigger marker, entry/stop/target lines with labels, and a flat-by vertical line. The x-axis is New York time, with IST in the hover.
- [x] **4.2 `charts.tm_odds_bar(tm)`**: stacked bar for target / stop / neither, with green as a separate marker.
- [x] **4.3 `charts.tm_fan(tm)`**: percentile bands from `mc`, about 50 of the sample paths drawn faintly, stop and target lines.
- [x] **4.4 `charts.tm_close_hist(tm)`**: the 24-bin histogram of the price at `--until`.
- [x] **4.5 `app/pages/3_Trade_Lab.py` layout**:
  1. Symbol picker (pinned + scanner hits + free text).
  2. Chart (4.1), auto-refreshing every 60 s in live mode.
  3. **Entry panel**: setup (orb/level + level input), interval, volume multiple → `entry.check(write=True)`; a status line exactly as the tool says it.
  4. **Exit panel**: stop rule (or-mid / or-low / pct:X / atr:K / price:X), target (1R / 1.5R / 2R / price:X), a live preview of risk per share and reward:risk (computed locally for preview only) → **Plan exit** runs `exit.plan(write=True)` and saves a `Plan`. Refusals are shown verbatim in red.
  5. **Time Machine panel**: **Run** with `until = flat_by` → odds bar, fan, histogram, then the history line and the verdict lines **verbatim**, plus the seed. Saves `TmResult` linked to the plan.
  6. **Compare plans**: up to 4 stop/target variants. Each variant runs `timemachine.run` through the explicit-plan arguments (it does **not** overwrite `trader/plan.json`), with the same seed; results go in a comparison table.
  7. Placeholder for the trade-level Go / No-Go panel (Phase 5).
- [x] **4.6** Long Time Machine runs use `st.status` with a spinner, and the button is disabled while running.
- [x] **4.7** A banner when `trader/plan.json` changed outside the dashboard (for example from Claude chat): "Plan updated externally, reload?"

### Tests
- [x] **4.8** `tests/test_charts.py`: figures build from the replay data; trace counts and level values are correct.
- [x] **4.9** Extend the UI smoke test: Trade Lab replay at 10:15 with TSLA renders the trigger marker at 364.18; Plan exit gives 358.32 / 370.04; Time Machine shows 29.4 / 25.5 / 45.1 and "Close to a coin flip".

### Verify
```powershell
uv run pytest tests/test_charts.py tests/test_lab.py tests/test_ui_trade_lab.py -v
uv run streamlit run app/Home.py      # REPLAY at 10:15 → Trade Lab → TSLA → Check entry → 1R → Plan exit → close → Run
uv run python scripts/validate.py --phase 4 --live   # every Phase 4 check, PASS / FAIL
```

### Exit criteria
- [x] All replay golden numbers appear on the page (entry 364.18 bar 8; plan 358.32 / 370.04, risk 5.86; Time Machine to the close 29.4 / 25.5 / 45.1 %, green 51.7 %, avg R +0.034, history 33 / 13 / 15 / 5, "Close to a coin flip"; `tests/test_ui_trade_lab.py`)
- [x] Comparison of 1R vs 2R vs or-low stop works without touching `trader/plan.json` (byte-for-byte check in `test_lab.py` and `test_ui_trade_lab.py`)
- [x] Live: a pinned ticker's chart and entry status (real TSLA chart, 79 bars, and a live entry.py status; checked on Saturday 2026-10-24, so the status was NO-DATA "closed today (weekend)" and the chart showed Friday's session; seeing it move bar by bar during a session is part of Issue 4)

---

## Phase 5: Go / No-Go engine

**Goal:** turn everything into GO / CAUTION / NO TRADE with reasons, for the day and for the trade.

### Tasks
- [x] **5.1 `gatekeeper/readiness.py`**:
  - `Gate(name, level: Literal["hard","soft"], status: Literal["PASS","WARN","FAIL"], reason: str, source: str)`
  - `evaluate_day(ctx) -> Readiness` and `evaluate_trade(ctx, plan_id) -> Readiness`
  - overall: any hard FAIL → **NO_TRADE**; otherwise any WARN or soft FAIL → **CAUTION**; otherwise **GO**.
- [x] **5.2 Day gates** (plan 9.1): market open, entry window, awake window in IST, daily loss budget, trades left, PDT, market context, breadth, recent form.
- [x] **5.3 Trade gates** (plan 9.2): entry triggered (plus staleness more than one bar old), news clean (`!` items 2.02, 4.02, 1.03, 3.01, 1.05 and the halt tag → FAIL), earnings outside the trade, plan valid, reward:risk at the fresh price, Time Machine verdict (parse the verdict text into `strong_target | lean_target | coin_flip | break_even | lean_stop | strong_stop`), history agrees, risk check, size sane.
- [x] **5.4 Thresholds** move into `Settings` (`gate_*` fields) with the plan's defaults; nothing is hard-coded in the gate functions.
- [x] **5.5 Context builder**: `build_context(plan_id=None)` gathers the latest rows plus a fresh `alerts.clock()`; one function so the gates stay pure and testable.
- [x] **5.6 `app/components/gates.py`**: the panel from plan 9.3 (icons, reasons, source tooltips), with buttons **Log: Taken** and **Log: Skipped** (a note field and a "followed my rules" checkbox) → a `Decision` row, plus **Copy ticket for Claude** (copies `/trader-broker` text).
- [x] **5.7** Wire the panels into Home (day) and Trade Lab (trade); store every evaluation as a `Readiness` row.
- [x] **5.8** For the trade flow in Trade Lab, add **Size & check**: `budget.size(write=True)` then `risk.check()` before evaluating the trade gates.

### Tests
- [x] **5.9** `tests/test_readiness.py`: table-driven PASS/WARN/FAIL boundaries for every gate; overall-result logic.
- [x] **5.10** Replay scenarios:
  - TSLA 10:15, 8 shares → **CAUTION** (coin flip; earnings this week)
  - 9 shares → **NO_TRADE** (risk BLOCK $52.74)
  - 09:40 → **NO_TRADE** (window)
  - quote 366.48 at 10:55 → **NO_TRADE** (reward:risk 0.44; loss $65.28)

### Verify
```powershell
uv run pytest tests/test_readiness.py tests/test_go_no_go_replay.py tests/test_ui_trade_lab.py tests/test_wording.py -v
uv run streamlit run app/Home.py      # REPLAY 10:15: Home → Today panel; Trade Lab → … → Size & check → panel → Log
uv run python scripts/validate.py --phase 5 --live   # every Phase 5 check, PASS / FAIL
```

### Exit criteria
- [x] All four replay scenarios give the expected result and reasons (CAUTION: coin flip + earnings in the news; NO TRADE: $52.74; NO TRADE: window; NO TRADE: reward:risk 0.44 and $65.28; `tests/test_go_no_go_replay.py`)
- [x] Decisions are logged with plan, result, note and rules-followed flag (plus the symbol and a link to the evaluation; `test_decision_is_logged`)
- [x] No wording anywhere says "buy" or "sell" as advice (enforced by `tests/test_wording.py`; the only "BUY" shown is the skill's own order ticket text)

---

## Phase 6: Risk, Size, Positions, Alerts

**Goal:** see your limits, sizing and open trades, and get alerted on time, especially for flat-by in IST.

### Tasks
- [x] **6.1 `app/pages/4_Risk_Size.py`**: limits card from `trader/config.json`; size result as a bar chart of the four limits with the binding one highlighted; risk report per order (PASS/BLOCK, reasons, warnings); today's risk ledger.
- [x] **6.2 "What if" price slider**: copies `trader/` to a temporary sandbox working directory, writes `prices.json` there, runs `size` and `risk --no-write` in the sandbox, and shows the result. The live `trader/` is never touched.
- [x] **6.3 `app/pages/5_Positions_Alerts.py`**: positions from `trader/portfolio.json` with last price, distance to stop and target in R, P&L in R only (no dollar projections); a flat-by countdown in NY and IST (red under 10 minutes); alert rules list with add/reset forms; fired-alert history.
- [x] **6.4 Flatten helper**: `broker.flatten()`, then `risk.check()`, then show the ticket with clear steps (cancel the bracket legs, then sell) to do in your broker or Claude chat. **No order is sent.**
- [x] **6.5 Record fills manually**: a form that calls `broker.fill()` / `broker.result()`, so the portfolio and daily-loss ledger stay correct.
- [x] **6.6 `gatekeeper/notify.py`**: `notify(title, body)` → none / Windows toast (`win11toast`) / Telegram (httpx POST to the Bot API). `job_alerts_check` calls it for each new `AlertFired`. Flat-by and stop alerts are marked urgent.
- [x] **6.7 After Plan exit**, Trade Lab offers **Add plan alerts** → `alerts.add_from_plan()`.

### Tests
- [x] **6.8** `tests/test_notify.py` with a fake transport.
- [x] **6.9** Replay: run the worker from 15:40 to 16:00 with the TSLA plan alerts → the "Flat by close" alert fires once at 15:55 and `notify` is called once.
- [x] **6.10** The sandbox "What if" leaves `trader/` byte-for-byte unchanged (hash before and after).

### Verify
```powershell
uv run pytest tests/test_notify.py tests/test_sandbox.py tests/test_alerts_notify.py tests/test_ui_risk_positions.py -v
uv run streamlit run app/Home.py      # REPLAY 10:15: Risk & Size (What if), Positions & Alerts (fill, ticket, rules)
uv run python scripts/validate.py --phase 6 --live   # every Phase 6 check, PASS / FAIL (+ one test notification)
```

### Exit criteria
- [x] Flat-by alert arrives as a Windows toast (or Telegram) in a live test using a custom `--at` time (2026-10-24: a `--at 15:50` "flat by close" rule rang through the worker's alerts job on the replay clock, since time rules only ring on trading days and this was a Saturday, and the real `NOTIFY=toast` notifier handed it to Windows in 0.21 s, non-blocking; your visual confirmation is Issue 7)
- [x] The Risk page reproduces PASS (8 shares) and BLOCK (9 shares) (the 9 through the What-if sandbox: $52.74 > $50; `tests/test_ui_risk_positions.py`)
- [x] Manually recorded fills update positions and today's ledger (buy 8 TSLA at 364.20 → position 8 shares, avg 364.20, 1.0R to the stop and the target; a `filled` row in today's ledger)

---

## Phase 7: Journal & Research

**Goal:** the learning loop (did following Gatekeeper help?) and the research views.

### Tasks
- [x] **7.1 `gatekeeper/journal.py`**:
  - `simulate_outcome(plan, bars) -> (r_result, exit_reason)`: walks 5-minute bars after the entry; stop is checked first, then target; a bar touching both counts as stop; otherwise flat at `flat_by` at that bar's close. The same rules as the Time Machine.
  - `stats(trades) -> {n, win_rate, avg_win_r, avg_loss_r, expectancy_r, profit_factor, max_dd_r, longest_losing_streak, adherence_rate}`
  - `calibration(trades) -> realised win rate per Time Machine verdict bucket`
  - `breakdown(trades, by="setup"|"entry_bucket"|"weekday")`
- [x] **7.2 `job_eod_journal`** (16:10 NY): for every plan today, a TAKEN decision with recorded fills gives the real R; TAKEN without fills is flagged "needs fill"; SKIPPED or no decision gives a simulated R (`simulated=true`).
- [x] **7.3 `app/pages/6_Journal.py`**: decision log table (editable notes); stats tiles; cumulative R (taken vs. "if I had taken all"); R histogram; calibration bar chart with sample sizes and a plain-language verdict ("not enough trades yet" under 40); breakdowns; the paper → live readiness card (40+ trades, expectancy > 0, adherence ≥ 95%), display only; CSV export.
- [x] **7.4 `app/pages/7_Research.py`**:
  - **Earnings** tab: `analyst.facts()` → quarterly revenue and EPS bars with year-on-year labels, margin lines, TTM, flags, links.
  - **Congress** tab: `pelosi.index()/new()` table with filters, an overlap flag against pinned tickers and holdings, and the 45-day-lag banner.
- [x] **7.5 `app/pages/8_Settings.py`**: `trader/config.json` editor (pydantic-validated, diff preview, timestamped backup in `data/backups/`); the `paper` field is **read-only**; dashboard settings (core tickers, awake hours, thresholds, job toggles, notifications); Diagnostics (`SkillRun` log, last error per tool, pinned skills commit, **Run contract self-test** which runs the Phase 1 contract tests in a subprocess).

### Tests
- [x] **7.6** `tests/test_journal.py`: `simulate_outcome` on hand-built bars (target first, stop first, both in one bar → stop, flat at flat-by); `stats` and `calibration` on 10 synthetic trades with known answers.
- [x] **7.7** Replay EOD for the TSLA plan produces a simulated R and a journal row.

### Verify
```powershell
uv run pytest tests/test_journal.py tests/test_eod_journal.py tests/test_config_edit.py tests/test_ui_journal_research_settings.py -v
uv run streamlit run app/Home.py      # REPLAY: plan TSLA at 10:15, decide, slide to 16:10, open Journal, Research, Settings
uv run python scripts/validate.py --phase 7 --live   # every Phase 7 check, PASS / FAIL (+ AAPL from SEC EDGAR)
```

### Exit criteria
- [x] Journal metrics match hand-calculated values (`tests/test_journal.py`: 10 synthetic trades, win rate 40 %, expectancy -0.05R, profit factor 0.9, max drawdown -2.5R, the working in comments; the replay TSLA skip is (366.68 - 364.18) / 5.86 = +0.427R)
- [x] Calibration chart renders and says "not enough data" below 40 trades ("Not enough trades yet: 1 of the 40 needed…" on the replay evening)
- [x] Settings refuses to change `paper`, and backs up the config before every save (the toggle is disabled; `config_edit.save` raises `PaperChangeRefused` either way and writes nothing; a budget change through the page left a byte-identical backup first)

---

## Phase P: Paper-trading period (usage, not code)

**Goal:** use Gatekeeper live, read-only, for 4 to 8 weeks to find out whether the process gives you an edge, before building any execution.

### Checklist
- [ ] `trader/config.json` set for your IST awake window (for example entries 09:45 to 11:00 NY, `flat_by` 12:00 NY)
- [ ] Alpaca **paper** account (or IBKR paper) connected to Claude for manual `/trader-broker` orders
- [ ] Worker running every US trading day; notifications working
- [ ] One setup only (for example 15-minute ORB, `or-mid` stop, 2R target)
- [ ] Every plan gets a Taken or Skipped decision, with "followed rules" ticked honestly
- [ ] Weekly review (fill in below)

| Week | Plans | Taken | Skipped | Expectancy (taken) | Expectancy (all, incl. simulated) | Adherence | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | | | | | | | |
| 2 | | | | | | | |
| 3 | | | | | | | |
| 4 | | | | | | | |
| 5 | | | | | | | |
| 6 | | | | | | | |
| 7 | | | | | | | |
| 8 | | | | | | | |

### Exit criteria (decide honestly)
- [ ] 40+ decisions logged
- [ ] The calibration chart has been reviewed: do "Leans target" trades beat "Coin flip" trades?
- [ ] Expectancy recorded. If ≤ 0: adjust the setup and repeat Phase P; **do not** go to Phase 8 for execution convenience
- [ ] Decision recorded in the Decision log: continue to Phase 8 / repeat Phase P / stop

---

## Phase 8: Alpaca paper execution (optional)

**Goal:** place **paper** orders from the dashboard, behind gates at least as strict as the skills' own.

**Do not start** unless the Phase P exit criteria are ticked and you have explicitly chosen to build this.

### Tasks
- [ ] **8.1** `uv sync --extra broker`; keys in `.env` (`ALPACA_API_KEY`, `ALPACA_SECRET_KEY`), never in the UI or logs.
- [ ] **8.2 `gatekeeper/broker_alpaca.py`**: `TradingClient(key, secret, paper=True)`, with `paper=True` **hard-coded** (no setting). On start, `get_account()`; refuse to load if the account is not a paper account, and log why.
- [ ] **8.3 Order gate** `place_bracket(order_index)`:
  1. reads `trader/orders.json[index]`;
  2. requires a **PASS** in `trader/state/risk.json` for that order's fingerprint, dated today (reuse `broker.show()` READY status);
  3. requires the typed confirmation to equal `BUY <qty> <SYMBOL>` exactly, then records it with `broker.approve(index, reply)` and requires "Recorded your yes";
  4. requires a second **Confirm (paper)** click;
  5. submits a market bracket (`take_profit.limit_price`, `stop_loss.stop_price`, whole shares, `time_in_force=day`);
  6. records the outcome with `broker.result(...)`.
- [ ] **8.4 Flatten** from Positions: cancel the open bracket legs, then a market sell for the held quantity; same typed-confirmation gate (`SELL <qty> <SYMBOL>`), and the exit is never blocked by day limits.
- [ ] **8.5 Fill sync job** (every 1 minute when positions exist): read Alpaca orders and positions, then `broker.fill()` / `result()`.
- [ ] **8.6** No job or background task can call `place_bracket` or flatten; a test enforces this by inspecting `worker/jobs.py` imports.

### Tests
- [ ] **8.7** Mocked `TradingClient`: no PASS → refused; wrong typed text → refused; a live account → module refuses to load; the happy path submits exactly the ticket's values.
- [ ] **8.8** A manual paper test: one 1-share order end-to-end, visible in the Alpaca paper dashboard, then flattened.

### Exit criteria
- [ ] All refusal paths tested
- [ ] One manual paper round trip completed and journaled
- [ ] A code review confirms there is no live-account path

---

## Phase 9: Hardening & operations

**Goal:** Gatekeeper runs reliably every trading evening without babysitting.

### Tasks
- [ ] **9.1 Resilience**: retries with backoff around Yahoo in `yahoo.py`; a "data stale" banner when the last good fetch is older than 2× its interval; the runner kills hung subprocesses at the timeout.
- [ ] **9.2 Worker heartbeat** on Home (red if no heartbeat for 3 minutes during the session).
- [ ] **9.3 Windows Task Scheduler** entry `Gatekeeper Worker` (start at login, restart on failure); a `scripts/install_task.ps1` script.
- [ ] **9.4 Keep awake**: `scripts/keep_awake.ps1` sets `powercfg /change standby-timeout-ac 0` during the session window and restores it after; documented in the README.
- [ ] **9.5 Backups**: a nightly copy of `data/gatekeeper.db` (using the SQLite backup API) and `trader/` to `data/backups/YYYY-MM-DD/`, keeping 30 days.
- [ ] **9.6 Log rotation** for `data/worker.log` (RotatingFileHandler, 5 × 5 MB).
- [ ] **9.7 Upgrade procedure** for the skills: bump the submodule on a branch, run upstream tests, `snapshot_contracts.py`, the contract tests, and the golden e2e; merge only if green; record the commit in the Decision log.
- [ ] **9.8 README runbook**: install, first run, daily routine (IST), what to do when Yahoo fails, how to upgrade, how to restore a backup.

### Exit criteria
- [ ] The worker survives a network drop (Wi-Fi off for 5 minutes) and a reboot
- [ ] A backup restores into a working database
- [ ] A skills upgrade dry run is documented

---

## Definition of done (whole project)

- [ ] Phases 0 to 7 ✅; Phase P completed with a recorded decision; Phases 8 and 9 ✅ or ⏭ with reasons
- [ ] `uv run pytest` green on Windows; CI green
- [ ] The replay demo reproduces every golden number from the dashboard
- [ ] No code path can touch a live brokerage account
- [ ] The README lets someone else install and run Gatekeeper from scratch

---

## Decision log

Record anything that changes the plan, a pinned version, or a golden number.

| Date | Phase | Decision | Reason |
| --- | --- | --- | --- |
| 2026-10-24 | — | Project named **Gatekeeper**, tagline "Every trade has to earn its way in." | Chosen by the user |
| 2026-10-24 | 0 | Pinned day-trader-skill commit: `3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd` (2026-10-20, "The Trader skill v2") | 315 upstream tests pass on it |
| 2026-10-24 | 0 | uv was already installed (0.8.13), and git was already set up on `main` with remote `Rishav123raj/Gatekeeper`; both were kept as they were | No reinstall or `git init` needed |
| 2026-10-24 | 0 | `pyproject.toml` adds a hatchling build so `gatekeeper`, `worker` and `app` install in editable mode | `streamlit run app/Home.py` only adds `app/` to the import path; installing the packages makes `from gatekeeper...` work from anywhere |
| 2026-10-24 | 0 | `pydantic-settings>=2.7` (not 2.4) | `NoDecode` is needed so `CORE_TICKERS=A,B,C` reads as a comma list |
| 2026-10-24 | 0 | The upstream tests run from inside `vendor/day-trader-skill` (`uv run --no-project ...`), not with `-s vendor/...` from the project root | The suite expects its own folder as the working directory |
| 2026-10-24 | 0 | No `replay/fixtures` symlink; replay reads fixtures directly from `vendor/day-trader-skill/tests/fixtures/` | Windows symlinks need admin rights or developer mode |
| 2026-10-24 | 0 | Gate threshold settings are deferred to Phase 5 (task 5.4) | They are only defined once the gates exist |
| 2026-10-24 | 0 | Added `.gitattributes` (LF line endings, CRLF for `.ps1`) and `tests/test_settings.py` | Avoids CRLF churn in diffs; covers the settings parsing |
| 2026-10-24 | 1 | **Exit codes (task 1.3): the guide's map was incomplete.** The rule the runner uses: JSON printed → `ok` on exit 0, else the tool's negative answer; no JSON → `error` with the stderr message. Negative answers: `empty` by default (no hits, nothing new, not triggered, market closed, no READY ticket), `blocked` for risk, budget (sizing refused) and broker `approve` ("Not recorded"), `partial` for analyst (some tickers failed). News, analyst and pelosi use exit 2 for errors | Read from every script's source: they print JSON for negative results and exit 1 for both "nothing" and errors, so the exit code alone can't tell them apart |
| 2026-10-24 | 1 | Scripts run as `python -I -X utf8 <script>` | `-I` (isolated) stops anything in the working folder shadowing a module; `-X utf8` gives UTF-8 output on Windows (`-I` ignores `PYTHONIOENCODING`) |
| 2026-10-24 | 1 | Commands with no JSON mode (`ticket.py approve/decline/result/fill/flatten/log`, `alerts.py add/list/reset`) are run for their effect, and their results read back from `trader/` files | Confirmed in the scripts' argparse definitions |
| 2026-10-24 | 1 | The Time Machine's printed JSON leaves out `mc.sample_paths` (160 paths); the wrapper reads them back from the file it writes | `timemachine.py` line 885 drops them from stdout |
| 2026-10-24 | 1 | Contract `analyst_tsla` became `analyst_aapl`; added contracts `risk_check_block_9`, `alerts_quote`, `alerts_check_1556`, `pelosi_new` (18 in all). Shared generator in `gatekeeper/contracts.py`, used by the snapshot script and the tests (structure-drift and reproducibility checks) | The analyst fixtures have AAPL and KO only, no TSLA |
| 2026-10-24 | 1 | Replay: `entry.py` reads a `charts/` folder in the workspace (TSLA only); pelosi gets `--year 2026 --today <replay date>`; news gets `--now` as ISO with offset; explicit `--now`/`--offline` from a caller always win | Matches how the skills' own tests call each tool |
| 2026-10-24 | 1 | Golden-number note, no change: "42 of 231 usable" is for `--min-price 0`; with the default $5 floor it is 41 hits of 222 usable | Both reproduced exactly |
| 2026-10-24 | 1 | `session_phase` takes the day's `alerts.py clock` status: holidays are closed, and an early close moves the close and the entry cutoff up together (13:00 close → 12:30 cutoff). `market_day()` caches per date and doesn't cache a failed lookup. The clock bar shows early closes and holidays | Task 1.19 |
| 2026-10-24 | 2 | Tables live in `gatekeeper/tables.py` (db.py has only the engine and session). Added a `PriceMove` table (each news check's price line, for the MOVING flag in Phase 3). The scan type is `ScanRun.scan_mode` (daily/orb), so `mode` always means live/replay | Keeps `mode` consistent on every table; the watchlist page needs the price moves |
| 2026-10-24 | 2 | Times are stored as time-zone-aware UTC | SQLModel 0.0.48 refuses naive datetimes; aware UTC matches the "store UTC" convention |
| 2026-10-24 | 2 | The runner now times each script **inside** the `trader/` lock (`started_at`, `duration_s`) and reports the lock wait separately (`waited_s`, `writes_state` on `SkillRun`) | Otherwise the run log can't prove that state-writing runs never overlap |
| 2026-10-24 | 2 | `SkillRun` rows are written through the runner's `on_result` hook (`store.skill_run_logger`), which the worker attaches; the runner itself stays database-free | Keeps Phase 1's runner and tests unchanged |
| 2026-10-24 | 2 | One schedule (`worker/jobs.py: SCHEDULE`, cron rules in New York time) feeds both the live APScheduler and the replay simulator, which asks the same cron triggers for their fire times | A replay fires exactly what a live day would |
| 2026-10-24 | 2 | Added a `clock` job (every minute): the worker's pulse. Live it calls `alerts.py clock`; in replay it uses the cached calendar, so a simulated day doesn't spend ~500 subprocesses on a static calendar | Exit criterion 3, without slowing replays |
| 2026-10-24 | 2 | The entry watch stops checking a ticker once it has triggered or expired that day; alerts and quotes skip when there are no rules / no plan or position for today | One trigger per setup per day (the skill's rule); saves free-API calls |
| 2026-10-24 | 2 | Job tickers: live uses `CORE_TICKERS` + pinned (+ the latest scan's top 10 for news); replay uses the recorded data (the 234-chart wall for scans, TSLA for news, AAPL and KO for earnings). The live daily scan builds the universe first if `trader/universe.txt` is missing | Replay can only use what was recorded |
| 2026-10-24 | 2 | New settings `DISABLED_JOBS` and `WORKER_LOCK_TIMEOUT` (300 s); new worker options `--list`, `--once JOB`, `--run-for`, `--add-pin/--remove-pin/--pins`, `--db`, `--quiet`, `--keep`; `scripts/validate.py` gained Phase 2 checks | Task 2.8 and day-to-day use |
| 2026-10-24 | 2 | The day test runs 07:00 to 16:10 (not 08:00) so the 07:00 earnings job is included; it expects 23 ORB scans (25 fire times; 15:30 and 15:45 are after the entry cutoff) | Covers every worker-filled table |
| 2026-10-24 | 3 | **In replay the dashboard drives the simulator itself**: the sidebar's time slider calls `sync_replay`, which simulates only the minutes since the last position (a new `ReplayState` table remembers it) and rebuilds from 07:00 when the slider moves back (about 30 s), keeping the replay pins. The separate worker isn't needed in replay | The guide's slider "writes `replay_now`", but the pages read the database, which must hold the replay day up to that time |
| 2026-10-24 | 3 | The replay data has no SPY / QQQ / IWM / VIX charts, so in replay those tiles show n/a and the market-context label is "unknown" (breadth is the only signal) | Allowed by task 3.2 ("mark any series without a fixture as n/a") |
| 2026-10-24 | 3 | Live index tiles are fetched by the Home page itself (cached 60 s), not only read from the worker's `RegimeSnapshot` | The tiles work even when the worker isn't running |
| 2026-10-24 | 3 | The market-context label rule: SPY vs VWAP, QQQ vs VWAP, SPY vs its 20-day average, VIX (down = +1, up 10 % or more = −1) and breadth (25 % or more = +1, under 10 % = −1); sum ≥ 2 supportive, ≤ −2 hostile, else mixed; fewer than 2 signals with data = unknown. Written in `gatekeeper/regime.py`'s docstring | Task 3.2 asks for the rule to be written down |
| 2026-10-24 | 3 | The `regime` job runs after `orb_scan` when both are due (the schedule order changed) | Otherwise its breadth lagged one scan behind |
| 2026-10-24 | 3 | New: `gatekeeper/yahoo.py` (live with query2→query1 fallback and a 60 s cache, plus a replay reader that shows only bars closed by the replay time), `REPLAY_WORKSPACE` setting, `app/state.py` and `app/components/page.py` (shared page setup), a Trade Lab placeholder page so "Open in Trade Lab" has somewhere to go | Needed by the pages |
| 2026-10-24 | 3 | Streamlit 1.66: `use_container_width` is deprecated (full width is the default), so it isn't used; dataframe row selection and markdown badges (`:red-badge[...]`) are used for selection and tag chips | Avoids deprecation warnings |
| 2026-10-24 | 3 | CI now posts failing tests and the first traceback as **annotations** (`scripts/ci_failure_annotation.py`), readable without admin rights, and runs pytest with a 600 s per-test timeout (`pytest-timeout`, a stack dump instead of a hang) | GitHub job logs need admin rights to download; Issue 5 |
| 2026-10-24 | 4 | The Time Machine panel ends replays at the plan's flat-by time by default (as task 4.5 says), with "the close (16:00)" as an option. The golden numbers (29.4 / 25.5 / 45.1) are for the close; at 15:55 they are 29.2 / 24.2 / 46.6 | Both are shown correctly; the tests use the close to match the reference table |
| 2026-10-24 | 4 | The comparison plans each variant with `exit.py` **without** `--write` (exact stops and targets, refusals as the tool says them), then replays it as explicit values; the Time Machine's `--stop-rule` follows the plan's rule (or_mid / or_low / pct, else auto) | Never touches `trader/plan.json`; the 1R variant reproduces the main run exactly |
| 2026-10-24 | 4 | The stop / target preview is computed locally (stop rounded down to the cent, target half up, like exit.py) and labelled "exit.py decides"; the ATR preview is left to exit.py | Task 4.5 asks for a local preview only |
| 2026-10-24 | 4 | Not triggered yet: "Plan ahead at entry price" passes `--entry` to exit.py, as the skill allows | exit.py refuses to plan a waiting entry without a price |
| 2026-10-24 | 4 | The chart's time window, trigger marker and flat-by line use the date of the bars, not the calendar day | Found in the live check: on a weekend the window was Saturday while the bars were Friday's, so no candles showed |
| 2026-10-24 | 4 | New `gatekeeper/lab.py` (preview, skill arguments, compare, plan-file hash) and `Page.runner()` / `Page.yahoo()`; the replay-mode UI fixture moved to `tests/conftest.py` (shared by the UI test modules, `tests/` is now a package) | Keeps the page thin and the logic testable |
| 2026-10-24 | 5 | The trade-level evaluation has the 9 trade gates only (the day gates have their own panel on Home); the entry window still reaches the trade through check.py's window BLOCK, which is how the 09:40 scenario comes out NO TRADE | Matches the plan's two panels; one source of truth for the window |
| 2026-10-24 | 5 | Missing inputs fail their hard gate with an instruction ("run the Time Machine on this plan first", "not checked yet: run Size & check"), and a Time Machine run for a different plan fails too | A trade has to earn its way in: nothing passes by default |
| 2026-10-24 | 5 | Earnings gate: a report date set by hand that is today → FAIL; within `GATE_EARNINGS_WARN_SESSIONS` (3) → WARN; no date but earnings in the news → WARN (this is the replay's "earnings this week") | SEC data has no report dates; the news is the only automatic signal |
| 2026-10-24 | 5 | Reward:risk is measured from the higher of the plan's entry and a price in `trader/prices.json` under 15 minutes old (the skills' own rule); exactly at the minimum is a WARN (within 10 %) | The documented 1R plan has reward:risk 1.00 with a minimum of 1 |
| 2026-10-24 | 5 | Evaluations are stored on every change, and an unchanged one at most every `GATE_READINESS_STORE_MIN` (5) minutes | Home refreshes every 30 s; storing each identical repeat would flood the table |
| 2026-10-24 | 5 | `Decision` gained `symbol`, `readiness_id` and `overall` (the result when you decided); `Readiness` gained `symbol`. `init_db` now adds missing columns to an existing database (`add_missing_columns`), tested on a copy of the real `data/gatekeeper.db` | `create_all` never alters existing tables |
| 2026-10-24 | 5 | Size & check only runs check.py when size.py wrote an order | Otherwise check.py would check an older order left in trader/orders.json |
| 2026-10-24 | 5 | "Copy ticket for Claude" is a code block (Streamlit's copy icon) with `/trader-broker`, the order's index, its risk fingerprint and the ticket text | Gatekeeper never places orders; Claude's own gates (your typed yes, Allow once) stay in charge |
| 2026-10-24 | 5 | A test (`tests/test_wording.py`) fails on any "buy" / "sell" in the app or the engine outside a "not a buy list" style disclaimer | Exit criterion 3, kept true from now on |
| 2026-10-24 | 6 | **Fixed the Phase 1 portfolio model**: ticket.py writes positions as `ticker`, `shares` and `lots` (with each lot's total cost), not `symbol` / `qty` / `avg_price`. `Position.avg_cost` is computed from the lots; a test reads the real format | Phase 1 never saw an open position (the contracts have none), so the guess went unnoticed |
| 2026-10-24 | 6 | The What-if sandbox can also change the order's share count (not only the price) | The exit criterion "reproduces BLOCK (9 shares)" needs it; same throwaway copy, same guarantee |
| 2026-10-24 | 6 | The Risk page runs size.py (without `--write`) and check.py (`--no-write`) on every view, so it shows the current state without changing anything | Read-only by design; both take about 0.2 s |
| 2026-10-24 | 6 | Notifications: `win11toast.notify` (returns at once; its `toast()` waits for a click and would hold up the worker) with the library's default app id (Windows can silently drop toasts from an unregistered one); Telegram through the Bot API with httpx, the token never logged; failures return False, never raise. Stop and flat-by alerts are urgent | The worker must never stall or crash on a notification |
| 2026-10-24 | 6 | `JobContext.notifier`: the live worker uses the real notifier; replays have none (record only), so moving the replay slider never pops up notifications; tests plug in a fake | Task 6.9 with no side effects |
| 2026-10-24 | 6 | Task 6.9's flat-by alert rings at 15:56, not 15:55: the alerts job runs every 2 minutes (…15:54, 15:56) and the rule rings at the first check after 15:55 | The schedule from Phase 2; the skill's own example shows the same |
| 2026-10-24 | 6 | `win11toast` is an optional extra (`uv sync --extra notify`), so CI and Linux don't install it; the tests use a fake module | It's Windows-only |
| 2026-10-24 | 6 | The wording test flagged six lines on the new Positions page ("market sell", "a sell you placed", the fill form's Side field). They describe orders, not advice, but the test stays strict: the sentences now say "closing order", and only the Side field's values `["sell", "buy"]` are allowed, with the reason in the test | Phase 5's guard did its job on Phase 6 code |
| 2026-10-25 | 7 | Journal outcomes use the Time Machine's rules on the day's 5-minute bars from the entry bar on: stop checked first (a bar touching both is -1R), target at its exact R, otherwise out at the close of the last bar before `flat_by`. If the bars end earlier, the reason says `data_end`, not `flat` | Honest about short data; the recorded replay day ends at 10:45 |
| 2026-10-25 | 7 | Real R from fills: average fill price per side; an exit within 1 cent of the stop or target is labelled stop / target. A TAKEN decision without both fills is flagged `needs_fill` (no R) until the fills are recorded; the next run updates the same row (one journal row per plan) | Never guess a result for a trade you took |
| 2026-10-25 | 7 | Journal stats show two views: taken (real) trades, and every plan including the simulated skips ("if I had taken all"). The readiness card counts only real taken trades; adherence counts every decision | Answers "did following Gatekeeper help?" without inflating the real record |
| 2026-10-25 | 7 | `TradeJournal` gained `session_date`, `symbol`, `exit_time`, `needs_fill`, `created_at` (added to existing databases by Phase 5's column upgrade) | The journal stands alone without joining every query |
| 2026-10-25 | 7 | Settings edits trader/config.json through a pydantic model with bounds (unknown keys kept), a diff preview, then a timestamped backup in `data/backups/` and an atomic write. `paper` is refused in both directions, and a brand-new file is always written with `paper: true` | Going live stays your own deliberate edit |
| 2026-10-25 | 7 | Settings edits only these .env keys: CORE_TICKERS, AWAKE_IST, NOTIFY, DISABLED_JOBS, FULL_UNIVERSE_ORB and GATE_* (other lines, comments and secrets are kept as they are; secrets are never shown or written). New settings `GATEKEEPER_ENV_FILE` and `BACKUPS_DIR` say where | Keys never pass through the dashboard |

---

## Issues and blockers

| # | Opened | Phase | Issue | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| 1 | 2026-10-24 | 1 | In replay, the news fixture's price line is a 10:52 quote (366.48, +3.31% MOVING) even when the replay clock is 10:15 | Known, accepted | A limit of the recorded fixture, not of Gatekeeper; live runs use the real time |
| 2 | 2026-10-24 | 1 | The live smoke test ran on a Saturday: `alerts.clock()` and `entry.check("SPY")` returned models, but "closed (weekend)" and "no-data" | Open | Re-run `entry.check("SPY")` once during a US session (from 19:15 IST on a weekday; 20:15 IST from Nov 2) to see a live WAITING/TRIGGERED |
| 3 | 2026-10-24 | 2 | In replay, ORB scans after 10:15 find only TSLA usable (1 of 1): the 234-chart wall was recorded at 10:15, and a chart counts only with every bar up to the cutoff | Known, accepted | A limit of the recording; the 10:15 scan (41 hits) is the one that matters |
| 4 | 2026-10-24 | 2 | The live worker on a weekday session (all jobs firing against real Yahoo / SEC data) is still untested; the 10-minute live run fell on a Saturday, so only the clock ran | Open | Run `uv run python -m worker` one US session (from 18:30 IST on a weekday) with `SEC_USER_AGENT` set and a pin, then check `data\worker.log` and the heartbeats; also open the dashboard during that session and check the live tiles, the Scanner and the worker dot |
| 5 | 2026-10-24 | 3 | One full `uv run pytest` run stalled for over 10 minutes and was stopped; the next verbose run passed all 194 tests in 128 s, and the stall didn't happen again | Watching | If CI or a local run hangs again, re-run with `-v --durations=15` to see which test, and report it |
| 6 | 2026-10-24 | 3 | CI run 40106465744 failed on Windows only: `test_pin_from_the_watchlist` got pins as TSLA, AMD, NVDA instead of TSLA, NVDA, AMD (and a second test failed because the first never unpinned). `store.pinned()` sorted by `added_at`, and two pins made in the same instant shared a timestamp on Windows' ~15 ms clock | Fixed | Pins are now ordered by SQLite's rowid (insertion order); new test `test_pins_keep_insertion_order_with_equal_timestamps`; the UI test cleans up in `finally`. Found by making CI post failures as public annotations (job logs need admin rights) |
| 7 | 2026-10-24 | 6 | The real Windows toast was handed over to Windows (win11toast reported success in 0.21 s) from a replay-clock alert on a Saturday; whether it showed on your screen needs your eyes, and a live flat-by toast during a session is still to be seen | Open | Set `NOTIFY=toast` in `.env`, run `uv sync --extra notify`, then `uv run python scripts/validate.py --phase 6 --live` and look for the "Gatekeeper: test" notification; during a session, add plan alerts and watch for flat-by |
| 8 | 2026-10-25 | 7 | `validate.py --phase 7 --live`: the AAPL earnings check needs `SEC_USER_AGENT` in `.env`, which is empty here, so it failed by design; the Research page shows the same message live. Also no `trader/config.json` yet (the check passes and says so) | Open | Add `SEC_USER_AGENT=Your Name you@example.com` to `.env` and re-run `uv run python scripts/validate.py --phase 7 --live`; run `/trader-budget` once to create `trader/config.json` |

---

## Progress log

Append one line per work session (newest at the bottom).

| Date | Phase | What was done | Tests | Next step |
| --- | --- | --- | --- | --- |
| 2026-10-24 | — | Implementation guide written | — | Start Phase 0 |
| 2026-10-24 | 0 | Skills pinned as a submodule; pyproject, settings, clock (NY/IST, session phase), Home page with clock bar, placeholder worker, dev.ps1, CI workflow, README | 22 pytest pass, ruff clean, 315 upstream pass; Home renders; server health 200 | Push to GitHub so CI runs, then Phase 1 |
| 2026-10-24 | 0 | Branch pushed; CI run 40008407159 green on windows-latest and ubuntu-latest (install, lint, 315 upstream tests, Gatekeeper tests). Added COMMANDS.md; merged `phase-0-foundation` into `main` | CI green; replay commands in COMMANDS.md re-checked (41 ORB hits, TSLA 364.18, TM 29.4/25.5/45.1) | Push `main`, then Phase 1 |
| 2026-10-24 | 1 | Runner (classification, lock, isolation, timeout, replay injection), replay workspace, 30+ typed models from real output, wrappers for all 11 tools, 18 contract snapshots, NYSE calendar in the session phase | 107 pytest pass (runner 28, contracts 39, golden e2e 18, clock 19, settings 3), ruff clean; every golden number reproduced; contracts byte-identical across runs; live smoke OK (weekend) | Push `phase-1-adapter` so CI runs, then Phase 2 |
| 2026-10-24 | 1 | Branch pushed; CI run 40065638051 green on windows-latest and ubuntu-latest. Added `scripts/validate.py` (PASS / FAIL per check for phases 0 and 1, `--live` for the internet checks); merged `phase-1-adapter` into `main` | validate.py --live: 11 of 11 PASS | Push `main`, then Phase 2 |
| 2026-10-24 | 2 | SQLite store (18 tables, WAL), store functions with dedupe rules, runner timing inside the lock, worker jobs (13) on one New York schedule, live APScheduler + replay simulator, worker CLI (`--list`, `--once`, `--run-for`, `--replay`, pins), Phase 2 checks in `validate.py`, COMMANDS.md worker section | 145 pytest pass (store 11, worker 27); ruff clean; validate.py --live 16/16 PASS; replay day 07:00–16:10 with no errors (TSLA triggered 10:15 at 364.18); live worker 10 min, clean stop | Push `phase-2-worker` so CI runs, then Phase 3 |
| 2026-10-24 | 2 | Branch pushed; CI run 40074262315 green on windows-latest and ubuntu-latest (lint, 315 upstream tests, 145 Gatekeeper tests). Merged `phase-2-worker` into `main` | CI green | Push `main`; Issue 4 (a weekday live session) when convenient; then Phase 3 |
| 2026-10-24 | 3 | Chart reader (`yahoo.py`), market context (`regime.py`) and the real `regime` job; dashboard replay that drives the simulator from the time slider; Home (tiles, context label, breadth, budget, what changed, worker health), Scanner (daily / ORB tabs, filters, pin, open in Trade Lab, run scan now), Watchlist & News (pins, moves, entry status, earnings date, news stream); shared sidebar, clock bar and footer; Phase 3 checks in `validate.py`; COMMANDS.md dashboard section | 194 pytest pass (regime 25, yahoo 9, tables 5, UI smoke 10); ruff clean; validate.py --phase 3 --live 4/4 PASS (41 hits + TSLA, 3 headlines, server health, live tiles) | Push `phase-3-screens` so CI runs, then Phase 4 |
| 2026-10-24 | 3 | Phase 3 CI failed on Windows (run 40106465744). Made CI post failures as annotations + per-test timeout; the next run (40107394227) showed a pin-ordering bug from equal timestamps. Fixed (rowid order), added a test, made the UI test clean up | 195 pytest pass locally with --timeout=600 | Push the fix; when CI is green, merge to `main` |
| 2026-10-24 | 3 | CI run 40108052325 green on windows-latest and ubuntu-latest (lint, 315 upstream tests, 195 Gatekeeper tests with the 600 s timeout). Merged `phase-3-screens` into `main` | CI green | Push `main`; Issue 4 (a weekday live session, worker + dashboard) when convenient; then Phase 4 |
| 2026-10-24 | 4 | Trade Lab charts (candles with levels, odds bar, fan, histogram), `gatekeeper/lab.py` (preview, compare, plan-file hash), the Trade Lab page (symbol picker, live chart, entry, exit with preview, Time Machine, compare, external-plan banner, Go / No-Go placeholder); fixed the chart window to use the bars' date (found live); Phase 4 checks in `validate.py`; COMMANDS.md Trade Lab notes | 216 pytest pass (charts 5, lab 9, Trade Lab page 7); ruff clean; validate.py --phase 4 --live 3/3 PASS | Push `phase-4-trade-lab` so CI runs, then Phase 5 |
| 2026-10-24 | 4 | CI run 40115151903 green on windows-latest (1 min 42 s) and ubuntu-latest (52 s); both jobs concluded success (the API didn't list per-step results for this run). Merged `phase-4-trade-lab` into `main` | CI green | Push `main`; Issue 4 (a weekday live session) when convenient; then Phase 5 |
| 2026-10-24 | 5 | Go / No-Go engine (`gatekeeper/readiness.py`: 9 day + 9 trade gates, pure, thresholds in `GATE_*` settings, context builders), store (readiness with repeat-skipping, decisions), DB column upgrades for older databases, the panel / ticket / decision form (`app/components/gates.py`), Home day panel, Trade Lab Size & check + trade panel; Phase 5 checks in `validate.py`; COMMANDS.md Go / No-Go section; `.env.example` thresholds | 307 pytest pass (readiness 80, scenarios 5, Trade Lab UI 11, wording 2); ruff clean; validate.py --phase 5 --live 5/5 PASS (all four scenarios; DB upgrade on a copy of the real database) | Push `phase-5-go-no-go` so CI runs, then Phase 6 |
| 2026-10-24 | 5 | CI run 40118467980 green on windows-latest (2 min 9 s) and ubuntu-latest (1 min 15 s). Merged `phase-5-go-no-go` into `main` | CI green | Push `main`; Issue 4 (a weekday live session) when convenient; then Phase 6 |
| 2026-10-24 | 6 | Risk & Size page (limits, sizing chart, live check.py, ledger, What-if sandbox), Positions & Alerts page (flat-by countdown NY/IST, positions in R, closing ticket, fills by hand, alert rules, fired history), Trade Lab Add plan alerts, `gatekeeper/notify.py` (toast / Telegram) wired into the alerts job, `gatekeeper/sandbox.py`; fixed the Phase 1 portfolio model; a real toast handed to Windows; Phase 6 checks in `validate.py`; COMMANDS.md section | 335 pytest pass (notify 12, sandbox 5, alert worker 4, pages 7); ruff clean; validate.py --phase 6 --live 3/3 PASS | Push `phase-6-risk-positions-alerts` so CI runs; confirm the toast (Issue 7); then Phase 7 |
| 2026-10-25 | 6 | CI run 40127238785 green on windows-latest (1 min 32 s) and ubuntu-latest (52 s). Merged `phase-6-risk-positions-alerts` into `main` | CI green | Push `main`; confirm the toast (Issue 7) and a weekday live session (Issue 4) when convenient; then Phase 7 |
| 2026-10-25 | 7 | Journal engine (`gatekeeper/journal.py`: outcomes on 5-minute bars, R from fills, stats, calibration, breakdowns, readiness card), `job_eod_journal` (real / needs fill / simulated, one row per plan), Journal page (decision notes, stats, cumulative R, histogram, calibration, breakdowns, readiness card, CSV), Research page (earnings from EDGAR, Congress filings with overlap flag), Settings page (config.json editor with diff, backup and `paper` read-only; `.env` editor; diagnostics with the contract self-test); Phase 7 checks in `validate.py`; COMMANDS.md section | 372 pytest pass (journal 14, EOD 5, config / .env 12, pages 6); ruff clean; validate.py --phase 7 offline 5/5 PASS; live EDGAR check needs `SEC_USER_AGENT` (Issue 8) | Push `phase-7-journal-research` so CI runs; set `SEC_USER_AGENT` (Issue 8); then Phase 8 (optional) or the paper-trading period |
| 2026-10-25 | 7 | CI run 40165361349 green on windows-latest (2 min 38 s) and ubuntu-latest (1 min 43 s). Merged `phase-7-journal-research` into `main` | CI green | Push `main`; set `SEC_USER_AGENT` and re-run `validate.py --phase 7 --live` (Issue 8); Issues 4 and 7 when convenient; then Phase 8 (optional) or the paper-trading period |
