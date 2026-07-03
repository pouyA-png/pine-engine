# TASKS — 5m Leg-Variant Lab (100-Agent Sweep)

Goal (one sentence): Build a 5m variant of the pre-open-leg strategy (all filters OFF,
take every level long+short every day, hold orders until 17:00 NY), then fan out 100
agents that each test a DIFFERENT invented leg-detection method, track every trade, and
find the best leg method + SL (8/12.5/14/16) + best day/time/level/RR, reporting WR,
Sharpe, PF, DD, avg RR.

## Decisions (from user)
- Filters: ALL OFF. Every day (incl. Monday), all 4 levels as long+short, both halves a/b.
  No leg-direction filter, no Wed/Thu single-level, no max-2/day, no kill-window, no cutoff.
- Cancel: NONE intraday. Unfilled orders + open positions only close at 17:00 NY.
- Sweep: I invent the leg methods (100 distinct), one method per agent.
- SL grid per trade: 8 / 12.5 / 14 / 16 points.

## Data
- CME NQ continuous 5m: /mnt/d/C-Transfer-2026-06-11/Claude-memories/HistoricalTradingData/NQ_continuous_5m.csv
- Period: last year 2025-03-13 .. 2026-03-13.
- ANNAHME/CAVEAT: NOT FTMO's NAS100 spot CFD feed (not obtainable autonomously).
  CME futures used as RANKING proxy (5m engine PF 1.14 vs TV CFD 1.10 = close).
  Winner must be re-validated on user's FTMO M5 export.

## Plan
1. [done] Read spec.md — leg/level/entry/SL/TP mechanics.
2. [in progress] Build leg_lab.py: data+NY tz, 100-method registry, sim engine, tracking.
3. [ ] Validate harness sanity (baseline method, plausible trade counts).
4. [ ] Workflow: 100 agents, 1 leg method each -> run harness, return metrics + loss-leg note.
5. [ ] Aggregate: rank methods, best SL, best day/time/level/RR.
6. [ ] Standard stats for winner(s): WR, Sharpe, PF, DD, avg RR.
7. [ ] Build final ONE 5m pine bot embedding best leg method + write report.

## Assumptions (labeled)
- Intrabar fill: conservative — if a 5m bar contains both SL and TP, assume SL first.
- Sell-limit valid only if level > 09:30 open; buy-limit only if level < open; else skip that order that day.
- BE move for b-half applies from the bar AFTER TP1 is reached.
- This Python lab is for DISCOVERY/RANKING; absolute numbers indicative, validated later in pine engine + FTMO data.
