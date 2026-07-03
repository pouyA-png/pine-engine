#!/usr/bin/env python3
"""Run a .pine strategy through the pine-engine and dump ALL closed trades to CSV.
Shared foundation for the quant-validation workflow — every agent reads these CSVs.
Usage: python3 quant/export_trades.py --pine F --data CSV [--start D --end D] --out OUT.csv [--param k=v ...]
"""
import argparse, csv, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pine_engine.engine import compile_pine, run_backtest
from pine_engine.data.loader import load_bars_csv


def pnl_points(t):
    d = (t.exit_price - t.entry_price) if t.side == "long" else (t.entry_price - t.exit_price)
    return d  # per-contract points


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pine", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--param", action="append", default=[])
    args = ap.parse_args()

    c = compile_pine(args.pine)
    bars = load_bars_csv(args.data, start_date=args.start, end_date=args.end)
    params = {}
    for p in args.param:
        k, v = p.split("=", 1)
        if v.lower() in ("true", "false"):
            v = (v.lower() == "true")
        else:
            try:
                v = float(v) if "." in v or v.replace("-", "").isdigit() else v
            except Exception:
                pass
        params[k] = v
    trades = run_backtest(c, bars, params or None)
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["entry_time", "exit_time", "side", "qty", "entry", "exit",
                    "entry_comment", "exit_comment", "pnl_pts_per_contract", "pnl_pts_total"])
        for t in trades:
            ppc = pnl_points(t)
            w.writerow([t.entry_time.isoformat(), t.exit_time.isoformat(), t.side, t.qty,
                        f"{t.entry_price:.4f}", f"{t.exit_price:.4f}",
                        t.entry_comment, t.exit_comment, f"{ppc:.4f}", f"{ppc*t.qty:.4f}"])
    print(f"wrote {len(trades)} trades -> {args.out}  bars={len(bars)}")


if __name__ == "__main__":
    main()
