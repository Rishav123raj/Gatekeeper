# Day Trader Skill Pack: Complete Usage Guide

A practical guide to the 11 `trader-*` skills installed in `~/.claude/skills/`
(source: https://github.com/Jakeschincariol/day-trader-skill, v2.0.0, MIT).

> **Read this first.** This pack is software that reads free public data and
> does arithmetic. It does not find guaranteed winners, and it cannot see the
> future. Most people who day trade lose money. The "beneficial outcome" this
> pack can realistically give you is **discipline**: small, pre-defined losses,
> no impulsive trades, honest odds before every trade, and a written record you
> can learn from. Any profit has to come from a setup that proves itself over
> many paper trades, and this guide shows you how to test for that.
> Nothing here is financial or tax advice.

---

## Table of contents

1. [What the pack is (and is not)](#1-what-the-pack-is-and-is-not)
2. [One-time setup](#2-one-time-setup)
3. [How the skills fit together](#3-how-the-skills-fit-together)
4. [Trading the US market from India: the clock](#4-trading-the-us-market-from-india-the-clock)
5. [The 11 skills in detail](#5-the-11-skills-in-detail)
6. [A full trading day, step by step](#6-a-full-trading-day-step-by-step)
7. [Your rules file (`trader/config.json`) explained](#7-your-rules-file-traderconfigjson-explained)
8. [How to actually get a beneficial outcome](#8-how-to-actually-get-a-beneficial-outcome)
9. [Common mistakes and how the pack stops them](#9-common-mistakes-and-how-the-pack-stops-them)
10. [Files the pack creates](#10-files-the-pack-creates)
11. [Quick command reference](#11-quick-command-reference)
12. [Limits and fine print](#12-limits-and-fine-print)

---

## 1. What the pack is (and is not)

**It is** a pipeline of 11 Claude skills for **long-only intraday trading of
US-listed stocks**. Each skill does one job, writes its result into a
`trader/` folder in your project, and the next skill reads it.

**It is not:**
- A signal service or a "buy this" bot. The skills never pick a stock for you.
- Real-time data. It uses free, unofficial, delayed Yahoo data in 1-minute or 5-minute bars.
- An auto-trader. **Nothing places an order without your explicit "yes"**, and
  even then Claude's own "Allow once / Deny" card asks a second time.
- A tool for Indian markets (NSE/BSE). The universe, hours, holidays and brokers
  are all US.
- A short-selling, options, margin or crypto tool (all off by default).

The core idea: **decide everything before the money moves.** Entry, stop,
target, size and the time you will be out are all fixed before you buy.

---

## 2. One-time setup

### 2.1 Requirements

| Need | Status on your machine |
| --- | --- |
| Python 3.8+ | Python 3.12.10 installed |
| pip packages | None needed (standard library only) |
| Skills | Installed in `~/.claude/skills/trader-*` |
| `pdftotext` (Poppler) | Optional, only for `/trader-pelosi` to read PDFs locally |
| Broker account | Optional, only for `/trader-broker` (Alpaca paper is the default) |

> On Windows the command is `python`, not `python3`. When Claude runs the skills
> it handles this, so you can just talk to Claude in plain English.

### 2.2 Create your rules file

Everything lands in a `trader/` folder inside your working project
(here: `c:\Users\Lenovo\Desktop\trading_skills\trader\`). The easiest way is to
ask Claude:

> "Set up my trading rules"

Claude runs `/trader-budget`, copies `config.example.json` to
`trader/config.json`, and asks you for each value. See
[Section 7](#7-your-rules-file-traderconfigjson-explained) for what each one means.

### 2.3 SEC identification (for news filings and earnings)

SEC EDGAR requires a name and email in every request. Add to `trader/config.json`:

```json
"sec_user_agent": "Your Name your.email@example.com"
```

or set the `SEC_USER_AGENT` environment variable. Without it, `/trader-news`
skips 8-K filings and `/trader-analyst` refuses to run.

### 2.4 Broker connection (optional, do this last)

Only needed when you want orders to actually go somewhere. Start with a
**paper** (simulated money) account.

**Alpaca (official MCP server, Claude Desktop):**
1. Create an Alpaca account and generate **paper trading** API keys.
2. Install `uv` (gives you `uvx`) from docs.astral.sh/uv.
3. Claude Desktop, then Settings, Developer, Edit Config (`%APPDATA%\Claude\claude_desktop_config.json` on Windows). Add:
   ```json
   {
     "mcpServers": {
       "alpaca": {
         "command": "uvx",
         "args": ["alpaca-mcp-server"],
         "env": {
           "ALPACA_API_KEY": "your paper key, typed in this file only",
           "ALPACA_SECRET_KEY": "your paper secret, typed in this file only",
           "ALPACA_PAPER_TRADE": "true",
           "ALPACA_TOOLSETS": "account,trading,stock-data"
         }
       }
     }
   }
   ```
4. Restart Claude Desktop.
5. Set tool permissions (Customize, Connectors, alpaca):
   - `place_stock_order`, `cancel_order_by_id`, `replace_order_by_id`, `close_position`: **Needs approval**
   - `place_option_order`, `place_crypto_order`, `close_all_positions`, `cancel_all_orders`: **Blocked**
   - read-only tools (`get_account_info`, `get_all_positions`, `get_orders`, quotes): Always allow is fine
6. Ask Claude for "my Alpaca account info" and confirm in Alpaca's dashboard that it is the paper account.

In **Claude Code**, add this to `.claude/settings.json` so orders always ask:
```json
{ "permissions": { "ask": ["mcp__alpaca__place_stock_order"] } }
```

**Interactive Brokers:** add the verified IBKR connector from Customize,
Connectors, Browse connectors, sign in there (never in chat), and set
`"broker": "ibkr"` in your config. With IBKR, orders are drafted to your IBKR
account and you approve them inside IBKR too.

> **Never paste API keys into the chat.** If you do by accident, delete the
> message and regenerate the keys.

> **For Indian residents:** buying US stocks goes through the RBI's Liberalised
> Remittance Scheme (LRS), and broker eligibility for Indian residents varies.
> Confirm with the broker that you can open an account, and check the LRS and
> tax rules (TCS on remittances, and how foreign short-term gains are reported),
> before funding a live account. Paper trading needs none of this.

---

## 3. How the skills fit together

```
                        ┌───────────── RESEARCH (any time / on a schedule) ─────────────┐
                        │  /trader-news     /trader-analyst     /trader-pelosi           │
                        └────────────────────────────────────────────────────────────────┘

ONE TRADE:
 /trader-scanner ──► /trader-news ──► /trader-entry ──► /trader-exit ──► /trader-timemachine
   find setups        any danger?       when to get in    stop + target    honest odds
   watchlist.json                       entry.json        plan.json        timemachine.json
                                                                                │
                                                                                ▼
 /trader-alerts ◄── /trader-broker ◄──────── /trader-risk ◄──────────── /trader-budget
   stop, target,     your "yes", then        PASS / BLOCK               how many shares
   flat-by bell      Allow once              state/risk.json            orders.json
```

| Order | Skill | Question it answers | Writes |
| --- | --- | --- | --- |
| 1 | `/trader-scanner` | Which charts match a setup right now? | `trader/watchlist.json` |
| 2 | `/trader-news` | Is there news (earnings, halt, lawsuit) that makes this dangerous? | `trader/state/news.json` |
| 3 | `/trader-entry` | Has it confirmed? At what time and price? | `trader/entry.json` |
| 4 | `/trader-exit` | Where is my stop, my target, and when am I out? | `trader/plan.json` |
| 5 | `/trader-timemachine` | If today behaves like the last 60 days, what are the odds? | `trader/timemachine.json` |
| 6 | `/trader-budget` | How many shares fit my max loss? | `trader/orders.json` |
| 7 | `/trader-risk` | Does this order break any of my rules? | `trader/state/risk.json` |
| 8 | `/trader-broker` | Do you say yes to this exact order? | `trader/state/broker.json`, `trader/portfolio.json` |
| 9 | `/trader-alerts` | Has the stop, target or flat-by time hit? | `trader/alerts.json`, `trader/prices.json` |
| side | `/trader-analyst` | What did the last earnings report actually say? | `trader/metrics.json` |
| side | `/trader-pelosi` | What did Congress members disclose buying or selling? | `trader/state/pelosi.json` |

You can invoke each skill with its slash command, or just ask in plain English
("scan the market", "where's my stop", "how many shares", "check my order").

---

## 4. Trading the US market from India: the clock

All the tools work in **New York time** internally and handle daylight saving
themselves. India has no daylight saving, so the gap changes twice a year:

| New York (ET) | What happens | IST until Nov 1, 2026 (US on EDT, +9:30) | IST from Nov 1, 2026 to Mar 14, 2027 (US on EST, +10:30) |
| --- | --- | --- | --- |
| before 9:30 | Pre-market: daily scan, news, analyst | before 7:00 PM | before 8:00 PM |
| 9:30 | NYSE opens; the opening range starts | 7:00 PM | 8:00 PM |
| 9:45 | Opening range complete; earliest entry (`no_entries_before`) | 7:15 PM | 8:15 PM |
| 9:50 | Earliest useful ORB scan | 7:20 PM | 8:20 PM |
| 10:15 | "Classic" ORB scan time | 7:45 PM | 8:45 PM |
| 15:30 | Last new entry (`no_entries_after`) | 1:00 AM | 2:00 AM |
| 15:55 | Flat by: everything closed (`flat_by`) | 1:25 AM | 2:25 AM |
| 16:00 | NYSE closes | 1:30 AM | 2:30 AM |

**What this means for you in practice:**
- The best part of the day for the opening-range breakout (the first 1 to 2
  hours) falls in your evening, between roughly 7 and 10 PM IST. That is workable.
- The **flat-by time falls after midnight IST.** Nothing in this pack closes a
  trade for you while you sleep. `/trader-broker` never places orders from a
  background task, because nobody is there to say yes.
- The bracket's stop-loss and take-profit sit at the broker and work without
  you. But they are **day orders that expire at the close**. A trade that hits
  neither stop nor target by 4:00 PM ET stays open overnight, which is exactly
  what a day trader must avoid.

**Recommended fix for an Indian schedule:** move your windows earlier in
`trader/config.json`, so you only trade, and are flat, while you are awake:

```json
"no_entries_before": "09:45",
"no_entries_after":  "11:00",
"flat_by":           "12:00"
```

That is entries from 7:15 to 8:30 PM IST and flat by 9:30 PM IST (one hour later
after Nov 1). Then run the Time Machine with `--until 12:00` so its odds match
the shorter trade. A shorter trade has a higher chance of "neither" (no stop or
target hit), so check the odds with your real cutoff before you commit.

---

## 5. The 11 skills in detail

### 5.1 `/trader-scanner`: Chart Scanner

**Job:** Scans thousands of US stocks and lists the charts that match a rule.
A hit means the chart "matched a rule", not "a buy".

**Three modes:**

| Command | When | What |
| --- | --- | --- |
| `scan.py universe` | Once a week | Builds the list of about 5,900 US common stocks and ADRs from Nasdaq Trader (ETFs, warrants, units, preferreds removed). Writes `trader/universe.txt` |
| `scan.py daily` | Before the open, or after the close | Scans daily closes of the whole universe (about 2.5 minutes). Liquidity filter: price ≥ $5, volume ≥ 1M |
| `scan.py orb` | After 9:50 AM ET | Intraday opening-range breakout scan on 5-minute bars |

**Daily setups:**

| Setup | Rule (on closing prices) |
| --- | --- |
| `breakout_20d` | Last close above every close of the previous 20 sessions |
| `bull_flag` | Up >10% over 10 sessions, then the last 5 closes inside a 5% range |
| `reclaim_ma20` | Was below its 20-day average, now closed above it |
| `oversold` | RSI(14) under 30 |
| `oversold_bounce` | RSI(14) under 30 yesterday, closed up today |

**Opening-range breakout (ORB):** the opening range is the high and low of the
first 15 minutes (the 9:30, 9:35 and 9:40 five-minute bars). A hit is the first
completed 5-minute bar that **closes** above the range high.

**Useful flags:** `--symbols TSLA,NVDA,AMD` (scan only these), `--watchlist FILE`,
`--min-price`, `--min-volume`, `--or-minutes 15`, `--at 10:15`, `--max-confirm 200`,
`--show N`, `--json`, `--no-write`.

**Tip:** a whole-universe ORB scan takes about 4 minutes. For speed, scan your
own short list of liquid names (`--symbols` or `--watchlist`). A later hit is
closer to the current price; an early hit may already have run.

**Ask Claude:** "Run a pre-market scan", "Find opening-range breakouts", "Scan TSLA, NVDA, AMD, META for setups".

---

### 5.2 `/trader-news`: News Monitor

**Job:** Before a setup becomes a trade, checks the stock's Yahoo Finance
headlines and SEC 8-K filings, shows only what is **new since the last check**,
and prints how far each stock is from yesterday's close.

**Tags:** earnings, analyst, legal, deal, capital, people, risk, halt, regulatory, macro.

**Important 8-K items (marked `!`):** 2.02 earnings results, 5.02 officer change,
2.06 impairment, 3.01 delisting notice, 4.02 restated financials, 1.03 bankruptcy,
1.05 cyber incident.

**MOVING:** a stock 3% or more from yesterday's close (`--move-pct` changes it).

**Commands:**
```
news.py                                  # watchlist + plan + portfolio tickers
news.py --tickers TSLA NVDA --hours 12
news.py --no-sec --json
news.py --all                            # include items already seen
```

**How to use it well:** treat headlines as leads, not facts; an 8-K beats a
headline. The key question: **is there an earnings report or event inside my
trade?** If so, a stop cannot protect you from a gap.

**Ask Claude:** "Any news on my watchlist?", "Why is AMD moving?", "Morning briefing". During the session: `/loop 15m /trader-news`.

---

### 5.3 `/trader-entry`: Entry Timer

**Job:** Watches a setup bar by bar and tells you the exact moment it confirms.

**The rule:**
- **ORB setup:** the trigger is the first completed bar after the opening range that **closes** above the range high. A wick above is not a trigger; a close exactly at the level is not "above".
- **Level setup:** same, but above a price you give (for example a 20-day high).
- Only closed bars count. The time reported is the bar's close time (the 10:10 bar closes at 10:15).
- Optional volume confirmation: `--min-volume-x 1.5` means the trigger bar's volume must be at least 1.5 times the opening-range bars' average.
- No entries before 9:45 or after 15:30 ET (from config).

**Statuses:** WAITING (and how far below the level), TRIGGERED (time and price), EXPIRED, not open yet, range still forming, market closed.

**Commands:**
```
entry.py check TSLA                                  # one-time check
entry.py check TSLA --write                          # also save trader/entry.json
entry.py check TSLA --setup level --level 371.20
entry.py check TSLA --interval 1m --min-volume-x 1.5
entry.py watch TSLA --until 15:30                    # runs until trigger or expiry
entry.py watchlist                                   # every scanner hit
```

**Tip:** if the trigger is more than one bar old when you see it, it is a
different (worse) trade: the price has moved on. Keep your computer awake while
`watch` runs.

**Ask Claude:** "Watch TSLA and tell me when it breaks out", "Has NVDA broken its opening range?"

---

### 5.4 `/trader-exit`: Exit Planner

**Job:** Sets the stop, the target and the flat-by time **before** you buy.

**Stop options (`--stop`):**

| Option | Where | Effect |
| --- | --- | --- |
| `or-mid` (default for ORB) | Opening-range midpoint | Balanced |
| `or-low` | Opening-range low | Wider stop, so fewer shares for the same max loss |
| `price:X` | Your price | Required for a level setup |
| `pct:X` | X% below entry | Simple |
| `atr:K` | K × 14-bar ATR below entry | Adapts to volatility |

**Target options (`--target`):** `2R` (default), `1R`, `1.5R`, or `price:X`.
**R** = risk per share = entry − stop. A 2R target is entry + 2 × risk.

**It refuses** a stop at or above the entry, a target at or below it, a stop
tighter than 0.05% of price (the spread would stop you out), an untriggered entry,
a short, or an entry after the flat-by time.

**Commands:**
```
exit.py plan                                         # from trader/entry.json
exit.py plan --stop or-mid --target 1R --write
exit.py plan --stop atr:1.5
exit.py plan --symbol TSLA --entry 364.18 --or-high 362.18 --or-low 354.47
exit.py show
```

**Golden rules:** set the stop before the entry, and never move it further away once the trade is on.

**Ask Claude:** "Set my stop and target", "Plan the exit with a 2R target".

---

### 5.5 `/trader-timemachine`: Time Machine (the most valuable skill)

**Job:** Before you risk money, it asks: *if today behaves like this stock's last
60 days, how often does this exact plan hit the target first, the stop first, or neither?*

**How it works:**
1. Loads 60 days of 5-minute bars and keeps only full sessions.
2. **10,000 replays:** builds the rest of today bar by bar, each bar drawn at random from a past bar at the same time of day, scaled to the current price. Checks the stop first, then the target (a bar touching both counts as a stop).
3. **History:** re-runs your exact rule on every one of those real past sessions.
4. **Verdict:** compares the target-first rate to the break-even rate for your R.

**Break-even win rate by target:**

| Target | You must hit the target first in at least... |
| --- | --- |
| 1R | 50% of trades that hit a side |
| 2R | 33% |
| 3R | 25% |

**Verdict lines:** "Close to a coin flip / Close to break-even" (within 5 points), "Leans toward the target / stop" (5 to 15 points), "Strongly toward" (15+ points).

**Commands:**
```
timemachine.py run --write
timemachine.py run --until 15:55          # end replays at your flat-by time
timemachine.py run --replays 20000 --seed 7
timemachine.py chart --from               # ASCII fan chart
```

**The real example from the repo (TSLA, Oct 19, 2026, 1R target):**
target first 29.4%, stop first 25.5%, neither 45.1%. The history: 33 setups, 13
targets, 15 stops. **Verdict: close to a coin flip.** This is what the tool is
for: showing you that a clean-looking breakout often has no real edge.

**Ask Claude:** "Run the time machine", "What are the odds on this trade?"

---

### 5.6 `/trader-budget`: Budget Manager

**Job:** Turns the plan into an exact share count. **The stop decides the size.**

**Shares = the smallest of four limits:**

| Limit | Formula |
| --- | --- |
| Max loss | `max_loss_per_trade_usd` ÷ (entry − stop) |
| Position cap | budget × `max_position_pct` ÷ entry |
| Max order | `max_order_usd` ÷ entry |
| Cash | (budget − cash buffer) ÷ entry, capped by real cash |

Example: $5,000 budget, $50 max loss, TSLA entry 364.18, stop 358.32 (risk 5.86):
max loss gives 8 shares, the position cap 10, max order 10, cash 12. **8 shares**,
$2,913.44, max loss at the stop $46.88.

**It writes one bracket order** (entry + stop-loss + take-profit) in Alpaca's
format to `trader/orders.json`. Nothing is placed.

**It refuses** when the size is 0, reward:risk is below your minimum, the move
already happened (price ran past the plan), the plan is for another day, or the ticker is blocked.

**Commands:**
```
size.py                         # show
size.py --write                 # write trader/orders.json
size.py --limit --write         # limit order at the plan's entry
size.py --limit 364.00
```

**Ask Claude:** "How many shares should I buy?", "I have $5,000 and want to risk $50 a trade".

---

### 5.7 `/trader-risk`: Risk Manager

**Job:** The gate. Every order must PASS before `/trader-broker` will even show it to you.

**What it blocks (for entries):**

| Check | Blocks when |
| --- | --- |
| stop | No stop, or a stop on the wrong side |
| loss | qty × (entry − stop) > max loss per trade |
| reward:risk | Below `min_reward_risk` |
| daily loss | Today's entries' max losses + this one > `max_daily_loss_usd` |
| trades | Already at `max_trades_per_day` |
| window | Before `no_entries_before`, after `no_entries_after`, or the market is closed |
| size / position / cash | Order too small or big, position over the cap, would break the cash buffer or need margin |
| blocked / asset / short | Blocked ticker, options or crypto, selling more than you hold |
| duplicate / daily limit | Same order twice, too many orders today |
| pdt (optional) | 3 day trades in 5 business days (only if `pdt_guard: true`) |

**Exits are never blocked by day limits.** You can always get out.

It measures risk from the **higher** of the plan's entry and a fresh price
(under 15 minutes old), so a plan from 10:15 cannot hide extra risk at 10:55.

**Commands:**
```
check.py
check.py --no-write        # look without recording
check.py --json
```

**Ask Claude:** "Check my order", "Can I take this trade?", "How much have I risked today?"

---

### 5.8 `/trader-broker`: Order Executor

**Job:** The only skill that can lead to a real order. Three gates, every time:

1. `/trader-risk` passed **this exact order** today (matched by fingerprint, so any edit needs a new check).
2. **You type an explicit "yes"** for that one order in the chat (no "yes to all"; "sure" doesn't count).
3. **You click "Allow once"** on Claude's permission card.

**Commands (ticket.py never talks to the broker itself):**
```
ticket.py show                                   # tickets, READY or not
ticket.py approve --index 1 --reply "yes"
ticket.py result --index 1 --status placed --broker-id ID --filled-qty 8 --filled-price 364.20
ticket.py fill --symbol TSLA --side sell --qty 8 --price 370.04
ticket.py flatten --symbol TSLA --qty 8          # build the closing sell
ticket.py log
```

**Closing the trade by flat-by:** check the position, run `flatten`, run
`/trader-risk`, say yes, **cancel the bracket's open stop and target orders
first** (otherwise Alpaca rejects the sell), then place the sell.

**Ask Claude:** "Place the order", "Flatten TSLA", "Connect Alpaca paper trading".

---

### 5.9 `/trader-alerts`: Price Alerts

**Job:** Rings once when a price, stop, target, time or the opening bell hits. Alerts are information only; they never trade.

**Rule types:** `above`/`target`, `below`/`stop`, `pct_move`, `time`, `opening_bell`.

**Commands:**
```
alerts.py clock                          # is NYSE open? next open?
alerts.py add --from-plan                # stop + target + flat-by from plan.json
alerts.py add --opening-bell
alerts.py add --symbol TSLA --stop 358.32
alerts.py add --symbol KO --pct 3
alerts.py add --at 15:55 --label "flat by close" --before-close
alerts.py check                          # run every few minutes
alerts.py quote TSLA --write             # fresh price into trader/prices.json
alerts.py list / reset <id>
```

Run checks with `/loop 5m /trader-alerts check`. Quotes are delayed and a price can pass a level between two checks.

**Ask Claude:** "Alert me when TSLA hits 370", "Is the market open?", "Watch my trade".

---

### 5.10 `/trader-analyst`: Earnings Analyst

**Job:** Reads a company's reported numbers straight from SEC EDGAR (XBRL) and
summarises: revenue, gross, operating and net margins, net income, diluted EPS,
quarter by quarter, against the same quarter last year, plus the trailing 12 months.

**Flags it raises:** a derived Q4 (no Q4 10-Q exists), SEC data lagging a new
filing, net income above operating income (one-off gains inside), and banks
with no gross margin.

**Commands:**
```
facts.py TSLA
facts.py TSLA NVDA AMD --metrics trader/metrics.json
facts.py AAPL --quarters 8 --json
```

**Day-trading use:** answer *"Is the next earnings report inside my trade?"*
If yes, a gap can jump straight past your stop. The report date is not in SEC
data; get it from `/trader-news` or the company's IR page. You can also paste an
earnings-call transcript and ask Claude to summarise it.

**Ask Claude:** "How did Tesla's earnings look?", "Compare NVDA and AMD margins".

---

### 5.11 `/trader-pelosi`: Congress Trade Tracker

**Job:** Reads US House members' Periodic Transaction Reports (STOCK Act
disclosures) from the House Clerk, alerts once per new filing, and turns each
PDF into rows: member, owner (SP = spouse, JT = joint, DC = child), ticker,
buy or sell, options strike and expiry, trade date, amount range, days to disclose.

**Commands:**
```
ptr.py index --member pelosi
ptr.py index --since 2026-10-01                    # every member
ptr.py new --member pelosi --read                  # only new filings
ptr.py fetch 20035143                              # one report
```

**Reality check:** disclosures are filed up to **45 days after** the trade.
This is public information read quickly, not inside information. Use it as a
reason to *look at a chart*, never as a trade signal by itself. The Senate has a
manual route (efdsearch.senate.gov, where you accept the site's terms yourself).

Needs `pdftotext` (Poppler) to parse PDFs locally; otherwise Claude can read the saved PDF directly.

**Ask Claude:** "What has Pelosi bought this year?", "Any new Congress trades in NVDA?"

---

## 6. A full trading day, step by step

The times below are ET, with IST before Nov 1, 2026 in brackets.

### Weekly (weekend)
1. **"Rebuild the stock universe"**: `scan.py universe`.
2. **"Summarise earnings for my usual names"**: `/trader-analyst` on the 10 to 20 stocks you trade most. Note who reports in the coming week.
3. **"Any new Congress filings?"**: `/trader-pelosi`, for ideas only.

### Pre-market (before 9:30 ET [before 7:00 PM IST])
4. **"Run a pre-market scan"**: `/trader-scanner daily`. Read the hits by setup.
5. **"Any news on the watchlist?"**: `/trader-news`. Cross off anything with earnings today or tonight, halts, offerings or legal news.
6. **"Alert me at the opening bell"**: `/trader-alerts add --opening-bell`.

### The open (9:30 to 9:45 ET [7:00 to 7:15 PM IST])
7. Do nothing. The opening range is forming, and the tools won't allow entries yet.

### Finding the trade (9:50 to 10:30 ET [7:20 to 8:00 PM IST])
8. **"Scan for opening-range breakouts"**: `/trader-scanner orb`, ideally on your short watchlist.
9. **Pick one** (Claude never picks for you). **"Watch [TICKER] for the entry"**: `/trader-entry`.
10. When it triggers: **"Plan the exit"**: `/trader-exit` (stop and target are now fixed).
11. **"Run the time machine"**: `/trader-timemachine --until <your flat_by>`.
    - Coin flip or leaning toward the stop: **skip the trade.** This is a win for your account.
    - Leaning toward the target, with history agreeing: continue.
12. **"Size it"**: `/trader-budget` writes one bracket order.
13. **"Check it"**: `/trader-risk` returns PASS or BLOCK. On BLOCK, read the reason; never loosen a rule mid-session.
14. **"Place it"**: `/trader-broker`, then your "yes", then Allow once.
15. **"Watch my trade"**: `/trader-alerts add --from-plan`, then `/loop 5m` checks.

### While the trade is open
16. The bracket does the work. When the stop or target alert rings, record the fill (`ticket.py fill`).
17. Do not move the stop further away. Do not add to a losing trade.

### Flat-by (your `flat_by` time)
18. Alert rings, then **"Flatten [TICKER]"**: `/trader-broker flatten`, `/trader-risk`, cancel the bracket legs, your yes, Allow once.

### After the close: the journal (most important habit)
19. **"Show my broker log"**: `ticket.py log`. Write down for each trade: setup, Time Machine verdict, R result, and whether you followed every rule.

---

## 7. Your rules file (`trader/config.json`) explained

Starting point (from `trader-budget/config.example.json`), with notes:

```jsonc
{
  "budget": 5000,                 // money for this, and only money you can afford to lose
  "cash_buffer_pct": 10,          // always kept in cash
  "max_position_pct": 75,         // max % of budget in one stock
  "max_order_usd": 4000,          // biggest single order
  "min_order_usd": 5,
  "max_loss_per_trade_usd": 50,   // THE key number: 1% of budget is a common choice
  "max_daily_loss_usd": 150,      // stop trading for the day after this much risk is used
  "max_trades_per_day": 3,        // prevents overtrading / revenge trading
  "max_orders_per_day": 10,
  "min_reward_risk": 1.0,         // consider 1.5 or 2.0
  "require_stop": true,           // never turn this off
  "no_entries_before": "09:45",   // New York time
  "no_entries_after": "15:30",    // move earlier for an Indian evening (see Section 4)
  "flat_by": "15:55",             // move earlier for an Indian evening (see Section 4)
  "fractional": false,
  "broker": "alpaca",             // or "ibkr"
  "paper": true,                  // keep true until you've proved the system (Section 8)
  "blocked": [],                  // tickers you never trade
  "allow_options": false,
  "allow_margin": false,
  "allow_short": false,
  "pdt_guard": false,             // set true if your broker still applies the $25k PDT rule
  "sec_user_agent": "Your Name you@example.com"
}
```

**Sizing your risk sensibly:**

| Account | Max loss per trade (≈1%) | Max daily loss (≈3%) |
| --- | --- | --- |
| $2,000 | $20 | $60 |
| $5,000 | $50 | $150 |
| $10,000 | $100 | $300 |

At 1% per trade, 10 losses in a row (which happens) costs about 10% of the
account, which is recoverable. At 5% per trade, the same streak costs about 40%.

---

## 8. How to actually get a beneficial outcome

The pack gives you **process**. Profit, if it comes, comes from running that
process on a setup with a real, measured edge, and from never letting one bad
day wipe you out. Here is a concrete plan.

### Phase 1: Learn the tools offline (week 1)
- Replay the repo's real example day. Ask Claude: *"Replay TSLA on 2026-10-19 using `--now` and `--offline` with the test fixtures."* The fixtures are in the cloned repo's `tests/fixtures/` folder; Claude can clone it again if needed.
- Run the Time Machine on several of your favourite stocks with different stop and target choices (`or-mid` vs `or-low`, 1R vs 2R), and see how the odds change.

### Phase 2: Paper trade (at least 4 to 8 weeks, 40+ trades)
- `"paper": true`, Alpaca paper account.
- Trade **one setup only** (for example, a 15-minute ORB with an `or-mid` stop and 2R target) so your results mean something.
- **Only take trades the Time Machine does not call a coin flip or a lean toward the stop.** This filter is the main way the pack can improve your results: it stops you from taking trades with no edge.
- Journal every trade: date, ticker, Time Machine verdict and target-first %, result in R, and "rules followed? Y/N".

### Phase 3: Measure your edge
After 40+ trades, compute your **expectancy** in R:

```
Expectancy (R) = (Win% × Avg win in R) − (Loss% × Avg loss in R)
```

Example with a 2R target: 40% winners at +2R, 60% losers at −1R:
`0.40 × 2 − 0.60 × 1 = +0.20R` per trade. At $50 risk, that is about +$10 per
trade on average, **before** commissions, slippage (stops filling worse) and
taxes.

| Your result | Meaning | What to do |
| --- | --- | --- |
| Expectancy ≤ 0 | No edge | Do **not** go live. Change the setup (stop rule, target R, time filter, volume filter) and paper-trade again |
| Small positive, rules often broken | Edge is in the setup, losses come from you | Keep paper trading until rules are followed 95%+ of the time |
| Consistently positive over 40 to 100 trades | Possible edge | Consider live with a **much smaller** risk per trade |

Also compare: **did the Time Machine's verdicts match reality?** If trades it
called "leans toward target" actually won more often, the filter is working for you.

### Phase 4: Go live small (only if Phase 3 says so)
- Switch `paper` to `false` yourself (the pack never does this).
- Cut `max_loss_per_trade_usd` to a quarter or a half of your paper size for the first month.
- Keep every rule identical. If live results drift far below paper results, go back to paper.

### Habits that make the difference
1. **Skipping is a position.** A coin-flip verdict means "no trade", and that is a good outcome.
2. **Respect the daily loss limit.** When `/trader-risk` blocks for the day, you are done.
3. **Never trade through earnings.** Check `/trader-news` and `/trader-analyst` every time.
4. **Never widen a stop** and never "average down".
5. **Re-run before acting.** Scanner hits and quotes go stale within minutes.
6. **Judge the process, not single trades.** A good trade can lose; a bad trade can win.

### Using the research skills well
- **`/trader-analyst`**: builds context (growth, margins) and tells you when *not* to hold through a report.
- **`/trader-pelosi`**: idea generation only. Weeks-old disclosures say nothing about today's price; let the scanner and entry timer decide if there is a trade.
- **`/trader-news` on a loop**: catches halts and surprise 8-Ks while you are in a position.

---

## 9. Common mistakes and how the pack stops them

| Mistake | What stops it |
| --- | --- |
| Buying because a stock "looks" like it's breaking out mid-bar | `/trader-entry` only counts **closed** bars |
| No stop, or a stop decided after entering | `/trader-exit` sets it first; `/trader-risk` blocks orders without one |
| Position too big | `/trader-budget` sizes to your max loss; `/trader-risk` re-checks |
| Chasing a stock that already ran | Budget and risk measure from the higher fresh price; reward:risk falls and the order is blocked |
| Overtrading / revenge trading | `max_trades_per_day`, `max_daily_loss_usd` |
| Trading the first chaotic minutes | `no_entries_before: 09:45` |
| Holding into earnings | `/trader-news` and `/trader-analyst` warnings; flat-by rule |
| Accidental live trading | `paper: true` default; three-gate approval in `/trader-broker` |
| Fooling yourself about a setup | `/trader-timemachine` gives honest odds and real history |

---

## 10. Files the pack creates

All inside `trader/` in your project folder:

| File | Written by | Read by |
| --- | --- | --- |
| `config.json` | You (via `/trader-budget`) | Most skills |
| `universe.txt` | scanner | scanner |
| `watchlist.json` | scanner | news, entry |
| `entry.json` | entry | exit |
| `plan.json` | exit | timemachine, budget, alerts, news, broker |
| `timemachine.json` | timemachine | (your review) |
| `orders.json` | budget, broker flatten | risk, broker |
| `prices.json` | alerts | budget, risk |
| `portfolio.json` | broker | budget, risk, news, pelosi |
| `alerts.json` | alerts | alerts |
| `metrics.json` | analyst | (your notes) |
| `state/news.json`, `state/risk.json`, `state/broker.json`, `state/alerts.json`, `state/pelosi.json` | each skill | dedupe, daily limits, logs |

`state/broker.json` is your trade log, so back it up.

---

## 11. Quick command reference

Plain English works for all of these. The scripts live in `~/.claude/skills/<skill>/`.

```bash
# Scanner
scan.py universe | daily | orb [--at 10:15] [--symbols A,B,C]
# News
news.py [--tickers TSLA NVDA] [--hours 12] [--all]
# Entry
entry.py check TSLA [--write] | watch TSLA --until 15:30 | watchlist
# Exit
exit.py plan [--stop or-mid|or-low|price:X|pct:X|atr:K] [--target 2R|1R|price:X] --write
# Time Machine
timemachine.py run --write [--until 15:55] | chart --from
# Budget
size.py [--limit [PRICE]] --write
# Risk
check.py [--no-write]
# Broker
ticket.py show | approve --index N --reply "yes" | result ... | fill ... | flatten --symbol X --qty N | log
# Alerts
alerts.py clock | add --from-plan | add --opening-bell | check | quote TSLA --write | list
# Analyst
facts.py TSLA [NVDA ...] [--quarters 8] [--metrics trader/metrics.json]
# Pelosi
ptr.py index --member pelosi | new --member pelosi --read | fetch DOCID
```

Handy for testing: almost every tool takes `--now "YYYY-MM-DD HH:MM"` (New York
time) and `--offline FILE` to replay a past day without network access.

**Recurring checks in Claude Code:**
```
/loop 15m /trader-news
/loop 5m /trader-alerts check
```

---

## 12. Limits and fine print

- **Not financial advice.** Most day traders lose money.
- **Long only.** No shorts in v2.
- **Free, unofficial, delayed data.** Yahoo can lag, change or rate-limit you. Bars are 1-minute or 5-minute, never tick-by-tick. Check prices at your broker before acting.
- **A stop is a plan, not a guarantee.** Gaps and fast markets can fill worse than the stop price.
- **The Time Machine is a simulation** from 60 days of data, not a prediction. Earnings, halts and news can do things those 60 days never did.
- **US market only:** NYSE hours, 2026 and 2027 holidays only.
- **PDT rule:** FINRA removed the $25,000 pattern-day-trader minimum (effective June 4, 2026), but brokers may phase it in until Oct 20, 2027. Turn on `pdt_guard` if yours still applies it.
- **Taxes:** day-trading gains are short-term; frequent trading makes wash sales likely (US). As an Indian resident, foreign income and assets have their own reporting rules. Consult a tax professional.
- **Congress trades** are public filings made up to 45 days late, not inside information.
