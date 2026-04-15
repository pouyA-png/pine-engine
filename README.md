# Pine Engine — Pine Script v5 Backtesting Engine

A **real Pine Script v5 transpiler + runtime** for Python. It parses your actual `.pine` files (no manual rewrite) and executes them bar-by-bar against CSV data with TradingView-compatible semantics.

- **TV parity**: trade counts and WR match TradingView within ~2% on equity-drift-free configs
- **Fast**: ~350k bars/year in ~50 seconds single-threaded
- **Parallel sweeps**: multi-process batch runner for parameter optimization
- **Zero 3rd-party deps**: pure Python stdlib (Python 3.9+)

Built for NQ pre-open leg strategies, but the language subset is general enough for most `strategy()` scripts that use the supported builtins.

---

## Quick start

```bash
git clone https://github.com/pouyA-png/pine-engine.git
cd pine-engine

# Run a backtest
python -m pine_engine.main run path/to/your_strategy.pine --data path/to/bars.csv

# Date-filter and override inputs
python -m pine_engine.main run strategy.pine --data nq_1m.csv \
    --start 2025-01-01 --end 2025-12-31 \
    --param slPoints=11.25 --param pivotRight=2

# Inspect a .pine file (inputs, strategy settings)
python -m pine_engine.main info strategy.pine

# Transpile .pine → Python (for debugging codegen output)
python -m pine_engine.main compile strategy.pine --output generated.py
```

No `pip install` required — the engine is a plain Python package, run it in-place.

---

## Input data

A 1-minute OHLC CSV. Headers are case-insensitive and can be in any order:

```csv
datetime,open,high,low,close,volume
2025-01-02 09:30:00,21345.25,21347.50,21344.00,21346.75,1250
2025-01-02 09:31:00,21346.75,21348.00,21345.00,21347.25,980
...
```

- Datetime column name: `datetime`, `date`, `time`, or `timestamp`
- Supported datetime formats: ISO 8601 (`2025-01-02T09:30:00`), space-separated (`2025-01-02 09:30:00`), with or without timezone
- Bars without timezone are assumed UTC. The engine converts to `America/New_York` for Pine's `hour()/minute()` calls
- Volume column is optional

Where to get data:
- **NQ / ES / CL futures**: Databento, Polygon.io, or CME DataMine (continuous contract, front-month)
- **Forex / CFDs**: Dukascopy historical data, MT5 `HistoryCenter`
- **Crypto**: Binance/Bybit/Kraken API
- **Stocks**: Polygon.io, Alpaca, IEX Cloud

> The repo ships with TradingView trade-export CSVs under `data/` — those are used for **TV-parity validation only**, not as bar data input. Bring your own 1-min OHLC file.

---

## Parameter sweeps

```python
from pine_engine.batch.runner import BatchRunner
from pine_engine.batch.param_grid import generate_grid, generate_range

runner = BatchRunner(
    pine_path="my_strategy.pine",
    data_paths=["nq_1m.csv"],
    param_grid=generate_grid({
        "slPoints":      generate_range(8, 14, 0.5),   # 8.0, 8.5, ... 14.0
        "pivotLeft":     [1, 2, 3],
        "pivotRight":    [1, 2, 3],
        "minRangeTicks": [16, 20, 24],
    }),
    start_date="2025-01-01",
    end_date="2025-12-31",
    point_value=20.0,   # NQ = $20/point
)
results = runner.run(workers=8, output_csv="sweep_results.csv")
```

Results include PF, WR, trade count, max DD, Sharpe, per-param combo. See `scripts/example_sweep.py` for a complete runnable template.

---

## Python API

```python
from pine_engine.engine import compile_pine, run_backtest
from pine_engine.data.loader import load_bars_csv
from pine_engine.reporting.stats import compute_stats, format_stats

compiled = compile_pine("my_strategy.pine")
bars     = load_bars_csv("nq_1m.csv", start_date="2025-01-01", end_date="2025-12-31")
trades   = run_backtest(compiled, bars, params={"slPoints": 11.25})
stats    = compute_stats(trades, point_value=20.0)

print(format_stats(stats))
for t in trades[-5:]:
    print(t.entry_time, t.side, t.entry_price, "→", t.exit_price, t.exit_comment)
```

---

## What Pine v5 subset is supported

