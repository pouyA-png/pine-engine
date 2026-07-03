#!/usr/bin/env python3
"""Adversarial significance test: per-DAY independence + bootstrap of OOS edge."""
import math, random
from collections import defaultdict
import leg_lab as L

WIN = 6
SL = 16.0
random.seed(12345)

days = L.load_days("/mnt/c/Users/nader/US100_M5_FTMO_utc.csv", "2025-04-28", "2026-06-17")
ks = sorted(days)
mid = len(ks) // 2
oos_keys = set(k.isoformat() for k in ks[mid:])
is_keys = set(k.isoformat() for k in ks[:mid])

mm = {"fam": "max_move", "p": {"win": WIN}, "id": -1, "name": "max_move"}
er = {"fam": "efficiency_ratio", "id": -3, "name": "ER_dirFalse_0.55_1",
      "p": {"win": WIN, "minER": 0.55, "minLegBars": 1, "dirLast": False, "minRange": 5.0, "fallback": False}}

def trades(m): return L.run_method(m, days, [SL])[SL]

def per_day_pnl(tr, cost):
    """net points per day after subtracting cost per trade (each half = 1 trade)."""
    d = defaultdict(float)
    for t in tr:
        d[t["date"]] += t["pnl"] - cost
    return d

def per_day_rr(tr):
    d = defaultdict(float); n = defaultdict(int)
    for t in tr:
        d[t["date"]] += t["rr"]; n[t["date"]] += 1
    return d  # sum of RR per day

mm_tr = trades(mm); er_tr = trades(er)

def tstat(xs):
    n=len(xs)
    if n<2: return 0,0,0
    mu=sum(xs)/n
    sd=(sum((x-mu)**2 for x in xs)/(n-1))**0.5
    t=mu/(sd/math.sqrt(n)) if sd else 0
    return mu,t,n

print("=== PER-TRADE vs PER-DAY t-stat (mean RR), FULL period ===")
for name,tr in [("max_move",mm_tr),("ER dirF",er_tr)]:
    rr=[t["rr"] for t in tr]
    mu,t,n=tstat(rr)
    pd=per_day_rr(tr)
    pdv=list(pd.values())
    mud,td,nd=tstat(pdv)
    print(f"{name:9s} per-trade: meanRR={mu:.3f} t={t:.2f} n={n}  |  per-DAY sumRR: mean={mud:.3f} t={td:.2f} days={nd}")

print("\n=== OOS net per day, after cost; difference test (ER - max_move) ===")
for cost in [0.0,1.0,2.0,2.5]:
    mm_pd=per_day_pnl(mm_tr,cost); er_pd=per_day_pnl(er_tr,cost)
    # OOS day universe = union of days either method traded
    oos_days=sorted(d for d in oos_keys if d in mm_pd or d in er_pd)
    # paired daily difference (0 if a method didn't trade that day)
    diffs=[]
    mm_vals=[]; er_vals=[]
    for d in oos_days:
        mv=mm_pd.get(d,0.0); ev=er_pd.get(d,0.0)
        mm_vals.append(mv); er_vals.append(ev); diffs.append(ev-mv)
    mud,td,nd=tstat(diffs)
    mu_mm,t_mm,_=tstat([v for v in mm_vals])
    mu_er,t_er,_=tstat([v for v in er_vals])
    # bootstrap diff mean CI
    B=20000; boot=[]
    for _ in range(B):
        s=sum(random.choice(diffs) for _ in range(nd))/nd
        boot.append(s)
    boot.sort()
    lo=boot[int(0.025*B)]; hi=boot[int(0.975*B)]
    p_gt0=sum(1 for b in boot if b<=0)/B  # frac of bootstrap means <=0
    print(f"cost={cost:3.1f}: ER/day mean={mu_er:+.2f}(t={t_er:.2f}) MM/day mean={mu_mm:+.2f}(t={t_mm:.2f}) "
          f"DIFF mean={mud:+.2f} t={td:.2f} 95%CI=[{lo:+.2f},{hi:+.2f}] P(diff<=0)={p_gt0:.3f} days={nd}")

print("\n=== OOS per-DAY net t-stat each method (after 2.5pt cost) standalone ===")
cost=2.5
mm_pd=per_day_pnl(mm_tr,cost); er_pd=per_day_pnl(er_tr,cost)
mm_oos=[v for d,v in mm_pd.items() if d in oos_keys]
er_oos=[v for d,v in er_pd.items() if d in oos_keys]
print("max_move OOS days traded:",tstat(mm_oos))
print("ER       OOS days traded:",tstat(er_oos))

print("\n=== Permutation test on OOS diff (sign-flip, 20000) ===")
oos_days=sorted(d for d in oos_keys if d in mm_pd or d in er_pd)
diffs=[er_pd.get(d,0.0)-mm_pd.get(d,0.0) for d in oos_days]
obs=sum(diffs)/len(diffs)
B=20000; ge=0
for _ in range(B):
    s=sum(d*random.choice((1,-1)) for d in diffs)/len(diffs)
    if s>=obs: ge+=1
print(f"observed diff mean={obs:+.2f}  one-sided perm p={ge/B:.3f}")
