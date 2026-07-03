#!/usr/bin/env python3
"""Generate direction-conditioned leg files to test the '72% winners are DOWN-legs' signal
(Pouya's manipulation thesis: the pre-open manip move has a direction). Each -> date->start/pivot
for injection into the REAL engine.
  python3 gen_dir_legs.py <days_dir>
Writes legs_downrec.json, legs_downbig.json, legs_uprec.json, legs_recanydir.json.
"""
import sys, json, os

days_dir = sys.argv[1]
meta = json.load(open(f"{days_dir}/days.json"))
downrec, downbig, uprec, recany = {}, {}, {}, {}
for d in sorted(meta):
    cands = meta[d]["cands"]; order = meta[d]["recency_order"]
    if not cands:
        continue
    downs = [i for i in order if cands[i]["dir"] == "down"]      # recency-ordered down cands
    ups = [i for i in order if cands[i]["dir"] == "up"]
    recany[d] = {"start": cands[order[0]]["start"], "pivot": cands[order[0]]["pivot"]}
    if downs:
        c = cands[downs[0]]; downrec[d] = {"start": c["start"], "pivot": c["pivot"]}
        cb = max((cands[i] for i in downs), key=lambda c: c["size"])
        downbig[d] = {"start": cb["start"], "pivot": cb["pivot"]}
    if ups:
        c = cands[ups[0]]; uprec[d] = {"start": c["start"], "pivot": c["pivot"]}

for name, obj in [("downrec", downrec), ("downbig", downbig), ("uprec", uprec), ("recanydir", recany)]:
    json.dump(obj, open(f"{days_dir}/legs_{name}.json", "w"))
    print(f"legs_{name}: {len(obj)} days")
