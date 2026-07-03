#!/usr/bin/env python3
"""Render a real day with the leglab auto-trade boxes (TV Long/Short tool look, $1k risk/level)
so Pouya can SEE the feature without a browser. Uses the exact v25 trade model (outcome_sim).
  python3 preview_trade.py <date YYYY-MM-DD> <out.png>
"""
import sys, json, os
from datetime import datetime, time
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from outcome_sim import levels_from_leg, orders_for

NY = ZoneInfo("America/New_York"); UTC = ZoneInfo("UTC")
RISK = 1000.0
DATA = "/home/pouya/pine-engine/quant/nq_lastyear.csv"
UP, DN = "#2F8F66", "#CB4B41"
date = sys.argv[1]; out = sys.argv[2]
meta = json.load(open("/tmp/claude-1000/-home-pouya/df461499-5170-4d6c-bc06-333ca04eea33/scratchpad/lastyear/days.json"))

# bars for that NY day 06:00-11:00
bars = []
with open(DATA) as f:
    f.readline()
    for line in f:
        c0 = line.find(",")
        ts = datetime.fromisoformat(line[:c0])
        if ts.tzinfo is None: ts = ts.replace(tzinfo=UTC)
        ny = ts.astimezone(NY)
        if ny.date().isoformat() != date: continue
        if time(6, 0) <= ny.time() <= time(11, 0):
            p = line.rstrip().split(",")
            bars.append((ny, float(p[1]), float(p[2]), float(p[3]), float(p[4])))
if not bars:
    print("no bars for", date); sys.exit(1)

# pick a leg: biggest down candidate (clean demo) else recency0
md = meta.get(date)
cands = md["cands"] if md else []
downs = [c for c in cands if c["dir"] == "down"]
leg = max(downs, key=lambda c: c["size"]) if downs else (max(cands, key=lambda c: c["size"]) if cands else None)
if not leg:
    print("no leg"); sys.exit(1)
startP, pivot = leg["start"], leg["pivot"]

dow = datetime.fromisoformat(date).weekday()
orders, SL = orders_for(startP, pivot, dow)
Lv = levels_from_leg(startP, pivot)
for nm, side, ent, tps in []:
    pass
# enrich orders with profit/RR
O = []
for nm, side, ent, tps in orders:
    rrA = abs(tps[0] - ent) / SL; rrB = abs(tps[-1] - ent) / SL
    O.append(dict(nm=nm, side=side, ent=ent, sl=ent - (1 if side == "long" else -1) * SL,
                  tps=tps, rrA=rrA, rrB=rrB, rr=(rrA + rrB) / 2, profit=(rrA + rrB) * RISK / 2))

open_idx = next((i for i, b in enumerate(bars) if b[0].time() >= time(9, 30)), len(bars) - 1)
n = len(bars)
fig, ax = plt.subplots(figsize=(15, 8), dpi=95)
for i, (t, o, h, l, c) in enumerate(bars):
    col = UP if c >= o else DN
    ax.plot([i, i], [l, h], color=col, lw=0.7, zorder=1)
    ax.add_patch(plt.Rectangle((i - 0.3, min(o, c)), 0.6, max(abs(c - o), 0.1), color=col, zorder=2))
# leg line
i0 = max(0, open_idx - 60); i1 = open_idx
ax.plot([i0, i1], [startP, pivot], color="#B8860B", lw=2.4, zorder=4)
ax.scatter([i0, i1], [startP, pivot], color="#B8860B", s=45, zorder=5)
# 7 levels faint
for nm, p in Lv.items():
    ax.axhline(p, color="#3B6FB0", lw=0.7, ls=":", alpha=0.35, zorder=1)
    ax.annotate(nm, (n - 1, p), color="#3B6FB0", fontsize=7, va="center", alpha=0.6)
ax.axvline(open_idx - 0.5, color="#666", ls="--", lw=1)
ax.annotate("09:30 Open", (open_idx - 0.5, max(b[2] for b in bars)), fontsize=9, color="#666", ha="right")

# TV trade boxes in lanes on the right
xs, xe = open_idx + 1, n + 28
N = len(O); laneW = (xe - xs) / max(1, N)
for k, od in enumerate(O):
    lx0 = xs + k * laneW + 1; lx1 = xs + (k + 1) * laneW - 1
    isLong = od["side"] == "long"
    ent, sl, tp2, tp1 = od["ent"], od["sl"], od["tps"][-1], od["tps"][0]
    # risk box (entry->SL) red
    ax.add_patch(plt.Rectangle((lx0, min(ent, sl)), lx1 - lx0, abs(sl - ent),
                               facecolor=DN, alpha=0.18, edgecolor=DN, lw=1.2, zorder=3))
    # reward box (entry->TP2) green
    ax.add_patch(plt.Rectangle((lx0, min(ent, tp2)), lx1 - lx0, abs(tp2 - ent),
                               facecolor=UP, alpha=0.18, edgecolor=UP, lw=1.2, zorder=3))
    ax.plot([lx0, lx1], [tp1, tp1], color=UP, lw=1, ls=(0, (4, 3)), zorder=4)   # TP1 dashed
    ax.plot([lx0, lx1], [ent, ent], color="#1f6e4f" if isLong else "#a8392f", lw=1.8, zorder=4)
    cxm = (lx0 + lx1) / 2
    ax.annotate(f"+${od['profit']:,.0f}", (cxm, (min(ent, tp2) + max(ent, tp2)) / 2),
                color="#1c7a54", fontsize=11, fontweight="bold", ha="center", va="center", zorder=6)
    ax.annotate(f"-${RISK:,.0f}", (cxm, (min(ent, sl) + max(ent, sl)) / 2),
                color="#b23a30", fontsize=9, fontweight="bold", ha="center", va="center", zorder=6)
    ax.annotate(f"{od['nm']} {'LONG' if isLong else 'SHORT'}", (cxm, max(ent, sl, tp2) + 3),
                color=UP if isLong else DN, fontsize=9, fontweight="bold", ha="center", zorder=6)
    ax.annotate(f"R:R 1:{od['rr']:.1f}", (cxm, min(ent, sl, tp2) - 3),
                color="#52525B", fontsize=8, ha="center", zorder=6)

ax.set_xlim(-1, xe + 2)
allp = [b[2] for b in bars] + [b[3] for b in bars] + [o["sl"] for o in O] + [o["tps"][-1] for o in O]
ax.set_ylim(min(allp) - 5, max(allp) + 8)
ax.set_title(f"leglab Auto-Trade Preview — {date}  ·  $1.000 Risk/Level  ·  TV Long/Short R:R-Tool", fontsize=12)
ax.set_xlabel("Bar (06:00–11:00 NY)"); ax.set_ylabel("Preis")
ax.grid(True, alpha=0.12)
fig.tight_layout(); fig.savefig(out, facecolor="white"); plt.close(fig)
print("saved", out, "| leg", f"{startP:.0f}->{pivot:.0f}", "| orders", len(O))
