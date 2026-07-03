#!/usr/bin/env python3
"""Mechanical pre-open leg SELECTOR — reverse-engineered from Cristiano's labelled CME picks.

RULE (final, 2026-06-29 refit on 85 cand-days):
    pick the MOST-RECENT candidate of the day (smallest `minopen` = nearest to 09:30).

WHY ONLY RECENCY:
  Every other feature was tested and ZEROED — adding any of size/clean/eff/disp/distlvl/
  round/wick/sweep LOWERED out-of-sample accuracy. The old full-weight fit overfit
  (in-sample 52% -> k-fold OOS 42%) and sign-flipped between years; recency-only does not.

VALIDATION (85 labelled cand-days, leglab CME):
  - recency-only OOS 48.2% (parameter-free -> cannot overfit)
  - regime-stable: 2021 46% (n=37), 2022 50% (n=48)
  - ~4.1x over random (random ~12% at avg 8.4 candidates/day)
  - picked is in the 2 most-recent on 76% of days
  - best recency+secondary OOS = 48.2% (+0.0pp): no secondary tiebreak helps

CAVEAT for the loosened detector: after re-exporting candidates with the 2026-06-29
endpoint-extension (leg_candidates.py), pivots cluster near 09:30 and pivot `minopen`
loses discrimination -> rank by leg START recency instead. Not yet testable (old snaps).
"""
from typing import Optional, List, Dict


def select_leg_index(candidates: List[Dict]) -> Optional[int]:
    """Return the index of the selected candidate (most-recent), or None if empty.
    `candidates` are the per-day snap dicts; each must carry `minopen` (minutes before 09:30)."""
    if not candidates:
        return None
    return min(range(len(candidates)), key=lambda i: candidates[i]["minopen"])


if __name__ == "__main__":
    # quick self-check against the live labels
    import json, sys, statistics
    path = sys.argv[1] if len(sys.argv) > 1 else "/home/pouya/leglab-backups/labels_latest.json"
    st = json.load(open(path))
    hit = tot = 0
    for date, v in st.get("cme", {}).items():
        if v.get("type") != "cand":
            continue
        snap = v.get("snap", {}).get(v.get("tf"), [])
        idx = v.get("idx")
        if not (isinstance(idx, int) and 0 <= idx < len(snap)):
            continue
        tot += 1
        if select_leg_index(snap) == idx:
            hit += 1
    print(f"recency-selector in-sample hit on {path}: {hit}/{tot} = {100*hit/tot:.1f}%" if tot else "no cand labels")
