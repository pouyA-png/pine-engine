#!/usr/bin/env python3
"""Run a SLICE of the leg-detection grid (for workflow fan-out). Prints one JSON line per config.
Usage: python3 sweep_legdetect_batch.py <start_idx> <count>
"""
import sys, json, itertools
sys.path.insert(0, "/home/pouya/pine-engine")
sys.path.insert(0, "/home/pouya/pine-engine/scripts")
from sweep_legdetect import GRID, run_one

keys = list(GRID)
grid = [dict(zip(keys, vals)) for vals in itertools.product(*GRID.values())]
start = int(sys.argv[1]); count = int(sys.argv[2])
for g in grid[start:start + count]:
    try:
        rec = run_one(g)
    except Exception as e:
        rec = {"error": str(e)[:140], "params": g, "beats_both": False}
    print(json.dumps(rec), flush=True)
