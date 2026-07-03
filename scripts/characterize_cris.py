#!/usr/bin/env python3
"""Characterize HOW Cristiano anchors his legs vs the detector window (08:00-09:30 NY).
Uses his stored bar-indices (i0,i1) + the dashboard tmin per day -> minutes-before-open of his
start & pivot. Tells us exactly what the detector must change to produce his legs.
"""
import json
SC = "/tmp/claude-1000/-home-pouya/df461499-5170-4d6c-bc06-333ca04eea33/scratchpad"
s = open(SC + "/live_app.html", encoding="utf-8").read()
a = s.index("const DATASETS=") + len("const DATASETS="); m = s.index("let curDS", a)
cme = {d["date"]: d for d in json.loads(s[a:m].rstrip()[:-1].strip())["cme"]["days"]}
legs = json.load(open(SC + "/legs_cris_full.json"))

import statistics as st
start_mbo, pivot_mbo, sizes, dirs = [], [], [], []
before_win = after_open = in_win = 0
win_frac = []   # his leg size / window range
for date, lg in legs.items():
    day = cme.get(date);
    if not day: continue
    tf = day["tf"].get(lg["tf"]);
    if not tf: continue
    tmin, oi, bars = tf["tmin"], tf["open_idx"], tf["bars"]
    if oi is None or oi < 0 or lg["i0"] >= len(tmin) or lg["i1"] >= len(tmin): continue
    ot = tmin[oi]
    s0 = ot - tmin[lg["i0"]]   # minutes before open of his START
    s1 = ot - tmin[lg["i1"]]   # minutes before open of his PIVOT
    start_mbo.append(s0); pivot_mbo.append(s1)
    sizes.append(abs(lg["start"] - lg["pivot"])); dirs.append(lg["dir"])
    # detector window = 08:00-09:30 NY = 90..0 min before open
    if s0 > 90: before_win += 1
    elif s0 < 0: after_open += 1
    else: in_win += 1
    # window range (08:00-09:30)
    wb = [bars[i] for i in range(len(tmin)) if 0 <= ot - tmin[i] <= 90]
    if wb:
        wr = max(b[1] for b in wb) - min(b[2] for b in wb)
        if wr > 0: win_frac.append(abs(lg["start"] - lg["pivot"]) / wr)

n = len(start_mbo)
print(f"=== Cristianos {n} Legs — Anker-Charakterisierung ===")
def dist(name, a):
    a = sorted(a)
    print(f"  {name:22s} median {st.median(a):5.0f} | p10 {a[len(a)//10]:4.0f} | p90 {a[9*len(a)//10]:4.0f} | min {a[0]:.0f} max {a[-1]:.0f}")
dist("START min vor Open", start_mbo)
dist("PIVOT min vor Open", pivot_mbo)
dist("Leg-Größe (pt)", sizes)
print(f"\n  START-Position vs Detektor-Fenster (08:00-09:30 = 0..90 min vor Open):")
print(f"    VOR dem Fenster (>90min): {before_win}/{n} = {100*before_win//n}%  <- Detektor sieht das NICHT")
print(f"    im Fenster:               {in_win}/{n} = {100*in_win//n}%")
print(f"    nach Open (<0):           {after_open}/{n} = {100*after_open//n}%")
import collections
print(f"\n  Richtung: {dict(collections.Counter(dirs))}")
if win_frac:
    print(f"  Leg-Größe / Fenster-Range: median {st.median(win_frac):.2f} (1.0 = volles Fenster; <1 = Sub-Move)")
# how many pivots land near open (recency)?
near = sum(1 for x in pivot_mbo if x <= 10)
print(f"  Pivot ≤10min vor Open (frisch): {near}/{n} = {100*near//n}%")
