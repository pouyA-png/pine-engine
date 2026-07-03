#!/usr/bin/env python3
"""Sweep v25's LEG-DETECTION shaping params in the REAL engine (the knobs that decide WHICH
leg v25 draws — impulse-origin, accum-zone, window timing). Split-half validated: a WIN must
beat v25 PF in BOTH halves AND the year. This optimises leg-FINDING on the real detector.
baseline (slPoints=13.5): H1 1.98 / H2 2.81 / YEAR 2.50.
"""
import sys, json, itertools
from concurrent.futures import ProcessPoolExecutor, as_completed
sys.path.insert(0, "/home/pouya/pine-engine")

BOT = "/tmp/claude-1000/-home-pouya/df461499-5170-4d6c-bc06-333ca04eea33/scratchpad/bot_lastyear.pine"
DATA = "/home/pouya/pine-engine/quant/nq_lastyear.csv"
OUT = "/tmp/claude-1000/-home-pouya/df461499-5170-4d6c-bc06-333ca04eea33/scratchpad/sweep_legdetect.jsonl"
SPLIT = "2025-09-13"
BASE = {"H1": 1.98, "H2": 2.81, "YEAR": 2.50}

GRID = {
    "impulseExtendRatio":  [1.0, 1.1, 1.2, 1.4, 1.6],
    "impulseLookbackBars": [25, 35, 50, 65],
    "accumZoneMin":        [8, 10, 15],
    "winEndM":             [25, 29],
}


def run_one(params):
    from pine_engine.engine import compile_pine, run_backtest
    from pine_engine.data.loader import load_bars_csv
    from pine_engine.reporting.stats import compute_stats
    c = compile_pine(BOT)
    p = dict(params); p["slPoints"] = 13.5
    out = {}
    for lbl, sd, ed in [("H1", None, SPLIT), ("H2", "2025-09-14", None), ("YEAR", None, None)]:
        bars = load_bars_csv(DATA, start_date=sd, end_date=ed)
        tr = run_backtest(c, bars, p)
        st = compute_stats(tr, point_value=20.0)
        out[lbl] = {"pf": round(st["profit_factor"], 3), "net": round(st["net_pnl"]), "trades": st["total_trades"]}
    out["params"] = params
    out["beats_both"] = (out["H1"]["pf"] > BASE["H1"] and out["H2"]["pf"] > BASE["H2"] and out["YEAR"]["pf"] > BASE["YEAR"])
    return out


def main():
    keys = list(GRID)
    grid = [dict(zip(keys, vals)) for vals in itertools.product(*GRID.values())]
    print(f"Grid: {len(grid)} leg-detection configs", flush=True)
    open(OUT, "w").close()
    done = winners = 0
    with ProcessPoolExecutor(max_workers=7) as pool:
        futs = {pool.submit(run_one, g): g for g in grid}
        with open(OUT, "a") as f:
            for fut in as_completed(futs):
                g = futs[fut]
                try:
                    rec = fut.result()
                except Exception as e:
                    rec = {"error": str(e)[:140], "params": g, "beats_both": False}
                f.write(json.dumps(rec) + "\n"); f.flush()
                done += 1
                if rec.get("beats_both"):
                    winners += 1
                    print(f"  WIN {done}/{len(grid)}: {g} -> H1 {rec['H1']['pf']} H2 {rec['H2']['pf']} YEAR {rec['YEAR']['pf']} Net{rec['YEAR']['net']:+d}", flush=True)
                elif done % 20 == 0:
                    print(f"  {done}/{len(grid)} ({winners} winners)", flush=True)
    print(f"DONE {done}/{len(grid)} winners={winners}", flush=True)


if __name__ == "__main__":
    main()
