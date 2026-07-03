#!/usr/bin/env python3
"""Pre-register the validation foundation: per-period day-windows (for running detectors) +
v25 baseline PF per regime. Built ONCE, frozen. Detectors are judged against THIS, no moving goalposts.
Periods: 2021-22 (bear), 2025-26 (bull/OOS), 2016-17 (3rd holdout).
"""
import sys, json, pickle
sys.path.insert(0, "/home/pouya/pine-engine")
sys.path.insert(0, "/home/pouya/pine-engine/quant/legcal")
import leg_candidates as L
from export_dashboard import build_tf_stream
from pine_engine.engine import compile_pine, run_backtest
from pine_engine.data.loader import load_bars_csv
from pine_engine.reporting.stats import compute_stats

SC = "/tmp/claude-1000/-home-pouya/df461499-5170-4d6c-bc06-333ca04eea33/scratchpad"
BASE = SC + "/bot_lastyear.pine"
PV = 20.0
PERIODS = {
    "2021-22": SC + "/nq_2122.csv",
    "2025-26": "/home/pouya/pine-engine/quant/nq_lastyear.csv",
    "2016-17": "/home/pouya/pine-engine/quant/nq_1617.csv",
}


def v25_pf(csv):
    c = compile_pine(BASE)
    bars = load_bars_csv(csv)
    tr = run_backtest(c, bars, {"slPoints": 13.5})
    s = compute_stats(tr, point_value=PV)
    return round(s["profit_factor"], 3), round(s["net_pnl"])


ds, de = L.hhmm("06:00"), L.hhmm("23:00")
ls, le = L.hhmm("08:00"), L.hhmm("09:30")
baselines = {}
for period, csv in PERIODS.items():
    print(f"building {period} ...", flush=True)
    d1 = build_tf_stream(csv, [2, 3, 5], 8.0, 0.10, ds, de, ls, le, None)
    days = {}
    for d in sorted(d1):
        tf = d1[d]
        if tf["open_idx"] is None or tf["open_idx"] < 0 or len(tf["bars"]) < 200:
            continue
        days[d.isoformat()] = {"bars": tf["bars"], "tmin": tf["tmin"], "open_idx": tf["open_idx"]}
    pickle.dump(days, open(f"{SC}/cache_{period}.pkl", "wb"))
    pf, net = v25_pf(csv)
    baselines[period] = {"v25_pf": pf, "v25_net": net, "n_days": len(days)}
    print(f"  {period}: days={len(days)}  v25 PF={pf} Net=${net:+d}", flush=True)

json.dump(baselines, open(f"{SC}/baselines.json", "w"))
print("\n=== PRE-REGISTERED BASELINES (frozen) ===")
print(json.dumps(baselines, indent=2))
print("DONE", flush=True)
