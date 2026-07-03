#!/usr/bin/env python3
"""Overfit check: run the Cristiano-style recent-window bot AND v25 on BOTH periods
(2021-22 in-sample for R, 2025-26 out-of-sample). Consistent results = not overfit.
"""
import sys, json
sys.path.insert(0, "/home/pouya/pine-engine")
sys.path.insert(0, "/home/pouya/pine-engine/quant/legcal")
import leg_candidates as L
from export_dashboard import build_tf_stream
from pine_engine.engine import compile_pine, run_backtest
from pine_engine.data.loader import load_bars_csv
from pine_engine.reporting.stats import compute_stats

SC = "/tmp/claude-1000/-home-pouya/df461499-5170-4d6c-bc06-333ca04eea33/scratchpad"
BASE = SC + "/bot_lastyear.pine"
ANCHOR = "    _haveAnchors = startP != 0.0 and endP != 0.0"
PV = 20.0; R = 10
DATA = {"2021-22": SC + "/nq_2122.csv", "2025-26": "/home/pouya/pine-engine/quant/nq_lastyear.csv"}


def cris_leg(bars, tmin, oi, R):
    ot = tmin[oi]
    idxs = [i for i in range(len(tmin)) if i < oi and 0 <= ot - tmin[i] <= R]
    if len(idxs) < 3: return None
    hi = max(idxs, key=lambda i: bars[i][1]); lo = min(idxs, key=lambda i: bars[i][2])
    if hi == lo: return None
    return {"start": bars[hi][1], "pivot": bars[lo][2]} if hi <= lo else {"start": bars[lo][2], "pivot": bars[hi][1]}


def gen_legs(csv):
    ds, de = L.hhmm("06:00"), L.hhmm("23:00"); ls, le = L.hhmm("08:00"), L.hhmm("09:30")
    d1 = build_tf_stream(csv, [2, 3, 5], 8.0, 0.10, ds, de, ls, le, None)
    out = {}
    for d in sorted(d1):
        tf = d1[d]
        if tf["open_idx"] is None or tf["open_idx"] < 0 or len(tf["bars"]) < 200: continue
        cl = cris_leg(tf["bars"], tf["tmin"], tf["open_idx"], R)
        if cl and abs(cl["start"] - cl["pivot"]) >= 5:
            out[d.isoformat()] = cl
    return out


def override(lg):
    blk = ['    _ovKey = year(time,"America/New_York")*10000 + month(time,"America/New_York")*100 + dayofmonth(time,"America/New_York")']
    for d in sorted(lg):
        y, mo, dd = d.split("-"); key = int(y)*10000+int(mo)*100+int(dd)
        blk += [f"    if _ovKey == {key}", f'        startP := {lg[d]["start"]:.2f}', f'        endP   := {lg[d]["pivot"]:.2f}',
                "        startB := bar_index - 5", "        endB   := bar_index - 1"]
    return "\n".join(blk) + "\n"


def run(c, bars):
    tr = run_backtest(c, bars, {"slPoints": 13.5})
    recs = sorted([(t.exit_time, (t.exit_price-t.entry_price)*(1 if t.side=="long" else -1)*t.qty*PV) for t in tr], key=lambda r: r[0] or 0)
    eq=peak=mdd=0.0
    for _, p in recs: eq+=p; peak=max(peak,eq); mdd=max(mdd,peak-eq)
    s = compute_stats(tr, point_value=PV)
    return s["profit_factor"], s["net_pnl"], mdd, s["total_trades"], s["win_rate"]


src = open(BASE).read()
c_v25 = compile_pine(BASE)
res = {}
for period, csv in DATA.items():
    print(f"--- {period} ---", flush=True)
    bars = load_bars_csv(csv)
    legs = gen_legs(csv)
    inj = src.replace(ANCHOR, override(legs) + ANCHOR, 1)
    p2 = SC + f"/inj_rw_{period}.pine"; open(p2, "w").write(inj)
    res[(period, "v25")] = run(c_v25, bars)
    res[(period, "recent")] = run(compile_pine(p2), bars)
    print(f"  legs={len(legs)} done", flush=True)

print("\n=== OVERFIT-CHECK: gleiche Ergebnisse in/out-of-sample? ===")
print(f"{'':18s} {'2021-22 (in-sample R)':>24s}   {'2025-26 (OOS)':>20s}")
for bot, name in [("v25", "V25"), ("recent", "RECENT-WINDOW (Cris-Stil)")]:
    a = res[("2021-22", bot)]; b = res[("2025-26", bot)]
    print(f"{name:26s} PF {a[0]:.2f} Net${a[1]:+8.0f} DD${a[2]:.0f}    PF {b[0]:.2f} Net${b[1]:+8.0f} DD${b[2]:.0f}")
print("DONE", flush=True)
