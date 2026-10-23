# Gatekeeper

> **Every trade has to earn its way in.**

A Python dashboard that runs the [day-trader skills](https://github.com/Jakeschincariol/day-trader-skill)
on a schedule and shows, for the day and for each trade, whether your rules and the
honest odds say GO, CAUTION or NO TRADE. It is tooling, not financial advice.

- Plan: [DASHBOARD_PROJECT_PLAN.md](DASHBOARD_PROJECT_PLAN.md)
- Build tracker: [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md)
- Skills usage: [DAY_TRADER_GUIDE.md](DAY_TRADER_GUIDE.md)
- All commands: [COMMANDS.md](COMMANDS.md)

## Quick start (Windows)

```powershell
git clone --recurse-submodules https://github.com/Rishav123raj/Gatekeeper.git
cd Gatekeeper
uv sync
copy .env.example .env        # then edit .env
uv run pytest
uv run streamlit run app/Home.py      # http://127.0.0.1:8501
```

Or start the worker and dashboard together: `powershell -ExecutionPolicy Bypass -File scripts\dev.ps1`.

The skills are pinned as a git submodule in `vendor/day-trader-skill`. Their own tests:

```powershell
cd vendor/day-trader-skill
uv run --no-project python -m unittest discover -s tests
```
