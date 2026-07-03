#!/usr/bin/env python3
"""Phase 2-4: fit an imitation selector to Cristiano's matched picks, apply to 2025-26,
run through the real engine, compare to v25. Plus diagnose his drawn legs vs detector.
"""
import sys, json, itertools
sys.path.insert(0, "/home/pouya/pine-engine")
from zoneinfo import ZoneInfo

SC = "/tmp/claude-1000/-home-pouya/df461499-5170-4d6c-bc06-333ca04eea33/scratchpad"
BASE = SC + "/bot_lastyear.pine"
DATA25 = "/home/pouya/pine-engine/quant/nq_lastyear.csv"   # 2025-03-13 .. 2026-03-13
ANCHOR = "    _haveAnchors = startP != 0.0 and endP != 0.0"
NY = ZoneInfo("America/New_York"); PV = 20.0
FEAT = ["size", "recency", "sweep", "clean", "disp", "wick"]


def featvec(cands):
    sizes = [c["size"] for c in cands]; mx = max(sizes) or 1
    mins = [c["minopen"] for c in cands]; mn = min(mins); span = (max(mins) - mn) or 1
    dmax = max((c["disp"] for c in cands), default=1) or 1
    out = []
    for c in cands:
        out.append({"size": c["size"] / mx, "recency": 1 - (c["minopen"] - mn) / span,
                    "sweep": 1.0 if c["sweep"] else 0.0, "clean": (c["clean"] - 1) / 4,
                    "disp": c["disp"] / dmax, "wick": 1.0 if c["wick"] else 0.0})
    return out


def pick(cands, w):
    fv = featvec(cands); best, bi = -1e18, 0
    for i, f in enumerate(fv):
        s = sum(w.get(k, 0) * f[k] for k in FEAT)
        if s > best: best, bi = s, i
    return bi


# ---- (A) diagnose his drawn legs vs detector candidates ----
train = json.load(open(SC + "/train_cris.json"))
import statistics as st
his_sz, cand_sz, his_rec = [], [], []
for t in train:
    his_sz.append(abs(t["drawn"]["start"] - t["drawn"]["pivot"]))
    for c in t["cands"]:
        cand_sz.append(c["size"])
print("=== DIAGNOSE: Cristianos gezeichnete Legs vs Detektor-Kandidaten ===")
print(f"  seine Leg-Größe: median {st.median(his_sz):.0f}pt  (Kandidaten median {st.median(cand_sz):.0f}pt)")
print(f"  Detector-Miss: {sum(1 for t in train if t['picked'] is None)}/{len(train)} "
      f"= {100*sum(1 for t in train if t['picked'] is None)//len(train)}% — seine Legs sind oft NICHT im Kandidaten-Set")

# ---- (B) fit imitation selector on matched picks ----
matched = [t for t in train if t["picked"] is not None]
best = None
for combo in itertools.product([0, 1, 2], repeat=len(FEAT)):
    if not any(combo): continue
    w = dict(zip(FEAT, combo))
    hit = sum(1 for t in matched if pick(t["cands"], w) == t["picked"])
    if best is None or hit > best[0]: best = (hit, w)
hit, W = best
print(f"\n=== IMITATION-SELEKTOR (fit auf {len(matched)} Matches) ===")
print(f"  beste Gewichte: {W}  -> reproduziert {hit}/{len(matched)} = {100*hit//len(matched)}% seiner Picks")

# ---- (C) apply to 2025-26, build leg-override file ----
meta = json.load(open(SC + "/lastyear/days.json"))
legs = {}
for d in sorted(meta):
    cands = meta[d]["cands"]
    if not cands: continue
    c = cands[pick(cands, W)]
    legs[d] = {"start": c["start"], "pivot": c["pivot"]}
print(f"  angewandt auf {len(legs)} Tage 2025-26 -> Leg-Picks", flush=True)

# ---- (D) inject + run engine, compare to v25 ----
from pine_engine.engine import compile_pine, run_backtest
from pine_engine.data.loader import load_bars_csv
from pine_engine.reporting.stats import compute_stats

def override(legs):
    blk = ['    _ovKey = year(time,"America/New_York")*10000 + month(time,"America/New_York")*100 + dayofmonth(time,"America/New_York")']
    for d in sorted(legs):
        y, m, dd = d.split("-"); key = int(y)*10000+int(m)*100+int(dd)
        blk += [f"    if _ovKey == {key}", f'        startP := {legs[d]["start"]:.2f}',
                f'        endP   := {legs[d]["pivot"]:.2f}', "        startB := bar_index - 5", "        endB   := bar_index - 1"]
    return "\n".join(blk) + "\n"

def stats(c, bars, lbl):
    tr = run_backtest(c, bars, {"slPoints": 13.5})
    recs = sorted([(t.exit_time, (t.exit_price-t.entry_price)*(1 if t.side=="long" else -1)*t.qty*PV) for t in tr], key=lambda r: r[0] or 0)
    eq=peak=mdd=0.0
    for _, p in recs: eq+=p; peak=max(peak,eq); mdd=max(mdd,peak-eq)
    s = compute_stats(tr, point_value=PV)
    print(f"  {lbl:16s} PF={s['profit_factor']:.2f} Net=${s['net_pnl']:+.0f} WR={s['win_rate']*100:.0f}% DD=${mdd:.0f} Tr={s['total_trades']}")

print("\n=== ENGINE 2025-03-13 .. 2026-03-13 (nq_lastyear) ===", flush=True)
bars = load_bars_csv(DATA25)
src = open(BASE).read()
stats(compile_pine(BASE), bars, "V25 (Baseline)")
inj = src.replace(ANCHOR, override(legs) + ANCHOR, 1)
p2 = SC + "/inj_imitation.pine"; open(p2, "w").write(inj)
stats(compile_pine(p2), bars, "IMITATION-BOT")
print("DONE", flush=True)
