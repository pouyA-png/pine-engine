#!/usr/bin/env python3
"""Fit a parameterised leg-SELECTOR to reproduce Pouya's labelled picks.

Input: the worksheet CSV (from leg_candidates.py) with the KORREKT(x) column
marked 'x' on the one correct candidate per day. The selector scores every
candidate from its features and picks argmax per day; we grid-search the
feature weights to MAXIMISE hit-rate (selector pick == labelled pick).

The fitted weights ARE Pouya's feel, made mechanical. Mismatch days are printed
— they expose the missing hidden rule.

Usage:
  python3 quant/legcal/fit_selection.py --worksheet labelled.csv
  python3 quant/legcal/fit_selection.py --worksheet ws.csv --self-test biggest
"""
import argparse, csv, itertools
from collections import defaultdict

FEATURES = ["size", "recency", "sweep", "wick", "clean", "impulse",
            "displacement", "dist_level", "round"]


def _norm_closer(val, day, col):
    """closer-to-zero = better -> 1.0; uses per-day min/max of column."""
    vals = [float(x[col]) for x in day if str(x.get(col, "")).strip() != ""]
    if not vals or str(val).strip() == "":
        return 0.0
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    return 1.0 - (float(val) - lo) / span


def load(path):
    days = defaultdict(list)
    with open(path) as f:
        for r in csv.DictReader(f):
            days[r["Datum"]].append(r)
    return days


def featvec(c, day):
    sizes = [float(x["Leg-Groesse(Pkt)"]) for x in day]
    mx = max(sizes) or 1.0
    mins = [float(x["Min-vor-9:30"]) for x in day]
    mn, mxm = min(mins), max(mins)
    span = (mxm - mn) or 1.0
    imp = {"niedrig": 0.0, "mittel": 0.5, "hoch": 1.0}
    dmax = max((float(x["Displacement"]) for x in day if str(x.get("Displacement", "")).strip() != ""), default=1.0) or 1.0
    return {
        "size": float(c["Leg-Groesse(Pkt)"]) / mx,
        "recency": 1.0 - (float(c["Min-vor-9:30"]) - mn) / span,  # closer to open = 1
        "sweep": 1.0 if c["Liquidity-Sweep"].strip().upper().startswith("J") else 0.0,
        "wick": 1.0 if c["Rejection-Wick"].strip().upper().startswith("J") else 0.0,
        "clean": (float(c["Pivot-Sauberkeit(1-5)"]) - 1) / 4.0,
        "impulse": imp.get(c["Impuls"].strip().lower(), 0.5),
        "displacement": float(c.get("Displacement", 0) or 0) / dmax,
        "dist_level": _norm_closer(c.get("Dist-Prev-Level", ""), day, "Dist-Prev-Level"),
        "round": _norm_closer(c.get("Round-Dist", ""), day, "Round-Dist"),
    }


def labelled_index(day):
    for i, c in enumerate(day):
        if c.get("KORREKT(x)", "").strip().lower() in ("x", "1", "j", "ja"):
            return i
    return None


def pick(day, w):
    best, bi = -1e9, 0
    for i, c in enumerate(day):
        fv = featvec(c, day)
        s = sum(w[k] * fv[k] for k in FEATURES)
        if s > best:
            best, bi = s, i
    return bi


def hit_rate(days, w):
    hit = tot = 0
    miss = []
    for d, day in days.items():
        li = labelled_index(day)
        if li is None:
            continue
        tot += 1
        if pick(day, w) == li:
            hit += 1
        else:
            miss.append(d)
    return (hit, tot, miss)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--worksheet", required=True)
    ap.add_argument("--self-test", default=None, choices=["biggest", "latest"])
    ap.add_argument("--grid", default="0,1,2")
    a = ap.parse_args()
    days = load(a.worksheet)

    if a.self_test:  # fabricate labels to prove the fit mechanics work
        for d, day in days.items():
            if not day:
                continue
            if a.self_test == "biggest":
                idx = max(range(len(day)), key=lambda i: float(day[i]["Leg-Groesse(Pkt)"]))
            else:
                idx = min(range(len(day)), key=lambda i: float(day[i]["Min-vor-9:30"]))
            for i, c in enumerate(day):
                c["KORREKT(x)"] = "x" if i == idx else ""

    n_lab = sum(1 for day in days.values() if labelled_index(day) is not None)
    print(f"days={len(days)} labelled_days={n_lab}")
    if n_lab == 0:
        print("No labels yet. Mark the correct candidate per day with 'x' in KORREKT(x), then re-run.")
        return

    grid = [float(x) for x in a.grid.split(",")]
    best = None
    # baseline single-rule references
    for name, w in [("pure-size", {k: (1 if k == "size" else 0) for k in FEATURES}),
                    ("pure-recency", {k: (1 if k == "recency" else 0) for k in FEATURES})]:
        h, t, _ = hit_rate(days, w)
        print(f"  ref {name:12s}: {h}/{t} = {100*h/t:.0f}%")

    # grid search over weights
    for combo in itertools.product(grid, repeat=len(FEATURES)):
        if sum(combo) == 0:
            continue
        w = dict(zip(FEATURES, combo))
        h, t, miss = hit_rate(days, w)
        if best is None or h > best[0]:
            best = (h, t, w, miss)
    h, t, w, miss = best
    print(f"\nBEST: {h}/{t} = {100*h/t:.1f}%")
    print("weights:", {k: v for k, v in w.items() if v})
    if miss:
        print(f"mismatch days ({len(miss)}) -> inspect for hidden rule:", ", ".join(miss[:20]))


if __name__ == "__main__":
    main()
