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

> In Phase 0 the worker is a placeholder: it prints the New York / IST clock and the session phase once a minute.

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

> From Phase 3, set `GATEKEEPER_MODE=replay` in `.env` and use the dashboard's time slider instead.

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
| 1 | `uv run python scripts/snapshot_contracts.py` | Saves every skill's JSON output from the recorded day as test references |
| 1 | `uv run pytest tests/test_replay_e2e.py -v` | Checks every recorded number end to end |
| 2 | `uv run python -m worker` | The real scheduler (scans, news, entries, alerts on a New York schedule) |
| 2 | `uv run python -m worker --replay --from 09:30 --to 10:30 --speed 600` | Fast-forwards a recorded day through the worker |
| 3 | `GATEKEEPER_MODE=replay` in `.env` | Dashboard in replay mode, with a time slider |
| 6 | `uv sync --extra notify` | Windows toast notifications |
| 8 | `uv sync --extra broker` | Alpaca **paper** trading support (optional phase) |
| 9 | `powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1` | Starts the worker automatically at login |
| 9 | `powershell -ExecutionPolicy Bypass -File scripts\keep_awake.ps1` | Keeps the PC awake during the US session |
