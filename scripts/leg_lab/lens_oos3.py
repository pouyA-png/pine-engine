#!/usr/bin/env python3
import leg_lab as L
DATA = "/mnt/c/Users/nader/US100_M5_FTMO_utc.csv"
SL = 16.0
mm = {"fam": "max_move", "p": {"win": 6}, "id": -1, "name": "mm"}
er = {"fam": "efficiency_ratio",
      "p": {"win": 6, "minER": 0.55, "minLegBars": 1, "dirLast": False, "fallback": False}, "id": -2, "name": "er"}

def pf(trades, cost=0.0):
    gp = gl = 0.0
    for t in trades:
        p = t["pnl"] - cost
        if p > 0: gp += p
        else: gl += -p
    return (gp/gl) if gl else float('inf')

print("=== OOS-START SENSITIVITY: shift the OOS boundary, cost=2.0pt ===")
print("If the edge is a window artifact, it should flip sign as the boundary moves.")
starts = ["2025-10-01","2025-11-01","2025-11-21","2025-12-01","2026-01-01","2026-02-01","2026-03-01"]
for s in starts:
    days = L.load_days(DATA, s, "2026-06-17")
    rm = L.run_method(mm, days, [SL])[SL]
    re = L.run_method(er, days, [SL])[SL]
    pm = pf(rm,2.0); pe = pf(re,2.0)
    print(f"  OOS {s}..end (cal={len(days)}): max_move PF={pm:.3f} (n={len(rm)})  ER PF={pe:.3f} (n={len(re)})  edge={pe-pm:+.3f}")
