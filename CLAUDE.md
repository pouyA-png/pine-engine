# CLAUDE.md — Agent Instructions for Pine Engine

**You are assisting a user who wants to backtest Pine Script v5 strategies with this engine.**
This document tells you exactly how the engine works, what it can and can't do, and the correct workflow for common tasks. Read it fully before taking action.

---

## What this repo is

A standalone Pine Script v5 transpiler + backtesting runtime written in pure Python (stdlib only, no numpy/pandas). It:

1. **Parses** a `.pine` source file via its own lexer + recursive-descent parser (no regex hacks)
2. **Transpiles** the AST to Python source code (`pine_engine/codegen.py`)
3. **Executes** the generated code bar-by-bar against 1-min OHLC CSV data, with a broker emulator for limit/market orders, partial exits, and cancels

It is **not** a wrapper around TradingView, not a data fetcher, and not a live-trading executor. It is offline backtest only.

---

## Required environment

- Python 3.9+ (uses `zoneinfo` from stdlib)
- No `pip install` needed — the engine is a plain import-in-place package
- Linux/macOS/WSL works; native Windows works but untested

Verify the environment with:
```bash
python --version        # must be >= 3.9
python -m unittest discover pine_engine/tests/ -v
```

If tests fail, fix the environment before touching user strategies.

---

## The user's typical request patterns

### Pattern 1: "Run my strategy on this data"
```bash
python -m pine_engine.main run <strategy.pine> --data <bars.csv>
```
Optional flags:
- `--start YYYY-MM-DD --end YYYY-MM-DD` — date range filter
- `--param key=value` (repeatable) — override any Pine `input.*` by its variable name

Output: trade count, WR, PF, gross profit/loss, net profit, last 10 trades.

### Pattern 2: "Sweep parameters"
Write a short Python script using `pine_engine.batch.runner.BatchRunner`. See `scripts/example_sweep.py` as a template. Run it directly with `python scripts/example_sweep.py strategy.pine bars.csv`. Output goes to `output/`.

**Important**: the sweep runner uses `ProcessPoolExecutor`. Set `workers` to `os.cpu_count() - 1` max, never more.

### Pattern 3: "Compare to TradingView"
The user has a TV trade export (CSV with columns `Trade #, Typ, Datum und Uhrzeit, Signal, Preis USD, ...` — yes, German headers are common). Sample exports are under `data/tv_*.csv`. Parity workflow:

1. Run the engine on the same date range as the TV export.
2. Compare trade counts and WR. See the **Validation** section in README.md for known deltas.
3. If counts diverge by more than ~7%, suspect:
   - The user is feeding different bar data than TV's chart
   - An unsupported Pine builtin is being silently skipped (grep codegen output for TODO/NotImplemented)
   - `strategy.equity` sizing drift (fix: switch to fixed qty)

### Pattern 4: "Why does my .pine not compile?"
Run `python -m pine_engine.main info strategy.pine` first — it will show parse errors with line context. Common causes:
- `request.security()` calls (not supported)
- User-defined types (`type Foo`, not supported)
- Libraries (`import Author/lib/1 as L`, not supported)
- Methods on types (not supported)

If the user's strategy needs any of these, tell them upfront. Do **not** attempt to stub these features — they affect execution semantics.

---

## How to run a backtest end-to-end (canonical flow)

```python
from pine_engine.engine import compile_pine, run_backtest
from pine_engine.data.loader import load_bars_csv
from pine_engine.reporting.stats import compute_stats, format_stats

# 1. Compile (parses + transpiles + exec's the Python source)
compiled = compile_pine("strategy.pine")
print(f"Inputs: {[i.name for i in compiled.inputs]}")

# 2. Load bars (1-min OHLC CSV, NY timezone applied automatically)
bars = load_bars_csv("nq_1m.csv", start_date="2025-01-01", end_date="2025-12-31")

# 3. Run — pass params dict to override any input
trades = run_backtest(compiled, bars, params={"slPoints": 11.25, "pivotRight": 2})

# 4. Stats — point_value dollarizes PnL (NQ=$20, ES=$50, MNQ=$2, etc.)
stats = compute_stats(trades, point_value=20.0)
print(format_stats(stats))
```

---

## CSV format (non-negotiable)

```csv
datetime,open,high,low,close,volume
2025-01-02 09:30:00,21345.25,21347.50,21344.00,21346.75,1250
```

