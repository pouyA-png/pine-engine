#!/usr/bin/env python3
"""Shared evaluator for the v25opt parameter search.
Loads in-sample + out-of-sample bars ONCE, evaluates a whole grid of param dicts,
prints one JSON array. Every sweep agent uses this so metrics are identical.

Usage:
  python3 quant/opt_eval.py --pine F.pine --data quant/nq_2yr.csv \
     --is-start 2024-03-13 --is-end 2025-07-04 \
     --oos-start 2025-07-05 --oos-end 2026-03-13 \
     --grid '[{"i_extraTP":0},{"i_extraTP":100}]'
"""
import argparse, json, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pine_engine.engine import compile_pine, run_backtest
from pine_engine.data.loader import load_bars_csv


def ppc(t):
    return (t.exit_price - t.entry_price) if t.side == "long" else (t.entry_price - t.exit_price)


def stats(trades):
    n = len(trades)
    if n == 0:
        return {"n": 0, "wr": 0.0, "pf": 0.0, "net": 0.0, "maxdd": 0.0, "avg": 0.0}
    pnls = [ppc(t) for t in trades]
    wins = [p for p in pnls if p > 0]
    gp = sum(p for p in pnls if p > 0)
    gl = -sum(p for p in pnls if p < 0)
    net = sum(pnls)
    eq = 0.0
    peak = 0.0
    maxdd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        maxdd = max(maxdd, peak - eq)
    return {"n": n, "wr": round(100 * len(wins) / n, 1),
            "pf": round(gp / gl, 3) if gl else 999.0,
            "net": round(net, 1), "maxdd": round(maxdd, 1),
            "avg": round(net / n, 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pine", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--is-start", required=True)
    ap.add_argument("--is-end", required=True)
    ap.add_argument("--oos-start", required=True)
    ap.add_argument("--oos-end", required=True)
    ap.add_argument("--grid", required=True, help="JSON list of param dicts")
    args = ap.parse_args()

    grid = json.loads(args.grid)
    c = compile_pine(args.pine)
    is_bars = load_bars_csv(args.data, start_date=args.is_start, end_date=args.is_end)
    oos_bars = load_bars_csv(args.data, start_date=args.oos_start, end_date=args.oos_end)

    out = []
    for cfg in grid:
        params = {k: v for k, v in cfg.items()}
        s_is = stats(run_backtest(c, is_bars, params or None))
        s_oos = stats(run_backtest(c, oos_bars, params or None))
        out.append({"config": cfg, "is": s_is, "oos": s_oos})
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
