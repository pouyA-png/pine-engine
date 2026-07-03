#!/usr/bin/env python3
"""Using the real-engine per-(day,rank) PnL matrix: (A) characterise the winning leg,
(B) fit small PRE-OPEN feature rules on H1 and test on H2 (real PnL, walk-forward).
A pick-rule's real-engine PnL = sum over days of matrix[date][picked_rank] (0 if it didn't trade).
"""
import json, itertools

LY = "/tmp/claude-1000/-home-pouya/df461499-5170-4d6c-bc06-333ca04eea33/scratchpad/lastyear"
SPLIT = "2025-09-13"
V25 = {"YEAR": 99787, "H1": 28470, "H2": 70237}

meta = json.load(open(f"{LY}/days.json"))
RP = json.load(open(f"{LY}/rank_pnl.json"))
matrix = RP["matrix"]                      # date -> {rank(str): pnl}
dates = sorted(meta)

FEAT = ["size", "recency", "sweep", "disp", "clean", "wick"]


def featvec(cands):
    sizes = [c["size"] for c in cands]; mx = max(sizes) or 1
    mins = [c["minopen"] for c in cands]; mn = min(mins); span = (max(mins) - mn) or 1
    dmax = max((c["disp"] for c in cands), default=1) or 1
    out = []
    for c in cands:
        out.append({"size": c["size"] / mx, "recency": 1 - (c["minopen"] - mn) / span,
                    "sweep": 1.0 if c["sweep"] else 0.0, "disp": c["disp"] / dmax,
                    "clean": (c["clean"] - 1) / 4, "wick": 1.0 if c["wick"] else 0.0})
    return out


def pnl_of(date, rank):
    return matrix.get(date, {}).get(str(rank), 0.0)


def pick_rank(cands, fvs, w):
    best, bi = -1e18, 0
    for i, f in enumerate(fvs):
        s = sum(w.get(k, 0) * f[k] for k in FEAT)
        if s > best:
            best, bi = s, i
    return bi


def rule_pnl(days, w):
    tot = 0.0
    for d in days:
        cands = meta[d]["cands"]; order = meta[d]["recency_order"]
        if not cands:
            continue
        fvs = featvec(cands)
        i = pick_rank(cands, fvs, w)      # index into cands (=recency rank order position? no: i is cand index)
        rank = order.index(i) if i in order else 0   # map cand-index -> recency rank used in matrix
        tot += pnl_of(d, rank)
    return tot


# ---- (A) characterise winners ----
print("=== (A) GEWINNER-LEG CHARAKTERISIERUNG (real-engine best rank/day) ===")
win_feats = {"size": [], "minopen": [], "sweep": [], "disp": [], "clean": [], "dir_up": [], "rank": []}
field_feats = {k: [] for k in win_feats}
for d in dates:
    if d not in matrix or not matrix[d]:
        continue
    cands = meta[d]["cands"]; order = meta[d]["recency_order"]
    ranks = {int(r): v for r, v in matrix[d].items()}
    if not ranks:
        continue
    bestrank = max(ranks, key=lambda r: ranks[r])
    if bestrank >= len(order):
        continue
    wc = cands[order[bestrank]]
    win_feats["size"].append(wc["size"]); win_feats["minopen"].append(wc["minopen"])
    win_feats["sweep"].append(1 if wc["sweep"] else 0); win_feats["disp"].append(wc["disp"])
    win_feats["clean"].append(wc["clean"]); win_feats["dir_up"].append(1 if wc["dir"] == "up" else 0)
    win_feats["rank"].append(bestrank)
    for i, c in enumerate(cands):     # field = all candidates
        field_feats["size"].append(c["size"]); field_feats["minopen"].append(c["minopen"])
        field_feats["sweep"].append(1 if c["sweep"] else 0); field_feats["disp"].append(c["disp"])
        field_feats["clean"].append(c["clean"]); field_feats["dir_up"].append(1 if c["dir"] == "up" else 0)
        field_feats["rank"].append(0)


def avg(a): return sum(a) / len(a) if a else 0
print(f"  {'feature':10s} {'WINNER avg':>12s} {'FIELD avg':>12s}")
for k in ("size", "minopen", "sweep", "disp", "clean", "dir_up", "rank"):
    fld = avg(field_feats[k]) if k != "rank" else float("nan")
    print(f"  {k:10s} {avg(win_feats[k]):12.2f} {fld:12.2f}")
print(f"  (n winners={len(win_feats['size'])})")

# ---- (B) walk-forward rule fit on real PnL ----
print("\n=== (B) PRE-OPEN-REGEL fit auf H1 -> test H2 (echte PnL) ===")
print(f"  v25 baseline: H1 +{V25['H1']}  H2 +{V25['H2']}  YEAR +{V25['YEAR']}")
train = [d for d in dates if d <= SPLIT]
test = [d for d in dates if d > SPLIT]
keys = ["size", "recency", "sweep", "disp", "clean"]
best = None
for combo in itertools.product([0, 1, 2], repeat=len(keys)):
    if not any(combo):
        continue
    w = dict(zip(keys, combo))
    tr = rule_pnl(train, w)
    if best is None or tr > best[0]:
        best = (tr, w)
trp, w = best
tep = rule_pnl(test, w)
yr = rule_pnl(dates, w)
print(f"  best-on-H1 weights: {w}")
print(f"  H1(train)={trp:+.0f}  H2(TEST)={tep:+.0f}  YEAR={yr:+.0f}")
print(f"  vs v25:  H1 {'WIN' if trp>V25['H1'] else 'lose'}  H2 {'WIN' if tep>V25['H2'] else 'lose'}  YEAR {'WIN' if yr>V25['YEAR'] else 'lose'}")
# also report fixed simple rules
print("\n  Fixe Regeln (ganzes Jahr, echte PnL):")
for nm, w in [("recency", {"recency": 1}), ("biggest", {"size": 1}),
              ("sweep+disp", {"sweep": 2, "disp": 1}), ("clean+size", {"clean": 1, "size": 1})]:
    print(f"    {nm:12s} YEAR={rule_pnl(dates, w):+.0f}")
