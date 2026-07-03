#!/usr/bin/env python3
"""Phase 1: build imitation-training data from Cristiano's real picks.
For each of his drawn-leg days, match his (start,pivot) to the nearest detector candidate
(the menu he chose from), and record all candidate features + which index he picked.
Source of candidates = the deployed dashboard data (same candidates he labelled against).
"""
import json, sys

SC = "/tmp/claude-1000/-home-pouya/df461499-5170-4d6c-bc06-333ca04eea33/scratchpad"
LIVE = SC + "/live_app.html"
LEGS = SC + "/legs_cristiano.json"

print("extracting cme days from dashboard ...", flush=True)
s = open(LIVE, encoding="utf-8").read()
a = s.index("const DATASETS=") + len("const DATASETS=")
m = s.index("let curDS", a)
DATASETS = json.loads(s[a:m].rstrip()[:-1].strip())
cme = {d["date"]: d for d in DATASETS["cme"]["days"]}
print(f"cme days in dashboard: {len(cme)}", flush=True)

legs = json.load(open(LEGS))
train = []
miss = 0
for date, lg in legs.items():
    day = cme.get(date)
    if not day:
        continue
    # his legs are drawn on a tf; try 1m then 5m, match nearest candidate
    best = None
    for tf in ("1m", "5m"):
        cands = day["tf"][tf]["cands"]
        for i, c in enumerate(cands):
            d = abs(c["start"] - lg["start"]) + abs(c["pivot"] - lg["pivot"])
            if best is None or d < best[0]:
                best = (d, tf, i, cands)
    if best is None:
        miss += 1; continue
    dist, tf, idx, cands = best
    # tolerance: within ~6 pts total -> counts as "this candidate"
    if dist > 6.0:
        miss += 1
        train.append({"date": date, "tf": tf, "cands": cands, "picked": None,
                      "drawn": {"start": lg["start"], "pivot": lg["pivot"], "dir": lg["dir"]}, "dist": round(dist, 1)})
        continue
    train.append({"date": date, "tf": tf, "cands": cands, "picked": idx,
                  "drawn": {"start": lg["start"], "pivot": lg["pivot"], "dir": lg["dir"]}, "dist": round(dist, 1)})

matched = [t for t in train if t["picked"] is not None]
json.dump(train, open(SC + "/train_cris.json", "w"))
print(f"train rows: {len(train)}  matched-to-candidate: {len(matched)}  detector-miss: {len(train)-len(matched)}")
# quick: where in recency order did he pick?
import collections
rk = collections.Counter()
for t in matched:
    order = sorted(range(len(t["cands"])), key=lambda i: t["cands"][i]["minopen"])
    rk[order.index(t["picked"])] += 1
print("recency-rank of his pick:", dict(sorted(rk.items())[:10]))
print("  picked #0 (youngest):", rk[0], "/", len(matched))
