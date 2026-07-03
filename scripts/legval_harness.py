#!/usr/bin/env python3
"""Validate ONE detector against the frozen pre-registered gates. Prints one JSON object.
  python3 legval_harness.py <detector_name>
Gates (regime-robustness — the property v25 LACKS):
  - reproduce% of Cristiano's 203 real picks (imitation anchor, measured on 2021-22)
  - PF in EACH of 2021-22 / 2025-26 / 2016-17
  - min_pf = worst regime. robust_win = min_pf > v25 min_pf AND all PF>1.2 AND reproduce>=35%.
"""
import sys, json, pickle
sys.path.insert(0, "/home/pouya/pine-engine")
sys.path.insert(0, "/home/pouya/pine-engine/scripts")
from detectors import DETECTORS
from pine_engine.engine import compile_pine, run_backtest
from pine_engine.data.loader import load_bars_csv
from pine_engine.reporting.stats import compute_stats

SC = "/tmp/claude-1000/-home-pouya/df461499-5170-4d6c-bc06-333ca04eea33/scratchpad"
BASE = SC + "/bot_lastyear.pine"
ANCHOR = "    _haveAnchors = startP != 0.0 and endP != 0.0"
PV = 20.0
CSV = {"2021-22": SC + "/nq_2122.csv", "2025-26": "/home/pouya/pine-engine/quant/nq_lastyear.csv",
       "2016-17": "/home/pouya/pine-engine/quant/nq_1617.csv"}


def override(lg):
    blk = ['    _ovKey = year(time,"America/New_York")*10000 + month(time,"America/New_York")*100 + dayofmonth(time,"America/New_York")']
    for d in sorted(lg):
        y, mo, dd = d.split("-"); key = int(y) * 10000 + int(mo) * 100 + int(dd)
        blk += [f"    if _ovKey == {key}", f'        startP := {lg[d][0]:.2f}', f'        endP   := {lg[d][1]:.2f}',
                "        startB := bar_index - 5", "        endB   := bar_index - 1"]
    return "\n".join(blk) + "\n"


def main():
    name = sys.argv[1]
    det = DETECTORS[name]
    base = json.load(open(SC + "/baselines.json"))
    cris = json.load(open(SC + "/legs_cris_full.json"))
    src = open(BASE).read()
    out = {"detector": name, "pf": {}, "net": {}}

    # reproduction on 2021-22 cache (where Cristiano labelled)
    cache21 = pickle.load(open(SC + "/cache_2021-22.pkl", "rb"))
    hit = tot = 0
    for d, lg in cris.items():
        day = cache21.get(d)
        if not day: continue
        res = det(day["bars"], day["tmin"], day["open_idx"])
        if not res: continue
        tot += 1
        if abs(res[0] - lg["start"]) + abs(res[1] - lg["pivot"]) <= 8: hit += 1
    out["reproduce_pct"] = round(100 * hit / tot) if tot else 0

    # PF per period
    for period, csv in CSV.items():
        cache = pickle.load(open(SC + f"/cache_{period}.pkl", "rb"))
        legs = {}
        for d, day in cache.items():
            res = det(day["bars"], day["tmin"], day["open_idx"])
            if res: legs[d] = res
        inj = src.replace(ANCHOR, override(legs) + ANCHOR, 1)
        c = compile_pine_str(inj)
        bars = load_bars_csv(csv)
        tr = run_backtest(c, bars, {"slPoints": 13.5})
        s = compute_stats(tr, point_value=PV)
        out["pf"][period] = round(s["profit_factor"], 2)
        out["net"][period] = round(s["net_pnl"])

    pfs = [out["pf"][p] for p in CSV]
    out["min_pf"] = min(pfs)
    v25_min = min(base[p]["v25_pf"] for p in CSV)
    out["v25_min_pf"] = v25_min
    out["robust_win"] = (out["min_pf"] > v25_min and all(p > 1.2 for p in pfs) and out["reproduce_pct"] >= 35)
    print(json.dumps(out))


def compile_pine_str(src_str):
    import tempfile, os
    f = tempfile.NamedTemporaryFile("w", suffix=".pine", delete=False, dir=SC)
    f.write(src_str); f.close()
    c = compile_pine(f.name); os.unlink(f.name); return c


if __name__ == "__main__":
    main()
