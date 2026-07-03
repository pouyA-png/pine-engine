#!/usr/bin/env python3
import leg_lab as L
from collections import defaultdict

DATA = "/mnt/c/Users/nader/US100_M5_FTMO_utc.csv"
SL = 16.0
days = L.load_days(DATA, "2025-11-21", "2026-06-17")
mm = {"fam": "max_move", "p": {"win": 6}, "id": -1, "name": "mm"}
er = {"fam": "efficiency_ratio",
      "p": {"win": 6, "minER": 0.55, "minLegBars": 1, "dirLast": False, "fallback": False}, "id": -2, "name": "er"}
res_mm = L.run_method(mm, days, [SL])[SL]
res_er = L.run_method(er, days, [SL])[SL]


def pf(trades, cost=0.0):
    gp = gl = 0.0
    for t in trades:
        p = t["pnl"] - cost
        if p > 0: gp += p
        else: gl += -p
    return (gp/gl) if gl else float('inf')


def ym(d): return d[:7]


gm = defaultdict(list); ge = defaultdict(list)
for t in res_mm: gm[ym(t["date"])].append(t)
for t in res_er: ge[ym(t["date"])].append(t)
months = sorted(set(gm) | set(ge))

print("=== LEAVE-ONE-MONTH-OUT: full-OOS PF after dropping each month (cost=2.0) ===")
print("Does ER stay ahead of max_move when any single month is removed?")
for drop in months:
    keep_mm = [t for t in res_mm if ym(t["date"]) != drop]
    keep_er = [t for t in res_er if ym(t["date"]) != drop]
    pm = pf(keep_mm, 2.0); pe = pf(keep_er, 2.0)
    flag = "ER>mm" if pe > pm else "ER<=mm"
    print(f"  drop {drop}: max_move PF={pm:.3f}  ER PF={pe:.3f}  edge={pe-pm:+.3f}  {flag}  | ER<1? {'YES' if pe<1 else 'no'}")

print("\n=== ER absolute PF (cost=2) leave-one-month-out — does ER stay profitable (>1)? ===")
for drop in months:
    keep_er = [t for t in res_er if ym(t["date"]) != drop]
    pe = pf(keep_er, 2.0)
    print(f"  drop {drop}: ER PF={pe:.3f}")

# Worst-case: drop the two best ER-edge months (Dec + Mar) simultaneously
print("\n=== Drop the 2 best edge-months (2025-12, 2026-03) together (cost=2) ===")
best2 = {"2025-12", "2026-03"}
km = [t for t in res_mm if ym(t["date"]) not in best2]
ke = [t for t in res_er if ym(t["date"]) not in best2]
print(f"  max_move PF={pf(km,2.0):.3f}  ER PF={pf(ke,2.0):.3f}  edge={pf(ke,2.0)-pf(km,2.0):+.3f}")

# Sign stability of monthly NET edge
print("\n=== Sign of monthly ER-net-edge (cost=2) ===")
pos = neg = 0
for mth in months:
    netm = sum(t["pnl"]-2.0 for t in gm.get(mth, []))
    nete = sum(t["pnl"]-2.0 for t in ge.get(mth, []))
    e = nete - netm
    if e > 0: pos += 1
    else: neg += 1
print(f"  positive-edge months: {pos}/{len(months)}   negative: {neg}/{len(months)}")
