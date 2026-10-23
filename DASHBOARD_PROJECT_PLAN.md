# Gatekeeper: Project Plan

> **Every trade has to earn its way in.**

**Gatekeeper** is an end-to-end Python project that runs the 11 `trader-*` skills on a schedule,
stores what they find, and shows it on one dashboard. Its job is to answer one
question honestly, many times a day:

> **Should I be trading right now and, if so, is this specific trade worth taking?**

Status: plan only (no code yet). Target platform: Windows 10, Python 3.12.

---

## Table of contents

1. [Goals and non-goals](#1-goals-and-non-goals)
2. [Key design decisions](#2-key-design-decisions)
3. [Tech stack](#3-tech-stack)
4. [Architecture](#4-architecture)
5. [Project structure](#5-project-structure)
6. [The skill adapter layer](#6-the-skill-adapter-layer)
7. [The background worker and its schedule](#7-the-background-worker-and-its-schedule)
8. [Data model (SQLite)](#8-data-model-sqlite)
9. [The Go / No-Go engine](#9-the-go--no-go-engine)
10. [Dashboard pages](#10-dashboard-pages)
11. [Replay mode (offline, deterministic)](#11-replay-mode-offline-deterministic)
12. [Order execution policy](#12-order-execution-policy)
13. [Configuration and secrets](#13-configuration-and-secrets)
14. [Testing strategy](#14-testing-strategy)
15. [Milestones and acceptance criteria](#15-milestones-and-acceptance-criteria)
16. [Risks and mitigations](#16-risks-and-mitigations)
17. [Future extensions](#17-future-extensions)

---

## 1. Goals and non-goals

### Goals
- **One screen for the live market:** NYSE status (in New York time and IST), market context, scanner hits, news flags, open positions and alerts.
- **A visual trade lab:** for a chosen ticker, show the candlestick chart with the opening range, entry trigger, stop and target, and the Time Machine's odds and fan chart.
- **A clear Go / No-Go verdict:** each verdict comes with the reasons behind it, at two levels: the day (should I trade at all?) and the trade (is this one worth it?).
- **Automation:** run the skills on a schedule in the background, so the dashboard is always current without anyone clicking.
- **Journal and statistics:** record every decision, including skipped trades, and measure expectancy in R, win rate, and whether the Time Machine's verdicts matched what actually happened.
- **Replay mode:** run the whole system on recorded data (Oct 19, 2026, TSLA) for development, demos and testing.

### Non-goals (v1)
- No automatic order placement. The dashboard decides; you act (see [Section 12](#12-order-execution-policy)).
- No live-money trading from the dashboard, ever, in v1.
- No short selling, options, margin or crypto (the skills don't support them).
- No Indian markets (NSE/BSE): the skills are US-only.
- No real-time tick data. Data is free, delayed Yahoo bars.
- No price predictions or "buy" labels. Wording stays factual, as in the skills.

---

## 2. Key design decisions

| # | Decision | Why |
| --- | --- | --- |
| D1 | **Call the skill scripts as subprocesses with `--json`. Do not import or modify them.** | Every script already has a JSON output mode (verified: scanner, news, entry, exit, timemachine, budget, risk, alerts, broker `show`, analyst, pelosi). The skills stay the single source of truth, upstream updates drop in, and Claude Code chat keeps working on the same files. |
| D2 | **Run every subprocess with the working directory set to the project root, so the dashboard and Claude chat share one `trader/` folder.** | The scripts read and write `trader/*.json` relative to their working directory. Sharing it means you can plan a trade in Claude chat and see it on the dashboard instantly, and the other way round. |
| D3 | **Separate the worker process from the UI process.** | Streamlit re-runs the page script on every interaction. Long jobs (a whole-universe scan takes about 4 minutes) must not live inside it. A worker on APScheduler runs jobs; the UI only reads results. |
| D4 | **SQLite as the shared store**, plus the skills' own `trader/` JSON files. | No server to install, a single file, easy to back up. Skill files are the live state; SQLite holds history (runs, hits, verdicts, journal). |
| D5 | **Pin the skills version** with a `vendor/day-trader-skill` git submodule; `SKILLS_DIR` can point at `~/.claude/skills` instead. | The dashboard parses the scripts' JSON output, so an upstream change could break it. Pinning plus contract tests catch that. |
| D6 | **The Go / No-Go output is a checklist of gates, not a numeric "score".** | A score like "73/100" implies precision that isn't there. Gates with reasons ("Blocked: earnings tonight") are honest and actionable. |
| D7 | **Read-only first. Paper orders only as a late, optional milestone, behind the same gates the skills use.** | See [Section 12](#12-order-execution-policy). |
| D8 | **All times are stored in UTC, computed in New York time, and displayed in both New York time and IST.** | The skills reason in New York time. You live in IST, and the gap between them changes twice a year. |

---

## 3. Tech stack

All Python. Versions are minimums.

| Layer | Choice | Role |
| --- | --- | --- |
| Language | **Python 3.12** | Already installed |
| Env & packaging | **uv** + `pyproject.toml` | Fast installs, lockfile; also needed for Alpaca's MCP server later |
| Dashboard UI | **Streamlit ≥ 1.40** | Multi-page app, `st.fragment(run_every=...)` for auto-refresh, `st.dataframe`, forms |
| Charts | **Plotly ≥ 5.24** | Candlesticks, fan chart, histograms, equity curve in R |
| Data wrangling | **pandas ≥ 2.2** | Tables, bar data, journal statistics |
| Validation | **pydantic ≥ 2.8** + **pydantic-settings** | Typed models for every skill's JSON; settings from `.env` |
| Scheduler | **APScheduler ≥ 3.10** (`BackgroundScheduler`, cron triggers in `America/New_York`) | Runs the skills on a schedule |
| Database | **SQLite** via **SQLModel ≥ 0.0.22** (SQLAlchemy 2) | History, journal, run log |
| HTTP (dashboard's own data) | **httpx ≥ 0.27** | Bars for charts, market-context quotes |
| Caching | `functools.lru_cache` / `st.cache_data(ttl=...)` | Avoids hammering Yahoo |
| File locking | **filelock ≥ 3.15** | Only one process writes `trader/*.json` at a time |
| Time zones | stdlib `zoneinfo` + **tzdata** | Required on Windows, which has no bundled IANA time-zone data |
| Notifications (optional) | Windows toast via **win11toast**, or a Telegram bot via httpx | Pushes alerts outside the browser |
| Tests | **pytest**, **pytest-cov**, **freezegun** | Contract tests on fixtures, gate logic, time zones |
| Lint / format | **ruff** | One tool for both |
| Broker (milestone M8, optional) | **alpaca-py** (paper only) | See [Section 12](#12-order-execution-policy) |

**Why Streamlit over Dash or FastAPI + React:** this is a single-user desk tool.
Streamlit gets the most UI per line of Python, and its weak spot, the re-run
model, is handled by moving all real work into the worker (D3). If you later
need several users or finer layout control, the `gatekeeper/` package is UI-agnostic
and can sit behind FastAPI and Dash without changes.

---

## 4. Architecture

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                          Streamlit UI  (app/)  :8501                           │
│  Market │ Scanner │ Watchlist & News │ Trade Lab │ Risk & Size │ Positions &   │
│  Alerts │ Journal │ Research │ Settings │ Replay                               │
│        reads ▲ SQLite + trader/*.json        on-demand actions ▼ (via runner)  │
└────────────────────────────────────────────────────────────────────────────────┘
                 │                                          │
                 ▼                                          ▼
┌───────────────────────────────┐        ┌───────────────────────────────────────┐
│   gatekeeper/ (core library)  │◄───────│   worker/  APScheduler process         │
│  runner   → subprocess + lock │        │  cron jobs in America/New_York:        │
│  skills/* → typed wrappers    │        │  scan, news, entry, alerts, pelosi...  │
│  readiness → Go/No-Go gates   │        │  writes results to SQLite              │
│  regime   → market context    │        └───────────────────────────────────────┘
│  yahoo    → bars for charts   │
│  journal  → stats, expectancy │
│  db       → SQLModel models   │
└───────────────────────────────┘
          │ subprocess (cwd = project root, sys.executable, --json)
          ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│  day-trader-skill scripts (vendor/ or ~/.claude/skills)                        │
│  scan.py news.py entry.py exit.py timemachine.py size.py check.py              │
│  ticket.py alerts.py facts.py ptr.py                                           │
│          read/write ▼                                                          │
│  trader/  config.json watchlist.json entry.json plan.json orders.json ...      │
│           state/{news,risk,broker,alerts,pelosi}.json   ◄── also used by Claude│
└────────────────────────────────────────────────────────────────────────────────┘
          │ HTTPS (free public data)
          ▼
   Yahoo Finance · Nasdaq Trader · SEC EDGAR · House Clerk
```

**Data flow for one trade:**
1. The worker's ORB scan job runs `scan.py orb --json`, stores the hits, and the Scanner page updates.
2. You click a hit. Trade Lab runs `news.py --tickers X --json` and `entry.py check X --json`, and draws the chart.
3. On a trigger you click "Plan exit". This runs `exit.py plan --write --json`, then `timemachine.py run --write --json --until <flat_by>`.
4. "Size & check" runs `size.py --write --json`, then `check.py --json`.
5. The Go / No-Go panel combines everything: **GO / CAUTION / NO TRADE** with reasons.
6. You place the trade yourself (broker app or Claude chat `/trader-broker`) and log the decision on the dashboard. The journal records it, including if you skipped.

---

## 5. Project structure

```
trading_skills/                         # project root = working dir for all scripts
├── pyproject.toml
├── uv.lock
├── .env.example                        # settings template (no secrets committed)
├── .gitignore                          # .env, trader/, data/, *.db
├── README.md
├── DAY_TRADER_GUIDE.md                 # existing usage guide
├── DASHBOARD_PROJECT_PLAN.md           # this file
│
├── vendor/
│   └── day-trader-skill/               # git submodule, pinned commit (D5)
│
├── trader/                             # shared live state (written by skills; gitignored)
│
├── data/
│   ├── gatekeeper.db                   # SQLite
│   └── cache/                          # cached bars
│
├── gatekeeper/                         # core library (UI-agnostic)
│   ├── __init__.py
│   ├── settings.py                     # pydantic-settings: paths, mode, schedule toggles
│   ├── clock.py                        # NY/IST conversion, session phase, NYSE calendar (via alerts.py clock)
│   ├── runner.py                       # SkillRunner: subprocess, timeout, lock, JSON parse, RunLog
│   ├── skills/
│   │   ├── models.py                   # pydantic models for each tool's JSON
│   │   ├── scanner.py                  # universe(), daily(), orb()
│   │   ├── news.py                     # check(tickers, hours)
│   │   ├── entry.py                    # check(symbol, setup, level, interval, min_volume_x)
│   │   ├── exit.py                     # plan(stop, target, flat_by), show()
│   │   ├── timemachine.py              # run(until, replays, seed)
│   │   ├── budget.py                   # size(limit)
│   │   ├── risk.py                     # check(no_write)
│   │   ├── broker.py                   # show(), log(), flatten(), fill()  (no broker calls)
│   │   ├── alerts.py                   # clock(), quote(), add_from_plan(), check(), list()
│   │   ├── analyst.py                  # facts(tickers, quarters)
│   │   └── pelosi.py                   # index(), new()
│   ├── yahoo.py                        # bars for charts + index/VIX quotes (cached, polite)
│   ├── regime.py                       # market context (SPY/QQQ/IWM trend, VIX, breadth from scan)
│   ├── readiness.py                    # Go / No-Go gate engine (Section 9)
│   ├── journal.py                      # decisions, outcomes, R stats, verdict calibration
│   └── db.py                           # SQLModel tables + session helpers
│
├── worker/
│   ├── __main__.py                     # `python -m worker` → starts scheduler
│   └── jobs.py                         # job functions + schedule (Section 7)
│
├── app/
│   ├── Home.py                         # `streamlit run app/Home.py` → Market Overview
│   ├── pages/
│   │   ├── 1_Scanner.py
│   │   ├── 2_Watchlist_News.py
│   │   ├── 3_Trade_Lab.py
│   │   ├── 4_Risk_Size.py
│   │   ├── 5_Positions_Alerts.py
│   │   ├── 6_Journal.py
│   │   ├── 7_Research.py
│   │   └── 8_Settings.py
│   └── components/
│       ├── charts.py                   # candlestick+levels, fan chart, histograms, R curve
│       ├── gates.py                    # Go/No-Go panel renderer
│       ├── clock_bar.py                # NY / IST clock + session phase banner
│       └── tables.py
│
├── replay/
│   ├── fixtures -> vendor/day-trader-skill/tests/fixtures
│   └── workspace/                      # separate working dir so replay never touches live trader/
│
├── scripts/
│   ├── dev.ps1                         # starts worker + UI together on Windows
│   └── snapshot_contracts.py           # regenerates golden JSON from fixtures
│
└── tests/
    ├── contracts/                      # golden JSON outputs per tool (from fixtures)
    ├── test_runner.py
    ├── test_models_contract.py
    ├── test_readiness.py
    ├── test_clock.py
    └── test_journal.py
```

---

## 6. The skill adapter layer

### 6.1 `SkillRunner` (gatekeeper/runner.py)

One function every call goes through:

```python
result = runner.run(
    tool="timemachine",               # maps to <SKILLS_DIR>/trader-timemachine/timemachine.py
    args=["run", "--write", "--until", "15:55"],
    json_out=True,                    # appends --json, parses stdout
    timeout=300,
    writes_state=True,                # takes the trader/ file lock
)
# -> RunResult(ok, exit_code, data: dict|None, stdout, stderr, started_at, duration_s)
```

Rules:
- Use `sys.executable`, never `python3` (Windows).
- `cwd` = project root (live) or `replay/workspace/` (replay mode).
- Env: `PYTHONIOENCODING=utf-8`, `PYTHONUTF8=1`, plus `SEC_USER_AGENT` from settings.
- In replay mode, inject `--now "<replay time>"` and the right `--offline` path per tool (the formats differ: a DIR for news, analyst and alerts; a FILE or PATH for scanner, entry, timemachine and exit; a FILE for pelosi).
- **Exit codes are data, not errors.** Several tools use exit 1 for "nothing found or nothing new" (scanner, news, alerts `check`, risk "something blocked", pelosi `new`). The wrapper maps each tool's exit codes to a status: `ok | empty | blocked | error`.
- A `filelock` on `trader/.gatekeeper.lock` for any call with `writes_state=True`, so the worker and UI never write the same file at once. Read-only calls (`--no-write`, `show`, `clock`) skip the lock.
- Every run is logged to the `skill_run` table (tool, args, status, duration, a stderr excerpt) for the Settings → Diagnostics view.

### 6.2 Typed wrappers (gatekeeper/skills/*.py)

Each wrapper is a thin function that builds the args and returns a pydantic
model. Example:

```python
def orb_scan(at: str | None = None, symbols: list[str] | None = None) -> ScanResult: ...
def entry_check(symbol: str, setup="orb", level=None, interval="5m", min_volume_x=None, write=False) -> EntryStatus: ...
def plan_exit(stop="or-mid", target="2R", flat_by=None, write=True) -> ExitPlan: ...
def time_machine(until: str, replays=10_000, seed=19, write=True) -> TimeMachineResult: ...
def size(limit: float | None = None, write=True) -> SizeResult: ...
def risk_check(no_write=False) -> RiskReport: ...
```

**Building the models:** in milestone M1, run every tool against the repo's
fixtures with `--offline --now ... --json`, save the outputs to
`tests/contracts/*.json`, and write the pydantic models from those real outputs.
Use `model_config = ConfigDict(extra="allow")` so a new field upstream doesn't
break parsing; contract tests catch removed or renamed fields.

### 6.3 What the dashboard computes itself (new code)

The skills don't expose everything a dashboard needs, so three small modules
are added:

| Module | Why it's needed | Data |
| --- | --- | --- |
| `gatekeeper/yahoo.py` | The scripts fetch bars internally but don't return them; the charts need them | Yahoo v8 chart, `range=1d&interval=5m` (today) and `range=60d&interval=5m` (context), cached 60 s, same polite user agent and backoff as the skills |
| `gatekeeper/regime.py` | Day-level context the skills don't cover | SPY, QQQ, IWM: today's change, price vs. VWAP and the opening range, daily close vs. the 20- and 50-day average; `^VIX` level and change; **breadth** = share of usable charts that broke the opening range up (from the ORB scan's counts) |
| `gatekeeper/journal.py` | Learning loop | Your logged decisions plus outcomes |

Regime outputs are **context, labelled as such**, never a signal on their own.

---

## 7. The background worker and its schedule

`python -m worker` starts an APScheduler `BackgroundScheduler(timezone="America/New_York")`.
Every job checks `clock.session_phase()` first and skips on weekends, NYSE
holidays and early-close afternoons. Every job has `max_instances=1` and
`coalesce=True`.

| Job | When (New York time) | IST before Nov 1, 2026 / from Nov 1 | Runs | Stores |
| --- | --- | --- | --- | --- |
| `universe` | Sun 18:00 | Mon 03:30 / 04:30 | `scan.py universe` | count |
| `analyst_watchlist` | Mon to Fri 07:00 | 16:30 / 17:30 | `facts.py <your core list> --json` | `earnings_snapshot` |
| `daily_scan` | Mon to Fri 08:30 | 18:00 / 19:00 | `scan.py daily --json` | `scan_run`, `scan_hit` |
| `premarket_news` | Mon to Fri 08:45 | 18:15 / 19:15 | `news.py --json` (watchlist + core list) | `news_item` |
| `regime` | every 5 min, 09:30 to 16:00 | — | `gatekeeper/regime.py` | `regime_snapshot` |
| `orb_scan` | 09:50, 10:00, 10:15, then every 15 min until `no_entries_after` | 19:20... / 20:20... | `scan.py orb --json --symbols <core list>`; a full universe scan once at 10:15 if enabled | `scan_run`, `scan_hit` |
| `intraday_news` | every 15 min, 09:30 to 16:00 | — | `news.py --json` | `news_item` (new only) |
| `entry_watch` | every 1 min, 09:45 to `no_entries_after` | — | `entry.py check <T> --json` for each **pinned** ticker | `entry_signal` (status changes only) |
| `alerts_check` | every 2 min, 09:30 to 16:00 | — | `alerts.py check --json` | `alert_fired` → toast/Telegram |
| `quotes` | every 5 min while a position or plan exists | — | `alerts.py quote --holdings --write` | `trader/prices.json` |
| `pelosi` | Mon to Fri, hourly 08:00 to 20:00 | — | `ptr.py new --json` | `pelosi_filing` |
| `eod_journal` | Mon to Fri 16:10 | 01:40 / 02:40 | reconcile the day: plans, decisions, outcomes from bars | `trade_journal` |

**Load budget:** with a 15-ticker core list, an intraday hour is about 4 ORB scans
(1 to 2 requests each plus confirmations), 4 news checks (about 30 requests),
60 entry checks × pinned tickers, and 30 alert checks. That is well within
polite limits. The **full-universe** ORB scan (about 300 + 200 requests, 4
minutes) is off by default and runs at most once a day.

**Windows notes:** the worker must keep running, so disable sleep while the
market is open (`powercfg`) or run it on an always-on machine. `scripts/dev.ps1`
starts both processes. A later option is to register the worker as a Task
Scheduler task that starts at login.

---

## 8. Data model (SQLite)

Raw skill JSON is always kept (`payload` columns) so nothing is lost when a
model changes.

| Table | Key columns |
| --- | --- |
| `skill_run` | id, tool, args, mode (live/replay), status, exit_code, started_at, duration_s, stderr_excerpt |
| `scan_run` | id, run_id, mode (daily/orb), as_of, universe, scanned, failed, usable, partial |
| `scan_hit` | id, scan_run_id, symbol, setup, price, range_high, range_low, pct_over, hit_time, rank, payload |
| `news_item` | id, symbol, published_at, source, title, url, tags, important_8k_item, moving_pct, payload |
| `earnings_snapshot` | symbol, as_of, period_end, revenue, rev_yoy, eps, eps_yoy, gross_m, op_m, net_m, flags, next_report_date (manual or from news) |
| `regime_snapshot` | ts, spy_chg, qqq_chg, iwm_chg, spy_vs_vwap, vix, vix_chg, breadth_orb_up, label |
| `entry_signal` | id, symbol, setup, status, level, last_close, trigger_time, trigger_price, ts |
| `plan` | id, symbol, date, entry, stop, stop_rule, target, target_r, risk_per_share, flat_by, payload |
| `tm_result` | id, plan_id, seed, replays, until, p_target, p_stop, p_neither, p_green, avg_r, hist_fired, hist_target, hist_stop, hist_neither, verdict, payload |
| `risk_verdict` | id, plan_id, ts, order_index, status (PASS/BLOCK), max_loss, rr, reasons, payload |
| `readiness` | id, ts, scope (day/trade), plan_id, overall (GO/CAUTION/NO_TRADE), gates_json |
| `decision` | id, plan_id, ts, action (TAKEN/SKIPPED), reason_note, followed_rules (bool) |
| `trade_journal` | id, plan_id, decision_id, entry_fill, exit_fill, exit_reason (target/stop/flat/manual), r_result, simulated (bool), notes |
| `alert_fired` | id, rule_id, symbol, kind, price, ts, notified |
| `pelosi_filing` | doc_id, member, filed, rows_json, overlaps_holdings |

**Shadow outcomes for skipped trades:** `eod_journal` plays every SKIPPED plan
forward on the day's real 5-minute bars (stop first if a bar touches both, as
the Time Machine does) and stores `r_result` with `simulated=true`. This shows
whether skipping was the right call, and it is how the Time Machine filter gets
validated without risking money.

---

## 9. The Go / No-Go engine

`gatekeeper/readiness.py` evaluates **gates**. Each gate returns
`PASS | WARN | FAIL`, a one-line reason, and its source. Overall result:
- **NO TRADE** if any hard gate FAILs
- **CAUTION** if no FAIL but any WARN (or any soft gate fails)
- **GO** otherwise

The engine never says "buy". GO means *"your rules allow this, and the honest
odds are not against it."*

### 9.1 Day-level gates ("Should I trade today?")

| Gate | Hard/Soft | FAIL | WARN | Source |
| --- | --- | --- | --- | --- |
| Market open | Hard | Closed, holiday, weekend | Early-close day | `alerts.py clock` |
| Entry window | Hard | Before `no_entries_before` / after `no_entries_after` | < 15 min left | config + clock |
| Awake window (IST) | Soft | `flat_by` falls outside your set awake hours in IST | — | settings |
| Daily loss budget | Hard | Day's risk used ≥ `max_daily_loss_usd` | ≥ 66% used | `trader/state/broker.json` |
| Trades left | Hard | `max_trades_per_day` reached | 1 left | broker log |
| PDT (if on) | Hard | 3 day trades in 5 business days | 2 | risk check |
| Market context | Soft | — | VIX up > 10% today, or SPY below VWAP and its opening-range low | `regime_snapshot` |
| Breadth | Soft | — | < 10% of usable charts broke the opening range up (weak tape for long breakouts) | ORB scan |
| Your recent form | Soft | — | Last 5 journal trades ≤ −3R total, or rules broken in 2 of the last 5 | `trade_journal` |

### 9.2 Trade-level gates ("Is this trade worth taking?")

| Gate | Hard/Soft | FAIL | WARN | Source |
| --- | --- | --- | --- | --- |
| Entry triggered | Hard | Not triggered / expired | Trigger more than one bar old | `entry.py check` |
| News clean | Hard | `!` 8-K today (2.02, 4.02, 1.03, 3.01, 1.05), halt tag | Legal/regulatory/risk tag, MOVING with no headline | `news_item` |
| Earnings outside the trade | Hard | Report before the next open and the trade could be held | Report within 3 sessions | analyst + news |
| Plan valid | Hard | `exit.py` refused | Risk < 0.3% of price (tight) | `plan` |
| Reward:risk | Hard | < `min_reward_risk` at the **fresh** price | Within 10% of the minimum | risk check |
| **Time Machine verdict** | Hard | "Leans/Strongly toward the stop" | "Coin flip" / "Close to break-even", or > 40% neither | `tm_result` |
| History agrees | Soft | — | History target-rate below break-even while the replays lean target, or fewer than 15 historical fires | `tm_result` |
| Risk check | Hard | Any BLOCK | Any warning (stale price, LIVE account) | `check.py` |
| Size sane | Hard | `size.py` refused | Size bound by cash or position cap rather than max loss | `size.py` |

All thresholds live in `settings` (and on the Settings page), not in code.

### 9.3 Panel rendering

```
┌──────────────── TRADE: TSLA long · ORB 15m · Mon 2026-10-19 10:15 ET (19:45 IST) ────────────────┐
│  OVERALL:  ⚠ CAUTION                                                                            │
│  ✔ Entry triggered        10:15 at 364.18 (bar 8 closed above 362.18)                           │
│  ✔ News clean             no 8-K today; 3 headlines tagged earnings, deal                        │
│  ⚠ Earnings               reports this week: flat by 15:55, do not hold overnight               │
│  ✔ Plan                   stop 358.32 (or-mid) · target 370.04 (1R) · risk 5.86/share            │
│  ⚠ Time Machine           Close to a coin flip: target 29.4% vs stop 25.5%, neither 45.1% (seed 19)│
│  ⚠ History                33 fires: 13 target / 15 stop / 5 neither · avg −0.06R                │
│  ✔ Risk check             PASS · 8 sh · max loss $46.88 / $50 · day 0/3 trades, $0/$150           │
│  [ Log: Taken ]  [ Log: Skipped ]  [ Open in Claude: /trader-broker ]                            │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 10. Dashboard pages

Every page shows a **top clock bar**: `NY 10:15 · IST 19:45 · Session: OPEN (entry window, 5h 15m left) · Mode: LIVE/REPLAY · Data: Yahoo delayed`.
Live panels refresh via `st.fragment(run_every="30s")`; the worker does the heavy lifting.

### Home: Gatekeeper Desk, Market Overview (`app/Home.py`)
- **Day-level Go / No-Go panel** (Section 9.1).
- Index tiles: SPY, QQQ, IWM (price, % change, vs. VWAP), VIX, with intraday sparklines.
- Breadth gauge: % of usable charts above their opening range; ORB hits over time (line).
- Today's budget: risk used vs. `max_daily_loss_usd`, trades used vs. max (progress bars).
- "What changed" feed: the latest scan hits, important news, alerts fired, Pelosi filings.
- Worker health: the last successful run of each job and any failures.

### 1. Scanner
- Tabs: **Pre-market (daily)** and **Opening-range breakouts**.
- Table: symbol, setup, price, range, % over, hit time, liquidity rank, news badge, earnings badge.
- Filters: setup, min price, min volume, "core list only".
- Buttons: **Pin** (adds to entry watch), **Open in Trade Lab**, **Run scan now** (on demand, with a spinner).
- A small heatmap of setups by sector is a later extension (needs sector data).

### 2. Watchlist & News
- The pinned list, each row showing: last price, % vs. yesterday's close, MOVING flag, entry status (WAITING x% away / TRIGGERED / EXPIRED), news count and tags.
- A news stream, newest first, in New York time and IST, with tag chips, `!` 8-K badges and links.
- Earnings calendar strip for the pinned tickers (from the analyst plus a manual date field).

### 3. Trade Lab (the core page)
1. **Chart:** 5-minute candlesticks for today plus volume, a shaded opening-range band, a marker on the trigger bar, horizontal lines for entry, stop and target, and a vertical line at flat-by.
2. **Entry panel:** status from `entry.py`; controls for setup (orb/level), interval (5m/1m), volume multiple.
3. **Exit panel:** stop rule (or-mid / or-low / pct / atr / price) and target (1R / 1.5R / 2R / price), with a live preview of risk per share and reward:risk. **Plan exit** runs `exit.py plan --write`.
4. **Time Machine panel:** **Run** with `--until = flat_by`. Shows:
   - the four odds as stacked bars (target / stop / neither / green);
   - a **fan chart** from `mc` bands and sample paths, with stop and target lines;
   - a histogram of the price at `--until` (24 bins, from `mc`);
   - the history line and the verdict line, **verbatim**, plus the seed.
   - **Compare plans:** run 2 to 4 stop/target variants side by side (each one a separate run with the same seed).
5. **Trade-level Go / No-Go panel** (Section 9.2), plus **Log decision** buttons.

### 4. Risk & Size
- Your config's limits, shown as a card.
- `size.py` output: the four limits as a bar chart with the binding one highlighted, shares, dollars, max loss.
- `check.py` output: PASS/BLOCK per order with reasons; today's risk ledger.
- A **"What if"** slider for the price (writes a temporary `prices.json` in a sandbox working directory, never the live one) to show how a run-up shrinks the size and reward:risk.

### 5. Positions & Alerts
- Positions from `trader/portfolio.json` (and, from M8, from Alpaca paper): quantity, average price, last price, distance to stop and target in R, time left to flat-by.
- **Flat-by countdown** in New York time and IST; it turns red 10 minutes before.
- Alert rules (`alerts.py list`) with add/reset forms; the fired-alert history.
- **Flatten helper:** runs `ticket.py flatten` and `check.py` and shows the ticket to execute in your broker or Claude chat.

### 6. Journal & Performance
- A decision log: every plan, TAKEN or SKIPPED, with reasons and whether rules were followed.
- Metrics (taken trades, and separately simulated skipped trades):
  - number of trades, win rate, average win and loss in R, **expectancy (R)**, profit factor, max drawdown in R, longest losing streak;
  - cumulative R curve (taken vs. "if I had taken everything");
  - R distribution histogram;
  - **Time Machine calibration:** realised win rate grouped by verdict bucket (Strongly target / Leans target / Coin flip / Leans stop). If "Leans target" doesn't beat "Coin flip" over 40+ trades, the filter isn't helping you, and the dashboard says so;
  - results by setup, by entry time bucket (9:45 to 10:30, 10:30 to 12:00, ...), by weekday;
  - rule-adherence rate.
- A **paper → live readiness card**: the Phase 3 criteria from the guide (40+ trades, expectancy > 0, rule adherence ≥ 95%). Display only.
- Export to CSV.

### 7. Research
- **Earnings (analyst):** pick tickers to see quarterly revenue and EPS bars with year-on-year change, margin lines, TTM, flags (derived Q4, data lag, one-offs), and links to the 10-Q and press release.
- **Congress (Pelosi):** the latest PTRs, a filterable table (member, ticker, buy/sell, amount range, days to disclose), and an overlap flag with your holdings and watchlist. A banner explains the 45-day reporting lag.

### 8. Settings
- An editor for `trader/config.json` (with validation, a diff preview, and a backup before saving). Changing `paper` to `false` is **not possible from the UI**.
- Dashboard settings: core ticker list, awake hours in IST, gate thresholds, which jobs are on, notification channel.
- Diagnostics: the `skill_run` log, the last error per tool, the skills version and commit, and a **Run contract self-test** button.

---

## 11. Replay mode (offline, deterministic)

The skills repo ships real recorded data for **Monday, Oct 19, 2026**:

| Fixture | Use |
| --- | --- |
| `trader-scanner/wall5m-2026-10-19.json.gz` | ORB scan of 234 tickers at 10:15 (42 hits, TSLA among them) |
| `trader-scanner/daily-spark-2026-10-19.json` | Pre-market daily scan |
| `trader-entry/TSLA-2026-10-19-5m.json` | TSLA bars for the entry timer and chart |
| `trader-timemachine/TSLA-60d5m.json.gz` | 60 days of TSLA bars for the Time Machine |
| `trader-news/*` | TSLA, AAPL and KO headlines and 8-Ks |
| `trader-analyst/*`, `trader-pelosi/*`, `trader-budget/*`, `trader-risk/*` | Earnings, PTRs, plans, orders |

A **Replay** toggle in the sidebar:
- switches the runner's working directory to `replay/workspace/` (copied fresh from a seed config), so live `trader/` state is never touched;
- injects `--now` from a **time slider** (09:30 to 16:00 on 2026-10-19) and the matching `--offline` paths;
- makes `gatekeeper/yahoo.py` serve bars from the fixture files instead of the network.

Dragging the slider from 10:10 to 10:15 should flip TSLA from WAITING to
TRIGGERED at 364.18, and the Time Machine should reproduce 29.4% / 25.5% /
45.1% with seed 19. **These exact numbers become automated acceptance tests.**

---

## 12. Order execution policy

The skills enforce three gates before any order: a risk PASS on the exact
order, your typed "yes", and Claude's "Allow once" card. A Python dashboard
that called a broker API directly would bypass the last two. So:

| Milestone | What the dashboard may do with orders |
| --- | --- |
| M1 to M7 | **Nothing.** It prepares the ticket (`ticket.py show`) and you place it in your broker or via Claude chat `/trader-broker`. Then you log the fill on the dashboard (`ticket.py fill` / `result`). |
| M8 (optional) | **Alpaca paper only** via alpaca-py, behind: (1) a `check.py` PASS for that order's fingerprint today; (2) a confirm dialog where you **type** `BUY 8 TSLA`, which is recorded with `ticket.py approve --reply`; (3) a second confirm button. The broker client is constructed with `paper=True` hard-coded, and the module refuses to start if the keys belong to a live account. No live trading in this plan. |

Never automated by any job: placing, cancelling or replacing orders. Jobs only read and alert.

---

## 13. Configuration and secrets

`.env` (gitignored), loaded by `gatekeeper/settings.py`:

```ini
GATEKEEPER_MODE=live                # live | replay
SKILLS_DIR=vendor/day-trader-skill  # or C:/Users/Lenovo/.claude/skills
PROJECT_ROOT=.                      # cwd for skill scripts (shared trader/)
DB_URL=sqlite:///data/gatekeeper.db
SEC_USER_AGENT=Your Name you@example.com
CORE_TICKERS=TSLA,NVDA,AMD,AAPL,MSFT,META,AMZN,GOOGL,NFLX,PLTR,COIN,SMCI,SPY,QQQ
AWAKE_IST=18:30-23:30
FULL_UNIVERSE_ORB=false
NOTIFY=toast                        # none | toast | telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
# M8 only (paper):
ALPACA_API_KEY=
ALPACA_SECRET_KEY=
```

- Trading rules stay in `trader/config.json`, the skills' own file, so chat and dashboard share them.
- No secrets are ever written to SQLite, logs or the UI.
- Streamlit binds to `localhost` only (`server.address = "127.0.0.1"` in `.streamlit/config.toml`).

---

## 14. Testing strategy

| Level | What | How |
| --- | --- | --- |
| Upstream | The skills' own suite still passes on the pinned commit | `python -m unittest discover -s vendor/day-trader-skill/tests` in CI |
| Contract | Each tool's `--json` output, run on fixtures, parses into our models and matches the golden files | `tests/test_models_contract.py`, with goldens from `scripts/snapshot_contracts.py` |
| Golden numbers | Replay reproduces the documented results: 42 ORB hits at 10:15, TSLA trigger 364.18, plan 358.32 / 370.04, Time Machine 29.4 / 25.5 / 45.1 (seed 19), 8 shares, max loss $46.88, risk PASS; 9 shares → BLOCK | `tests/test_replay_e2e.py` |
| Gates | Every gate's PASS/WARN/FAIL boundaries | Table-driven tests in `test_readiness.py` |
| Clock | NY↔IST across the Nov 1, 2026 and Mar 14, 2027 daylight-saving changes, holidays, early closes | `test_clock.py` with freezegun |
| Runner | Exit-code mapping, timeouts, lock contention, non-JSON stdout, Windows paths with spaces | `test_runner.py` |
| Journal | Expectancy, drawdown, calibration math on synthetic trades | `test_journal.py` |
| UI smoke | Every page loads in replay mode without exceptions | `streamlit.testing.v1.AppTest` |

CI: GitHub Actions on `windows-latest` and `ubuntu-latest`, Python 3.12,
`uv sync && ruff check && pytest`. No network access in CI: replay only.

---

## 15. Milestones and acceptance criteria

| # | Milestone | Deliverables | Done when |
| --- | --- | --- | --- |
| **M0** | Skeleton | `pyproject`, uv env, folders, settings, submodule pinned, ruff, pytest, CI | `uv run pytest` is green; `streamlit run app/Home.py` shows an empty page with the clock bar |
| **M1** | Adapter + contracts | `runner.py`, all 11 wrappers, pydantic models, golden contracts, replay working directory | Every wrapper returns a typed model on fixtures; the golden-number test passes |
| **M2** | Storage + worker | SQLModel tables, `worker/jobs.py`, schedule, session-phase guards, run log | In replay with a simulated clock, jobs fire in order and fill the tables; no overlapping writes |
| **M3** | Market Overview + Scanner + News | Home, Scanner, Watchlist & News pages; regime module | In replay at 10:15: 42 ORB hits listed with TSLA; TSLA news shows the three documented headlines |
| **M4** | Trade Lab | Chart, entry/exit controls, Time Machine panel with fan chart and comparison | Replay TSLA: trigger marker at 10:15 / 364.18; plan lines correct; Time Machine numbers match exactly |
| **M5** | Go / No-Go engine | `readiness.py`, day and trade panels, thresholds in settings | The TSLA replay shows CAUTION with "coin flip" and "earnings this week" warnings; a forced 9-share order shows NO TRADE (risk BLOCK) |
| **M6** | Risk, Size, Positions, Alerts | Pages 4 and 5, flatten helper, notifications | Alerts from the plan appear; the 15:55 flat-by alert fires in replay and sends a toast |
| **M7** | Journal & Research | Decision logging, EOD shadow outcomes, metrics, calibration chart, analyst and Pelosi views, CSV export | 10 synthetic decisions give correct expectancy and calibration; skipped trades get simulated R |
| **—** | **Paper-trading period** | Use M1 to M7 live, read-only, for 4 to 8 weeks; you place orders manually or via Claude | 40+ logged decisions; review the journal's calibration and expectancy |
| **M8** (optional) | Alpaca paper execution | alpaca-py paper client, typed confirmation, fingerprint gate, fill sync | Cannot place without a PASS plus typed confirmation; refuses live keys; fills show in Positions and the Journal |
| **M9** | Hardening | Retry and backoff dashboards, a Task Scheduler entry for the worker, backup of `gatekeeper.db` and `trader/`, a README runbook | The worker survives network drops and a laptop restart; a nightly backup exists |

Suggested order of effort: M0 to M1 is the foundation and the riskiest part
(parsing contracts). Everything after it is mostly UI work on top of tested data.

---

## 16. Risks and mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Yahoo's unofficial endpoints change or rate-limit | Empty scans and charts | Cache, backoff, small core list by default, a "data stale" banner when the last good fetch is older than 2× the interval; the skills already fall back from query2 to query1 |
| Upstream skills change their JSON | Parsing breaks | Pinned submodule, `extra="allow"` models, contract tests before bumping the version |
| Worker and Claude chat write `trader/` at the same time | Corrupted state | File lock in the runner; Claude chat writes rarely; the UI warns if `plan.json` changed underneath it |
| Laptop sleeps during the session | Missed triggers and alerts | `powercfg` guidance, a worker heartbeat on Home, missed-job catch-up via APScheduler `misfire_grace_time` |
| IST late-night flat-by | Positions held overnight unintentionally | Awake-window gate (soft FAIL), a red countdown, a strong recommendation to set `flat_by` within your awake hours |
| Overconfidence from a pretty UI | Bad trades | No "buy" language, verdicts verbatim, the calibration chart, CAUTION shown as prominently as GO, a disclaimer in the footer |
| Free data is delayed | Late entries | The clock bar shows the data's age; the "trigger more than one bar old" WARN gate |
| Streamlit re-runs | Slow UI, duplicate actions | Heavy work in the worker; `st.cache_data`; action buttons disabled while a run is in flight; idempotent writes |

---

## 17. Future extensions

- **Sector and industry tags** for the scanner (a static SEC SIC mapping) and a sector heatmap.
- **Multiple setups:** add level breakouts from the daily `breakout_20d` hits automatically (entry `--setup level --level <20d high>`).
- **Walk-forward study page:** run the Time Machine's history mode across the whole core list for a chosen rule, and rank which tickers the rule historically worked on (still not a prediction).
- **FastAPI layer** over `gatekeeper/` for a mobile view or a Telegram bot with commands (`/status`, `/plan TSLA`).
- **Claude in the loop:** a "Ask Claude about this trade" button that sends the plan, news and Time Machine JSON to the Claude API for a plain-language second opinion (read-only, no order tools).
- **Interactive Brokers** read-only position sync.
- **Docker** packaging for running the worker on an always-on home server or VPS.

---

*This project is tooling for disciplined decision-making on free, delayed public
data. It is not financial advice, it does not predict prices, and most people
who day trade lose money. Paper trade first.*
