#!/usr/bin/env python3
"""
A/B: Efficiency-Ratio leg detector (trading_bot_5m_visualleg.pine) vs max_move
baseline, on the REAL FTMO M5 feed, conservative SL-first engine, ALL FILTERS OFF.

Isolates the leg-detection effect only: same level/entry/exit/SL mechanics as the
documented max_move FTMO run (PF 1.43 @ SL16). ER trades FEWER days (stands aside
on un-clean days) — the question is whether that selectivity lifts PF/expectancy/DD
per trade vs taking every day with max_move.

Usage: python3 er_ab.py [--data CSV] [--start D] [--end D] [--sl 16.0]
"""
import argparse, json
from collections import defaultdict
import leg_lab as L

WIN = 6  # i_legBars in the pine bot


def fmt(s):
    if not s or s.get("trades", 0) == 0:
        return "n=0"
    return (f"n={s['trades']:4d} days={s['days']:3d} WR={s['wr']:4.1f}% PF={s['pf']:4.2f} "
            f"net={s['net']:7.0f} DD={s['max_dd']:5.0f} expR={s['expectancy']:5.2f} "
            f"sharpe={s['sharpe']:4.2f}")


def run(days, method, sl):
    res = L.run_method(method, days, [sl])
    return L.stats(res[sl]), res[sl]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/mnt/c/Users/nader/US100_M5_FTMO_utc.csv")
    ap.add_argument("--start", default="2025-04-28")
    ap.add_argument("--end", default="2026-06-17")
    ap.add_argument("--sl", type=float, default=16.0)
    args = ap.parse_args()

    days = L.load_days(args.data, args.start, args.end)
    ndays = len(days)
    print(f"# data={args.data.split('/')[-1]} {args.start}..{args.end}  calendar_days={ndays}  SL={args.sl}  win={WIN}")
    print(f"# net/DD/expR are in POINTS (engine is point-based, not dollarized). All filters OFF, every level both halves.\n")

    # baseline
    mm = {"fam": "max_move", "p": {"win": WIN}, "id": -1, "name": "max_move_win6"}
    s_mm, _ = run(days, mm, args.sl)
    print(f"BASELINE max_move_win6        {fmt(s_mm)}")
    base_pf = s_mm["pf"]; base_exp = s_mm["expectancy"]
    print()

    # ER sweep
    print("ER sweep (dirLast=True, no fallback)  — stands aside on un-clean days:")
    header = f"{'minER':>5} {'minBars':>7}  metrics"
    print(header)
    grid_er = [0.35, 0.45, 0.55, 0.65, 0.75]
    grid_bars = [1, 2, 3]
    best = None
    for minER in grid_er:
        for mb in grid_bars:
            m = {"fam": "efficiency_ratio", "id": -2, "name": f"ER_{minER}_{mb}",
                 "p": {"win": WIN, "minER": minER, "minLegBars": mb, "dirLast": True,
                       "minRange": 5.0, "fallback": False}}
            s, _ = run(days, m, args.sl)
            mark = ""
            if s.get("trades", 0) >= 100:
                if best is None or s["pf"] > best[0]:
                    best = (s["pf"], minER, mb, s)
                if s["pf"] > base_pf: mark += " *PF>base"
                if s["expectancy"] > base_exp: mark += " *expR>base"
            print(f"{minER:>5} {mb:>7}  {fmt(s)}{mark}")

    print("\nER sweep (dirLast=False — seed dir from largest single move):")
    for minER in [0.45, 0.55, 0.65]:
        for mb in [1, 2]:
            m = {"fam": "efficiency_ratio", "id": -3, "name": f"ERf_{minER}_{mb}",
                 "p": {"win": WIN, "minER": minER, "minLegBars": mb, "dirLast": False,
                       "minRange": 5.0, "fallback": False}}
            s, _ = run(days, m, args.sl)
            print(f"{minER:>5} {mb:>7}  {fmt(s)}")

    print("\nER + fallback to max_move on un-clean days (trades every day like baseline):")
    for minER in [0.45, 0.55, 0.65]:
        for mb in [1, 2]:
            m = {"fam": "efficiency_ratio", "id": -4, "name": f"ERfb_{minER}_{mb}",
                 "p": {"win": WIN, "minER": minER, "minLegBars": mb, "dirLast": True,
                       "minRange": 5.0, "fallback": True}}
            s, _ = run(days, m, args.sl)
            print(f"{minER:>5} {mb:>7}  {fmt(s)}")

    if best:
        print(f"\nBEST ER (n>=100, by PF): minER={best[1]} minLegBars={best[2]}  {fmt(best[3])}")
        print(f"  vs baseline PF {base_pf:.2f} / expR {base_exp:.2f}")


if __name__ == "__main__":
    main()