Requirements:
- Datetime column named `datetime`, `date`, `time`, or `timestamp`
- OHLC columns named `open`, `high`, `low`, `close` (any case)
- Volume optional
- Bars in chronological order (loader will not sort — sort first if needed)
- **1-minute bars** for the shipped strategies; other timeframes work but leg-detection logic depends on NY 09:30 granularity

Timezone handling:
- If datetime has tz suffix (`+00:00`, `Z`), it's used
- If not, UTC is assumed
- Pine's `hour(time, "America/New_York")` works correctly either way

---

## What NOT to do

1. **Do NOT rewrite the user's Pine file in Python to "make it easier to backtest"**. The whole point of this engine is to run the real `.pine` file. If you rewrite, results drift, user loses trust.

2. **Do NOT silently skip unsupported Pine features**. If the strategy uses `request.security`, tell the user the engine can't run it. Don't fake it.

3. **Do NOT add numpy/pandas as dependencies**. The engine is stdlib-only by design. If you need array math, use `math` and lists.

4. **Do NOT modify** `pine_engine/codegen.py` without running the full test suite afterward. Codegen is load-bearing — a bad edit silently corrupts every strategy the engine runs.

5. **Do NOT commit TV export data or user bar CSVs to the repo**. Those are user data. The `data/` folder has TV exports checked in solely as validation fixtures; don't add more.

6. **Do NOT assume the user has Pine files in this repo**. They don't. The user brings their `.pine` and CSV, points the CLI at them, reads results.

---

## Known TV-parity gotchas (save you 2 hours of debugging)

1. **`strategy.closedtrades` as a property returns a count, not a list**. The codegen emits `ctx.strategy.closedtrades_count` when `closedtrades` is used as a value. If you see `closedtrades > X` in Pine, it's a count comparison.

2. **`pine_round()` is half-away-from-zero**, NOT Python's banker's rounding. Do not replace with `round()`.

3. **Exit re-firing**: the broker tracks `fired_exit_ids` per open position. Don't "simplify" this — TV fires each exit once per entry, even if the Pine script keeps calling `strategy.exit()` every bar with the same id.

4. **Pre-declaration**: all local Pine vars must be pre-declared at the top of `execute_bar()`. The codegen does this. If you write custom codegen, remember this — a naked `if cond: x = 1` wipes the sibling branch's `x`.

5. **`strategy.equity` is dollar-denominated in this engine**. Pine's is chart-currency. Pass `point_value` to `compute_stats()` to dollarize point-based PnL from the broker log.

6. **Timezone for `hour()/minute()`**: always specify `"America/New_York"` in Pine. The engine defaults to UTC otherwise, which breaks session logic.

---

## Where to look for things

| User question | File to read |
|---|---|
| "How does the engine decide fills?" | `pine_engine/runtime/broker.py` |
| "How do inputs get parsed?" | `pine_engine/parser.py` + `pine_engine/codegen.py` (search `Input`) |
| "What Pine functions are supported?" | `pine_engine/runtime/builtins.py` |
| "How do sweeps work?" | `pine_engine/batch/runner.py` + `scripts/sweep_vvv1.py` |
| "What stats are computed?" | `pine_engine/reporting/stats.py` |
| "How is `strategy.entry` implemented?" | `pine_engine/runtime/strategy.py` + `broker.py:register_entry` |

---

## When asked to extend the engine

Run tests after every change:
```bash
python -m unittest discover pine_engine/tests/ -v
```

Adding a new Pine builtin (e.g., `ta.supertrend`):
1. Implement the function in `pine_engine/runtime/builtins.py`
2. Register it in the codegen's function-call dispatch table (search `builtin_funcs` in `codegen.py`)
3. Add a test in `pine_engine/tests/test_codegen.py` that compiles a minimal `.pine` using the new function and asserts the expected output

Adding a new `strategy.*` call:
1. Add the method to `StrategyAPI` in `pine_engine/runtime/strategy.py`
2. Wire it in `codegen.py` (search `strategy.` method dispatch)
3. Test against a known TV result

---

## When in doubt

- Prefer running `python -m pine_engine.main info <file.pine>` before guessing what a strategy does
- Prefer a small date-range run (`--start / --end`) over a full multi-year run for quick iteration
- Compute `stats` with explicit `point_value` — a strategy that looks profitable in points may be negative-PnL in dollars after commissions

---

## Contact / upstream

Repo: https://github.com/pouyA-png/pine-engine

Issues and PRs welcome. The maintainer tests against NQ 1-min data; parity on other instruments is unverified but should work.
