#!/usr/bin/env python3
"""Lightweight: regenerate per-day candidate metadata (days.json) WITHOUT rendering PNGs.
Same detection as the dashboard. For leg-selection experiments after a scratchpad wipe.
  python3 export_cands.py <data.csv> <out_dir>
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import leg_candidates as L
from export_dashboard import build_tf_stream

data, outdir = sys.argv[1], sys.argv[2]
os.makedirs(outdir, exist_ok=True)
ds, de = L.hhmm("06:00"), L.hhmm("23:00")
ls, le = L.hhmm("08:00"), L.hhmm("09:30")
print("streaming candidates ...", flush=True)
d1 = build_tf_stream(data, [2, 3, 5], 8.0, 0.10, ds, de, ls, le, None)
days = sorted(d for d in d1 if len(d1[d]["bars"]) >= 200 and d1[d]["open_idx"] >= 0)
meta = {}
for d in days:
    cands = d1[d]["cands"]
    order = sorted(range(len(cands)), key=lambda k: cands[k]["minopen"])
    meta[d.isoformat()] = {"open_idx": d1[d]["open_idx"], "cands": cands, "recency_order": order}
json.dump(meta, open(os.path.join(outdir, "days.json"), "w"))
print(f"DONE {len(meta)} days -> {outdir}/days.json", flush=True)
