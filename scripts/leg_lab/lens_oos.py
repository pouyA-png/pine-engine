#!/usr/bin/env python3
import leg_lab as L
from collections import defaultdict

DATA = "/mnt/c/Users/nader/US100_M5_FTMO_utc.csv"
SL = 16.0
OOS_START = "2025-11-21"
OOS_END = "2026-06-17"

days = L.load_days(DATA, OOS_START, OOS_END)
print(f"OOS calendar_days={len(days)}  {OOS_START}..{OOS_END}")

mm = {"fam": "max_move", "p": {"win": 6}, "id": -1, "name": "max_move"}
er = {"fam": "efficiency_ratio",
      "p": {"win": 6, "minER": 0.55, "minLegBars": 1, "dirLast": False, "fallback": False},
      "id": -2, "name": "ER_dirFalse_0.55_1"}

res_mm = L.run_method(mm, days, [SL])[SL]
res_er = L.run_method(er, days, [SL])[SL]


def pf_of(trades, cost=0.0):
    gp = gl = 0.0
    for t in trades:
        p = t["pnl"] - cost
        if p > 0:
            gp += p
        else:
            gl += -p
    if gl == 0:
        return float('inf'), 0, 0.0
    return gp / gl, len(trades), (gp - gl)


def bucket(trades, keyfn):
    g = defaultdict(list)
    for t in trades:
        g[keyfn(t["date"])].append(t)
    return g


def ym(d):  # date is ISO 'YYYY-MM-DD'
    return d[:7]


def quarter(d):
    y = d[:4]; m = int(d[5:7])
    q = (m - 1) // 3 + 1
    return f"{y}Q{q}"


print("\n=== FULL OOS ===")
for cost in (0.0, 2.0, 2.5):
    pm, nm, netm = pf_of(res_mm, cost)
    pe, ne, nete = pf_of(res_er, cost)
    print(f" cost={cost}pt  max_move PF={pm:.3f} (n={nm}, net={netm:.0f})  "
          f"ER PF={pe:.3f} (n={ne}, net={nete:.0f})  ER_edge={pe-pm:+.3f}")

print("\n=== MONTH-BY-MONTH (cost=0) ===")
gm = bucket(res_mm, ym); ge = bucket(res_er, ym)
months = sorted(set(gm) | set(ge))
print(f"{'month':>8} | {'mm_PF':>6} {'mm_n':>5} {'mm_net':>8} | {'er_PF':>6} {'er_n':>5} {'er_net':>8} | {'ER_ahead?':>9}")
er_wins = 0; total_months = 0
for mth in months:
    pm, nm, netm = pf_of(gm.get(mth, []))
    pe, ne, nete = pf_of(ge.get(mth, []))
    ahead = "YES" if pe > pm else ("tie" if abs(pe-pm) < 1e-9 else "no")
    if pe > pm: er_wins += 1
    total_months += 1
    pms = f"{pm:.2f}" if pm != float('inf') else "inf"
    pes = f"{pe:.2f}" if pe != float('inf') else "inf"
    print(f"{mth:>8} | {pms:>6} {nm:>5} {netm:>8.0f} | {pes:>6} {ne:>5} {nete:>8.0f} | {ahead:>9}")
print(f"ER ahead in {er_wins}/{total_months} months (PF, cost=0)")

print("\n=== MONTH-BY-MONTH (cost=2.0pt) ===")
print(f"{'month':>8} | {'mm_PF':>6} {'mm_net':>8} | {'er_PF':>6} {'er_net':>8} | {'edge_net':>8}")
for mth in months:
    pm, nm, netm = pf_of(gm.get(mth, []), 2.0)
    pe, ne, nete = pf_of(ge.get(mth, []), 2.0)
    pms = f"{pm:.2f}" if pm != float('inf') else "inf"
    pes = f"{pe:.2f}" if pe != float('inf') else "inf"
    print(f"{mth:>8} | {pms:>6} {netm:>8.0f} | {pes:>6} {nete:>8.0f} | {nete-netm:>+8.0f}")

print("\n=== QUARTER-BY-QUARTER (cost=0 and cost=2.0) ===")
qm = bucket(res_mm, quarter); qe = bucket(res_er, quarter)
quarters = sorted(set(qm) | set(qe))
for c in (0.0, 2.0):
    print(f" -- cost={c}pt --")
    for q in quarters:
        pm, nm, netm = pf_of(qm.get(q, []), c)
        pe, ne, nete = pf_of(qe.get(q, []), c)
        pms = f"{pm:.2f}" if pm != float('inf') else "inf"
        pes = f"{pe:.2f}" if pe != float('inf') else "inf"
        print(f"  {q}: max_move PF={pms} (n={nm} net={netm:.0f}) | ER PF={pes} (n={ne} net={nete:.0f}) | edge_net={nete-netm:+.0f}")

# Concentration test: how much of ER's net edge (cost=2) comes from the single best month?
print("\n=== CONCENTRATION (ER net edge over max_move, cost=2.0pt, by month) ===")
edges = []
for mth in months:
    _, _, netm = pf_of(gm.get(mth, []), 2.0)
    _, _, nete = pf_of(ge.get(mth, []), 2.0)
    edges.append((mth, nete - netm))
edges.sort(key=lambda x: x[1])
total_edge = sum(e for _, e in edges)
print(f"Total ER net edge over max_move (cost=2): {total_edge:+.0f} pts")
for mth, e in sorted(edges, key=lambda x: -x[1]):
    share = (e/total_edge*100) if total_edge else 0
    print(f"  {mth}: edge {e:+8.0f}  ({share:+5.1f}% of total)")
