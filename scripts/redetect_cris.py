#!/usr/bin/env python3
"""Detector redesign for Cristiano's style: leg = high<->low (chronological, pivot near open)
within the LAST R minutes before open (a recent sub-move, not the full 90min window).
(1) optimize R to reproduce his 203 legs, (2) apply best R to 2025-26, (3) engine vs v25.
"""
import sys, json
sys.path.insert(0, "/home/pouya/pine-engine")
sys.path.insert(0, "/home/pouya/pine-engine/quant/legcal")
from zoneinfo import ZoneInfo
import leg_candidates as L
from export_dashboard import build_tf_stream

SC = "/tmp/claude-1000/-home-pouya/df461499-5170-4d6c-bc06-333ca04eea33/scratchpad"
BASE = SC + "/bot_lastyear.pine"
DATA25 = "/home/pouya/pine-engine/quant/nq_lastyear.csv"
ANCHOR = "    _haveAnchors = startP != 0.0 and endP != 0.0"
NY = ZoneInfo("America/New_York"); PV = 20.0


def cris_leg(bars, tmin, oi, R):
    ot = tmin[oi]
    idxs = [i for i in range(len(tmin)) if i < oi and 0 <= ot - tmin[i] <= R]
    if len(idxs) < 3: return None
    hi = max(idxs, key=lambda i: bars[i][1]); lo = min(idxs, key=lambda i: bars[i][2])
    if hi == lo: return None
    if hi <= lo:   # high earlier -> pivot = more-recent low (down leg)
        return {"start": bars[hi][1], "pivot": bars[lo][2]}
    return {"start": bars[lo][2], "pivot": bars[hi][1]}   # up leg


# (1) optimize R on his 203 days using dashboard bars
s = open(SC + "/live_app.html", encoding="utf-8").read()
a = s.index("const DATASETS=") + len("const DATASETS="); m = s.index("let curDS", a)
cme = {d["date"]: d for d in json.loads(s[a:m].rstrip()[:-1].strip())["cme"]["days"]}
legs = json.load(open(SC + "/legs_cris_full.json"))
print("=== (1) R optimieren: reproduziert recent-window-Leg Cristianos Picks? ===")
best = None
for R in [8, 10, 12, 15, 18, 20, 25, 30]:
    hit = 0; tot = 0
    for date, lg in legs.items():
        day = cme.get(date)
        if not day: continue
        tf = day["tf"].get(lg["tf"])
        if not tf or tf["open_idx"] is None or tf["open_idx"] < 0: continue
        cl = cris_leg(tf["bars"], tf["tmin"], tf["open_idx"], R)
        if not cl: continue
        tot += 1
        if abs(cl["start"] - lg["start"]) + abs(cl["pivot"] - lg["pivot"]) <= 8: hit += 1
    pct = 100 * hit // tot if tot else 0
    print(f"  R={R:2d}min: reproduziert {hit}/{tot} = {pct}%")
    if best is None or hit / max(1, tot) > best[1]: best = (R, hit / max(1, tot))
R = best[0]
print(f"  -> bestes R = {R} min")

# (2) apply to 2025-26 (stream nq_lastyear)
print("\n=== (2) recent-window-Leg auf 2025-26 anwenden ===", flush=True)
ds, de = L.hhmm("06:00"), L.hhmm("23:00"); ls, le = L.hhmm("08:00"), L.hhmm("09:30")
d1 = build_tf_stream(DATA25, [2, 3, 5], 8.0, 0.10, ds, de, ls, le, None)
legs25 = {}
for d in sorted(d1):
    tf = d1[d]
    if tf["open_idx"] is None or tf["open_idx"] < 0 or len(tf["bars"]) < 200: continue
    cl = cris_leg(tf["bars"], tf["tmin"], tf["open_idx"], R)
    if cl and abs(cl["start"] - cl["pivot"]) >= 5:
        legs25[d.isoformat()] = cl
print(f"  Legs für {len(legs25)} Tage", flush=True)

# (3) inject + engine vs v25
from pine_engine.engine import compile_pine, run_backtest
from pine_engine.data.loader import load_bars_csv
from pine_engine.reporting.stats import compute_stats

def override(lg):
    blk = ['    _ovKey = year(time,"America/New_York")*10000 + month(time,"America/New_York")*100 + dayofmonth(time,"America/New_York")']
    for d in sorted(lg):
        y, mo, dd = d.split("-"); key = int(y)*10000+int(mo)*100+int(dd)
        blk += [f"    if _ovKey == {key}", f'        startP := {lg[d]["start"]:.2f}', f'        endP   := {lg[d]["pivot"]:.2f}',
                "        startB := bar_index - 5", "        endB   := bar_index - 1"]
    return "\n".join(blk) + "\n"

def stats(c, bars, lbl):
    tr = run_backtest(c, bars, {"slPoints": 13.5})
    recs = sorted([(t.exit_time, (t.exit_price-t.entry_price)*(1 if t.side=="long" else -1)*t.qty*PV) for t in tr], key=lambda r: r[0] or 0)
    eq=peak=mdd=0.0
    for _, p in recs: eq+=p; peak=max(peak,eq); mdd=max(mdd,peak-eq)
    st = compute_stats(tr, point_value=PV)
    print(f"  {lbl:20s} PF={st['profit_factor']:.2f} Net=${st['net_pnl']:+.0f} WR={st['win_rate']*100:.0f}% DD=${mdd:.0f} Tr={st['total_trades']}")

print("\n=== (3) ENGINE 2025-03..2026-03 vs v25 ===", flush=True)
bars = load_bars_csv(DATA25)
stats(compile_pine(BASE), bars, "V25 (Baseline)")
inj = open(BASE).read().replace(ANCHOR, override(legs25) + ANCHOR, 1)
p2 = SC + "/inj_recent.pine"; open(p2, "w").write(inj)
stats(compile_pine(p2), bars, "RECENT-WINDOW-BOT")
print("DONE", flush=True)