| Category | Supported |
|---|---|
| `strategy()` declaration + `default_qty_*` | Yes |
| `input.int / float / bool / string / color` | Yes |
| `var` / `varip` declarations | Yes |
| Full control flow: `if / else / for / while` | Yes |
| Series indexing (`close[1]`, `high[N]`) | Yes |
| Pine built-ins: `ta.pivothigh`, `ta.pivotlow`, `ta.rsi`, `ta.atr`, `ta.sma`, `ta.ema`, `ta.crossover`, `ta.change`, `math.*`, `str.tostring`, `hour`, `minute`, `dayofweek`, `dayofmonth`, `year`, `month`, `timestamp` | Yes |
| `strategy.entry / order / exit / close / close_all / cancel / cancel_all` | Yes |
| `strategy.position_size / equity / opentrades / closedtrades` | Yes |
| `alertcondition` / `alert()` | parsed, not executed (no external alerts) |
| `plot / plotshape / label / line / box` | parsed, silently no-op (no rendering) |
| `request.security` (MTF) | No |
| Libraries (`import X as Y`) | No |
| User-defined types / methods | No |

If your `.pine` file uses something unsupported, `compile_pine()` will raise a clear error pointing at the unsupported AST node.

---

## Validation against TradingView

The engine ships with TV-export comparison scripts. Workflow:

1. In TradingView, run your strategy on the chart and export the "List of Trades" as CSV.
2. Run the same strategy locally on the same date range and data.
3. Compare trade counts, entry/exit bars, WR.

Known parity status (NQ 1-min, v6.3 variants):

| Date range | TV trades | Engine trades | WR TV | WR Engine |
|---|---|---|---|---|
| 2023-04 → 2023-08 | 74 | 74 | 21.6% | 21.6% |
| 2025-03 → 2026-03 | 213 | 227 | 23.5% | 21.1% |

Remaining ~6% over-trade on 12-month runs is equity-drift → qty parity (the engine uses `strategy.equity` in dollars; TV's qty sizing shifts with equity on percent-of-equity sizing). The fix is tick-level fills, not codegen.

---

## Project layout

```
pine_engine/
├── lexer.py              # tokenizer (Pine v5 → tokens)
├── parser.py             # recursive-descent parser → AST
├── ast_nodes.py          # AST node dataclasses
├── codegen.py            # AST → Python source (the transpiler core)
├── engine.py             # top-level: compile_pine + run_backtest
├── main.py               # CLI entry point
├── runtime/
│   ├── broker.py         # Bar, ClosedTrade, limit/market fill logic
│   ├── strategy.py       # StrategyAPI (mirrors strategy.*)
│   ├── series.py         # Series (Pine's [N] history access)
│   ├── builtins.py       # ta.*, math.*, str.*, time builtins
│   └── na.py             # NA sentinel
├── batch/
│   ├── runner.py         # parallel sweep runner
│   └── param_grid.py     # generate_grid, generate_range
├── reporting/
│   ├── stats.py          # PF, WR, DD, Sharpe, expectancy
│   └── trade_log.py      # CSV trade export
├── data/loader.py        # CSV → list[Bar]
└── tests/                # unit tests (lexer, parser, codegen, end-to-end)

scripts/                  # example sweep + analysis scripts
data/                     # sample TV exports (for validation only, not input bars)
output/                   # default sweep output location (gitignored)
```

---

## Running the tests

```bash
python -m unittest discover pine_engine/tests/ -v
```

---

## Known limitations

- **Intrabar fills**: bars are processed on close — limits fill at bar close if `touched`, not at the exact price within the bar. For most 1-min strategies this is fine; for scalping use tick data and extend `runtime/broker.py`.
- **`calc_on_every_tick=true`**: not supported. Engine always runs in close-only mode.
- **Floating-point equity drift**: after hundreds of trades, engine's qty sizing on percent-of-equity can diverge from TV by a few percent. Use fixed-qty sizing for max parity.
- **No order-book / slippage / commissions** by default. Set `point_value` in `compute_stats()` to dollar-normalize; add slippage in `runtime/broker.py:register_entry` if needed.

---

## License

MIT — use it, fork it, make money with it, no warranty.

See [`CLAUDE.md`](./CLAUDE.md) for Claude Code / AI-agent-specific usage notes.
