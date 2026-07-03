#!/usr/bin/env python3
"""Optimize v25cris on the LAST YEAR (NQ fallback; FTMO history too short).
Interruption-safe: each finished config is appended to a JSONL immediately."""
import sys, json
from concurrent.futures import ProcessPoolExecutor, as_completed
sys.path.insert(0, "/home/pouya/pine-engine")
from pine_engine.batch.runner import _run_single
from pine_engine.batch.param_grid import generate_grid

BOT = "/mnt/c/Users/nader/Documents/Claude-memories/trading bot/trading_bot.pine"
DATA = "/home/pouya/pine-engine/quant/nq_lastyear.csv"
OUT = "/tmp/claude-1000/-home-pouya/df461499-5170-4d6c-bc06-333ca04eea33/scratchpad/sweep_lastyear.jsonl"

grid = generate_grid({
    "slPoints":           [9.0, 11.25, 13.5, 16.0],
    "slPointsWedThu":     [10.0, 12.5, 15.0],
    "cutoffAfterOpenMin": [30, 45, 60],
    "minRangeTicks":      [16, 20, 28],
})
print(f"Grid: {len(grid)} configs", flush=True)
open(OUT, "w").close()

done = 0
with ProcessPoolExecutor(max_workers=7) as pool:
    futs = {pool.submit(_run_single, BOT, DATA, p, None, None, 20.0): p for p in grid}
    with open(OUT, "a") as f:
        for fut in as_completed(futs):
            p = futs[fut]
            try:
                s = fut.result()
                rec = {k: s.get(k) for k in ("profit_factor", "net_pnl", "max_drawdown", "total_trades", "win_rate")}
                rec["params"] = p
                f.write(json.dumps(rec) + "\n"); f.flush()
            except Exception as e:
                f.write(json.dumps({"error": str(e)[:120], "params": p}) + "\n"); f.flush()
            done += 1
            if done % 20 == 0:
                print(f"  {done}/{len(grid)}", flush=True)
print(f"DONE {done}/{len(grid)}", flush=True)
