#!/usr/bin/env python3
"""Can a PRE-OPEN-observable feature rule reproduce Claude's visual leg-picks?
If yes -> the bot can mechanise the picks. If no -> vision edge is not buildable.

  python3 rule_fit.py <days_dir> <picks_json>

Reports hit-rate (reproduce vision pick) for several rules, in-sample AND walk-forward
(train earlier 60% of days -> test later 40%). Features normalised within-day (same as
the leglab dashboard featvec). Pure stdlib.
"""
import json, sys, itertools


FEAT = ["size", "recency", "sweep", "wick", "clean", "disp", "distlvl", "round"]


def featvec(cands):
    """normalise per day -> list of dicts (one per cand), 0..1, recency=1 means youngest."""
    sizes = [c["size"] for c in cands]; mx = max(sizes) or 1
    mins = [c["minopen"] for c in cands]; mn = min(mins); span = (max(mins) - mn) or 1
    dmax = max((c["disp"] for c in cands), default=1) or 1
    dl = [c["distlvl"] for c in cands if c.get("distlvl") is not None]
    dlo = min(dl) if dl else 0; dls = ((max(dl) - dlo) if dl else 1) or 1
    rd = [c["round"] for c in cands]; rlo = min(rd); rls = (max(rd) - rlo) or 1
    out = []
    for c in cands:
        out.append({
            "size": c["size"] / mx,
            "recency": 1 - (c["minopen"] - mn) / span,
            "sweep": 1.0 if c["sweep"] else 0.0,
            "wick": 1.0 if c["wick"] else 0.0,
            "clean": (c["clean"] - 1) / 4,
            "disp": c["disp"] / dmax,
            "distlvl": 0.0 if c.get("distlvl") is None else 1 - (c["distlvl"] - dlo) / dls,
            "round": 1 - (c["round"] - rlo) / rls,
        })
    return out


def pick_with(fvs, w):
    best, bi = -1e18, 0
    for i, f in enumerate(fvs):
        s = sum(w.get(k, 0) * f[k] for k in FEAT)
        if s > best:
            best, bi = s, i
    return bi


def load(days_dir, picks_json):
    meta = json.load(open(f"{days_dir}/days.json"))
    picks = {p["date"]: p for p in json.load(open(picks_json))}
    rows = []   # (date, cands, fvs, label_idx)
    for d in sorted(meta):
        cands = meta[d]["cands"]; order = meta[d]["recency_order"]
        if not cands or d not in picks:
            continue
        pr = picks[d]["pick_rank"]
        if not (0 <= pr < len(order)):
            continue
        label = order[pr]
        rows.append((d, cands, featvec(cands), label))
    return rows


def hit(rows, picker):
    if not rows:
        return 0.0, 0
    h = sum(1 for (_, c, fv, lab) in rows if picker(c, fv) == lab)
    return h / len(rows), len(rows)


def main():
    days_dir, picks_json = sys.argv[1], sys.argv[2]
    rows = load(days_dir, picks_json)
    n = len(rows)
    print(f"labelled days: {n}")

    # fixed rules
    rules = {
        "RECENCY (argmin minopen)": lambda c, fv: max(range(len(fv)), key=lambda i: fv[i]["recency"]),
        "BIGGEST (argmax size)":    lambda c, fv: max(range(len(c)), key=lambda i: c[i]["size"]),
        "CLEANEST (argmax clean, tie->recency)":
            lambda c, fv: max(range(len(fv)), key=lambda i: (fv[i]["clean"], fv[i]["recency"])),
        "CLEAN+SIZE (clean*0.6+size*0.4)":
            lambda c, fv: max(range(len(fv)), key=lambda i: 0.6 * fv[i]["clean"] + 0.4 * fv[i]["size"]),
        "CLEAN+SWEEP+SIZE":
            lambda c, fv: max(range(len(fv)), key=lambda i: 0.5 * fv[i]["clean"] + 0.3 * fv[i]["sweep"] + 0.2 * fv[i]["size"]),
    }
    print("\n=== FIXED RULES (in-sample hit-rate vs Claude's pick) ===")
    base = {}
    for name, fn in rules.items():
        hr, _ = hit(rows, fn)
        base[name] = hr
        print(f"  {name:42s} {100*hr:5.1f}%")

    # learned weights: small grid over a few salient features (size, recency, clean, sweep)
    print("\n=== LEARNED WEIGHTS (grid {0,1,2} over size/recency/clean/sweep) ===")
    keys = ["size", "recency", "clean", "sweep"]
    cut = int(n * 0.6)
    train, test = rows[:cut], rows[cut:]

    def best_weights(data):
        best_hr, best_w = -1, None
        for combo in itertools.product([0, 1, 2], repeat=len(keys)):
            if not any(combo):
                continue
            w = dict(zip(keys, combo))
            hr, _ = hit(data, lambda c, fv, w=w: pick_with(fv, w))
            if hr > best_hr:
                best_hr, best_w = hr, w
        return best_w, best_hr

    w_all, hr_all = best_weights(rows)
    print(f"  in-sample best: {w_all}  -> {100*hr_all:.1f}%")
    w_tr, hr_tr = best_weights(train)
    hr_te, _ = hit(test, lambda c, fv: pick_with(fv, w_tr))
    print(f"  walk-forward: train({len(train)}) {w_tr} = {100*hr_tr:.1f}%  ->  TEST({len(test)}) = {100*hr_te:.1f}%")
    decay = (hr_tr - hr_te)
    print(f"  decay train->test: {100*decay:+.1f}pp  ({'OVERFIT' if decay > 0.15 else 'stabil' if decay < 0.08 else 'leicht'})")

    rand = sum(1 / len(c) for (_, c, _, _) in rows) / n
    print(f"\n  Zufallsbasis (1/#cands): {100*rand:.1f}%  (Regeln darüber = echtes Signal)")
    print("\nFazit: reproduziert eine simple Regel Claudes Picks gut (>~50% & test stabil)")
    print("-> Bot mechanisierbar; sonst ist der Vision-Edge nicht in Features fassbar.")


if __name__ == "__main__":
    main()
