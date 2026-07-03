#!/usr/bin/env python3
"""Score leg-picking strategies by the v25 trade outcome (R) per day.
Compares: VISION (Claude's visual picks), RECENCY (#0 youngest pivot), BIGGEST (max size).

  python3 eval_picks.py <cal_dir> <data_csv> <picks_json>

picks_json: [{"date","pick_rank",...}, ...] from the vision workflow.
Prints per-strategy win-rate / avg-R / total-R + per-day table.
"""
import json, sys
from datetime import date as Date
from outcome_sim import simulate_day, stream_rth_by_day


def cand_R(c, d_iso, rth):
    dow = Date.fromisoformat(d_iso).weekday()
    return simulate_day(c["start"], c["pivot"], dow, rth)["total_R"]


def main():
    cal_dir, data_csv, picks_json = sys.argv[1], sys.argv[2], sys.argv[3]
    meta = json.load(open(f"{cal_dir}/days.json"))
    picks = {p["date"]: p for p in json.load(open(picks_json))}
    dates = sorted(meta)
    print(f"streaming RTH bars from {dates[0]} ...", flush=True)
    rth = stream_rth_by_day(data_csv, start_date=dates[0])

    strat = {"VISION": [], "RECENCY": [], "BIGGEST": []}
    rows = []
    for d in dates:
        cands = meta[d]["cands"]
        order = meta[d]["recency_order"]
        bars = rth.get(Date.fromisoformat(d), [])
        if not cands or not bars:
            continue
        # recency #0
        rec_c = cands[order[0]]
        # biggest
        big_c = max(cands, key=lambda c: c["size"])
        # vision
        vp = picks.get(d)
        vis_c = None
        if vp is not None and 0 <= vp["pick_rank"] < len(order):
            vis_c = cands[order[vp["pick_rank"]]]
        R_rec = cand_R(rec_c, d, bars)
        R_big = cand_R(big_c, d, bars)
        R_vis = cand_R(vis_c, d, bars) if vis_c else None
        strat["RECENCY"].append(R_rec)
        strat["BIGGEST"].append(R_big)
        if R_vis is not None:
            strat["VISION"].append(R_vis)
        rows.append((d, vp["pick_rank"] if vp else "-", R_vis, R_rec, R_big,
                     vp["gate"] if vp else "-", vp["conf"] if vp else "-"))

    def summ(name, rs):
        if not rs:
            return f"{name:8s}  n=0"
        wins = sum(1 for r in rs if r > 0)
        return (f"{name:8s}  n={len(rs):2d}  WinRate={100*wins/len(rs):4.0f}%  "
                f"avgR={sum(rs)/len(rs):+5.2f}  totalR={sum(rs):+6.1f}  "
                f"best={max(rs):+.1f} worst={min(rs):+.1f}")

    print("\n=== PER-DAY (R) ===")
    print(f"{'date':11s} {'vis#':4s} {'R_vis':>7s} {'R_rec':>7s} {'R_big':>7s}  gate conf")
    for d, pr, rv, rr, rb, g, cf in rows:
        sv = f"{rv:+.2f}" if rv is not None else "  -  "
        print(f"{d:11s} {str(pr):4s} {sv:>7s} {rr:+7.2f} {rb:+7.2f}  {g:4s} {cf}")
    print("\n=== SUMMARY ===")
    for k in ("VISION", "RECENCY", "BIGGEST"):
        print(summ(k, strat[k]))
    # head-to-head vision vs recency on shared days
    sh = [(r[2], r[3]) for r in rows if r[2] is not None]
    if sh:
        vw = sum(1 for v, rr in sh if v > rr)
        same = sum(1 for v, rr in sh if abs(v - rr) < 1e-6)
        print(f"\nVISION vs RECENCY (n={len(sh)}): vision strictly better {vw}, "
              f"same pick/again {same}, recency better {len(sh)-vw-same}")


if __name__ == "__main__":
    main()
