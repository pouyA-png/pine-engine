import leg_lab as L
from collections import defaultdict
import math

DATA="/mnt/c/Users/nader/US100_M5_FTMO_utc.csv"
SL=16.0
WIN=6
days = L.load_days(DATA,"2025-04-28","2026-06-17")
ks=sorted(days); mid=len(ks)//2
oos={k:days[k] for k in ks[mid:]}
full=days

mm={"fam":"max_move","p":{"win":WIN},"id":-1,"name":"mm"}
erf={"fam":"efficiency_ratio","id":-3,"name":"ERf",
     "p":{"win":WIN,"minER":0.55,"minLegBars":1,"dirLast":False,"minRange":5.0,"fallback":False}}

def trades(dd,m): return L.run_method(m,dd,[SL])[SL]

def pf_net(ts,cost=0.0):
    # subtract flat cost per trade record
    gp=gl=0.0
    for t in ts:
        p=t["pnl"]-cost
        if p>0: gp+=p
        else: gl+=-p
    return (gp/gl if gl else float('inf')), gp-gl, len(ts)

# (1) Reproduce OOS flat-cost
print("=== (1) OOS flat per-trade cost (confirm claim) ===")
for name,m in [("max_move",mm),("ER dirF",erf)]:
    ts=trades(oos,m)
    row=[]
    for c in [0,1,2,2.5]:
        pf,net,n=pf_net(ts,c)
        row.append(f"{c}pt:PF={pf:.2f}")
    print(f"  {name:10s} n={len(ts)}  "+"  ".join(row))

print()
print("=== (c) SELECTION vs QUALITY: common days only (OOS) ===")
mm_ts=trades(oos,mm); erf_ts=trades(oos,erf)
mm_days=set(t["date"] for t in mm_ts)
erf_days=set(t["date"] for t in erf_ts)
common=mm_days & erf_days
print(f"  mm trades {len(mm_days)} days, ER trades {len(erf_days)} days, common={len(common)}")
print(f"  days ER stands aside (mm trades, ER doesnt): {len(mm_days-erf_days)}")

def meanR(ts): 
    rs=[t["rr"] for t in ts]; 
    return sum(rs)/len(rs), len(rs)

# all trades
print("\n  -- ALL OOS trades --")
for name,ts in [("max_move",mm_ts),("ER dirF",erf_ts)]:
    mu,n=meanR(ts); pf,net,_=pf_net(ts)
    print(f"    {name:10s} meanR={mu:.3f} PF={pf:.2f} n={n}")

# common days only: does ER pick BETTER trades on the SAME days, or same quality?
mm_common=[t for t in mm_ts if t["date"] in common]
erf_common=[t for t in erf_ts if t["date"] in common]
print("\n  -- COMMON days only (both trade) --")
for name,ts in [("max_move",mm_common),("ER dirF",erf_common)]:
    mu,n=meanR(ts); pf,net,_=pf_net(ts)
    print(f"    {name:10s} meanR={mu:.3f} PF={pf:.2f} n={n}")

# the days ER stands aside on: how would mm have done there?
aside=mm_days-erf_days
mm_aside=[t for t in mm_ts if t["date"] in aside]
mu,n=meanR(mm_aside); pf,net,_=pf_net(mm_aside)
print(f"\n  -- mm on days ER SKIPS (n={n}) -- meanR={mu:.3f} PF={pf:.2f} net={net:.0f}")
print("    (if this is BAD, ER's edge = avoiding these = SELECTION not per-trade quality)")

print()
print("=== (a) ASYMMETRIC SLIPPAGE: stops slip, limits/TP do not ===")
# Realistic model: limit ENTRY fills at exact level (pay ~0 spread, already optimistic).
# Exits: TP = limit, fills at level (~0 slip). SL/BE/EOD = market-ish, slip AGAINST us.
# Model: subtract entry_spread on every trade + extra stop_slip on SL/BE/EOD exits.
from collections import Counter
for name,ts in [("max_move",mm_ts),("ER dirF",erf_ts)]:
    oc=Counter(t["outcome"] for t in ts)
    print(f"  {name}: {dict(oc)}")

def pf_asym(ts, entry_spread, stop_slip):
    gp=gl=0.0
    for t in ts:
        p=t["pnl"]-entry_spread
        if t["outcome"] in ("SL","BE","EOD"):
            p-=stop_slip
        if p>0: gp+=p
        else: gl+=-p
    return (gp/gl if gl else float('inf')), gp-gl

print("\n  entry_spread=2.0pt fixed, vary stop_slip (extra pts stops slip past level):")
print(f"  {'slip':>5} {'max_move PF':>12} {'ER dirF PF':>11}")
for slip in [0,1,2,3,4]:
    pm,_=pf_asym(mm_ts,2.0,slip)
    pe,_=pf_asym(erf_ts,2.0,slip)
    print(f"  {slip:>5} {pm:>12.2f} {pe:>11.2f}")

print()
print("=== Is stop-slip plausible on US100 M5? bar-range distribution (OOS session bars) ===")
ranges=[]
for d in sorted(oos):
    pre,ses=L.split_day(oos[d])
    for b in ses:
        ranges.append(b["h"]-b["l"])
ranges.sort()
n=len(ranges)
def pct(p): return ranges[int(p*n)]
print(f"  session 5m bar high-low range pts: median={pct(.5):.1f} p75={pct(.75):.1f} p90={pct(.90):.1f} p95={pct(.95):.1f} max={ranges[-1]:.1f}")
print("  (a stop placed inside such a bar can be filled anywhere in this range -> slip is a real fraction of these)")

print()
print("=== (b) limit-entry optimism + SL-first: does ER win because it enters FEWER but the SAME-quality? ===")
# net contribution: at the claimed 2.5pt FLAT cost, ER net advantage in points
def net_flat(ts,c):
    return sum(t["pnl"]-c for t in ts)
print(f"  OOS net @2.5pt flat: max_move={net_flat(mm_ts,2.5):.0f}pt  ER dirF={net_flat(erf_ts,2.5):.0f}pt")
# but PF is what claim cites. The point: ER's lower trade COUNT (286 vs 432) means 2.5pt flat
# costs ER less total drag. Re-express: ER pays 286*2.5=715pt, mm pays 432*2.5=1080pt
print(f"  total flat-cost drag: max_move pays {432*2.5:.0f}pt, ER pays {286*2.5:.0f}pt  -> ER saves {(432-286)*2.5:.0f}pt JUST from fewer trades")

print()
print("=== combined realistic: entry 2pt + stop slip 2.5pt (US100 5m plausible) ===")
pm,nm=pf_asym(mm_ts,2.0,2.5); pe,ne=pf_asym(erf_ts,2.0,2.5)
print(f"  max_move PF={pm:.2f} net={nm:.0f}pt   ER dirF PF={pe:.2f} net={ne:.0f}pt")
