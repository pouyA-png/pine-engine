#!/usr/bin/env python3
"""Leg-Labeling harness — candidate detection + measurable features.

For each NY trading day, find every pre-market leg candidate in the
08:00–09:30 (NY) window and compute the features Pouya labels by feel, so a
parameterised selector can later be fit to reproduce his picks.

LOOK-AHEAD DISCIPLINE: every PRICE feature uses only bars up to & including the
candidate's pivot bar (the decision moment). Pivot *confirmation* needs
`lookback` right-side bars — allowed for offline labeling, never feeds a price
feature.

Fixes applied after adversarial audit:
  A) efficiency/cleanliness now use the leg's EXTREME displacement (consistent
     with leg_size), path = close-to-close travel, clamped [0,1].
  B) multi-scale pivots (lookbacks {3,5}) merged + deduped → big legs that span
     a minor counter-pivot are representable.
  C) wick body floored + ratio clipped.
  + percent-scaled min-size floor (handles the price-scale confound).
  + features added: Displacement (whale move), Dist-Prev-Level, Round-Dist.

Outputs one row PER CANDIDATE so Pouya just marks the correct one.
"""
import argparse, csv, statistics
from datetime import datetime, time
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
OPEN_T = time(9, 30)
RTH_OPEN, RTH_CLOSE = time(9, 30), time(16, 0)
TICK = 0.1


def hhmm(s):
    h, m = s.split(":")
    return time(int(h), int(m))


def load_window_days(path, win_start):
    """{ny_date: [bars]} for bars in [win_start, 09:40] NY (window + confirm tail)."""
    days = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            ts = datetime.fromisoformat(row["datetime"]).astimezone(NY)
            if not (win_start <= ts.time() <= time(9, 40)):
                continue
            days.setdefault(ts.date(), []).append({
                "ts": ts, "t": ts.time(), "o": float(row["open"]), "h": float(row["high"]),
                "l": float(row["low"]), "c": float(row["close"]), "v": float(row.get("volume", 0) or 0)})
    for d in days:
        days[d].sort(key=lambda b: b["ts"])
    return days


def load_prev_rth_levels(path):
    """{ny_date: (prevH, prevL, prevC)} from the previous NY day's RTH (09:30-16:00)."""
    hi, lo, cl = {}, {}, {}
    with open(path) as f:
        for row in csv.DictReader(f):
            ts = datetime.fromisoformat(row["datetime"]).astimezone(NY)
            if not (RTH_OPEN <= ts.time() <= RTH_CLOSE):
                continue
            d = ts.date()
            h, l, c = float(row["high"]), float(row["low"]), float(row["close"])
            hi[d] = max(hi.get(d, -1e18), h)
            lo[d] = min(lo.get(d, 1e18), l)
            cl[d] = c  # last close of the day wins (chronological)
    days = sorted(hi)
    prev = {days[i]: (hi[days[i-1]], lo[days[i-1]], cl[days[i-1]]) for i in range(1, len(days))}
    return prev


def find_pivots(bars, L, win_end):
    piv = []
    n = len(bars)
    for i in range(L, n - L):
        if bars[i]["t"] >= win_end:      # exclude the 09:30 open bar (pre-open only)
            continue
        hi, lo = bars[i]["h"], bars[i]["l"]
        is_h = all(hi >= bars[i - k]["h"] and hi >= bars[i + k]["h"] for k in range(1, L + 1))
        is_l = all(lo <= bars[i - k]["l"] and lo <= bars[i + k]["l"] for k in range(1, L + 1))
        if is_h and is_l:
            # outside bar = both extremes: classify by bar direction (down bar -> high pivot)
            down = bars[i]["c"] < bars[i]["o"]
            piv.append((i, "H", hi) if down else (i, "L", lo))
        elif is_h:
            piv.append((i, "H", hi))
        elif is_l:
            piv.append((i, "L", lo))
    return piv


def efficiency(bars, i0, i1, p0, p1):
    """Directional cleanliness: extreme displacement / close-to-close travel, clamped."""
    disp = abs(p1 - p0)
    path = sum(abs(bars[k]["c"] - bars[k - 1]["c"]) for k in range(i0 + 1, i1 + 1))
    if path <= 0:
        return 1.0
    return min(1.0, disp / path)


def clean_1to5(er):
    return max(1, min(5, int(round(1 + er * 4))))


def build_candidates(bars, lookbacks, win_end):
    """Multi-scale: union of adjacent-pivot swings across each lookback, deduped."""
    seen = {}
    for L in lookbacks:
        piv = find_pivots(bars, L, win_end)
        for a in range(len(piv) - 1):
            i0, k0, p0 = piv[a]
            i1, k1, p1 = piv[a + 1]
            if k0 == k1:
                continue
            key = (i0, i1)
            if key not in seen:
                seen[key] = (i0, i1, p0, p1)
    return list(seen.values())


def candidates_for_day(bars, lookbacks, min_abs, min_pct, win_end, prev_levels, anchor_win=None, extend_endpoint=True):
    raw = build_candidates(bars, lookbacks, win_end)
    # window-anchored synthetic leg for monotone trend days (only one pivot -> no adjacent-pair candidate)
    if anchor_win is not None:
        ls, le = anchor_win
        widx = [j for j, b in enumerate(bars) if ls <= b["t"] < le]
        if widx:
            a = widx[0]
            hi_j = max(widx, key=lambda j: bars[j]["h"])
            lo_j = min(widx, key=lambda j: bars[j]["l"])
            up_move = bars[hi_j]["h"] - bars[a]["l"]
            dn_move = bars[a]["h"] - bars[lo_j]["l"]
            anc = None
            if up_move >= dn_move and hi_j > a:
                anc = (a, hi_j, bars[a]["l"], bars[hi_j]["h"])
            elif lo_j > a:
                anc = (a, lo_j, bars[a]["h"], bars[lo_j]["l"])
            if anc and (anc[0], anc[1]) not in {(c[0], c[1]) for c in raw}:
                raw.append(anc)
    # ENDPOINT EXTENSION (2026-06-29): the strict +/-L pivot end truncates legs whose true
    # pre-open extreme prints in the final minutes / lacks right-side confirmation. For each
    # candidate, extend its END to the dir-consistent window extreme reached after its start
    # (only forward, only pre-open). Recovers ~half of the hand-drawn detector-misses at ZERO
    # extra candidate clutter (verified: drawn-leg coverage 43%->77%, cand/day unchanged).
    # Offline-labeling only (whole pre-open known by 09:30) — the live bot uses its own frozenWin.
    if extend_endpoint and raw:
        pre_n = sum(1 for b in bars if b["t"] < win_end)
        ext = {}
        for i0, i1, p0, p1 in raw:
            up = p1 > p0
            j_ext, p_ext = i1, p1
            for j in range(i0 + 1, pre_n):
                if up and bars[j]["h"] > p_ext:
                    p_ext, j_ext = bars[j]["h"], j
                elif (not up) and bars[j]["l"] < p_ext:
                    p_ext, j_ext = bars[j]["l"], j
            ext[(i0, j_ext)] = (i0, j_ext, p0, p_ext)   # dedup by (start, extended-end)
        raw = list(ext.values())
    cands = []
    for i0, i1, p0, p1 in raw:
        size = abs(p1 - p0)
        if size < max(min_abs, min_pct / 100.0 * p1):
            continue
        direction = "up" if p1 > p0 else "down"
        er = efficiency(bars, i0, i1, p0, p1)
        eb = bars[i1]
        body = max(abs(eb["c"] - eb["o"]), TICK)
        wick = (eb["h"] - max(eb["o"], eb["c"])) if p1 > p0 else (min(eb["o"], eb["c"]) - eb["l"])
        wick_ratio = min(wick / body, 10.0)
        # liquidity sweep: start pivot took out the prior same-side extreme in-window
        prior = bars[:i0]
        sweep = False
        if prior:
            sweep = (p0 < min(b["l"] for b in prior)) if direction == "up" else (p0 > max(b["h"] for b in prior))
        # impulse (range-based) vs window median range up to pivot
        leg_rng = [bars[j]["h"] - bars[j]["l"] for j in range(i0, i1 + 1)]
        upto = [bars[j]["h"] - bars[j]["l"] for j in range(0, i1 + 1)]
        med = statistics.median(upto) if upto else 1.0
        ri = (sum(leg_rng) / len(leg_rng)) / med if med else 1.0
        impulse = "hoch" if ri >= 1.6 else ("mittel" if ri >= 0.9 else "niedrig")
        # NEW: displacement (whale) = biggest single-bar body in leg / median body UP TO pivot (no look-ahead)
        _medbody = statistics.median([abs(bars[j]["c"] - bars[j]["o"]) for j in range(0, i1 + 1)]) or TICK
        disp_feat = max(abs(bars[j]["c"] - bars[j]["o"]) for j in range(i0, i1 + 1)) / _medbody
        # NEW: distance of pivot to nearest prev-day RTH level
        if prev_levels:
            dist_lvl = min(abs(p1 - lv) for lv in prev_levels)
        else:
            dist_lvl = ""
        # NEW: round-number distance (G=50 for US100)
        G = 50.0
        rmod = p1 % G
        round_dist = min(rmod, G - rmod)
        cands.append({
            "direction": direction, "i0": i0, "i1": i1,
            "start_time": bars[i0]["ts"].strftime("%H:%M"), "start_price": round(p0, 2),
            "pivot_time": eb["ts"].strftime("%H:%M"), "pivot_price": round(p1, 2),
            "leg_size": round(size, 2), "efficiency": round(er, 3), "clean": clean_1to5(er),
            "wick": "J" if wick_ratio >= 1.0 else "N", "wick_ratio": round(wick_ratio, 2),
            "sweep": "J" if sweep else "N", "impulse": impulse,
            "min_before_open": round((datetime.combine(eb["ts"].date(), OPEN_T, tzinfo=NY) - eb["ts"]).total_seconds() / 60.0),
            "displacement": round(disp_feat, 2),
            "dist_level": round(dist_lvl, 1) if dist_lvl != "" else "",
            "round_dist": round(round_dist, 1),
            "_size": size, "_pt": eb["ts"],
        })
    if cands:
        mx = max(c["_size"] for c in cands)
        latest = max(c["_pt"] for c in cands)
        for c in cands:
            c["n"] = len(cands)
            c["biggest"] = "J" if c["_size"] == mx else "N"
            c["latest"] = "J" if c["_pt"] == latest else "N"
    return cands


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--lookbacks", default="2,3,5")
    ap.add_argument("--min-abs", type=float, default=8.0)
    ap.add_argument("--min-pct", type=float, default=0.10)
    ap.add_argument("--win-start", default="08:00")
    ap.add_argument("--win-end", default="09:30")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--last-n", type=int, default=0)
    a = ap.parse_args()

    ws, we = hhmm(a.win_start), hhmm(a.win_end)
    lbs = [int(x) for x in a.lookbacks.split(",")]
    days = load_window_days(a.data, ws)
    prev = load_prev_rth_levels(a.data)
    dates = sorted(days)
    if a.start:
        dates = [d for d in dates if d.isoformat() >= a.start]
    if a.end:
        dates = [d for d in dates if d.isoformat() <= a.end]
    if a.last_n:
        dates = dates[-a.last_n:]

    cols = ["Datum", "Kandidat#", "KORREKT(x)", "Richtung", "Start-Zeit", "Start-Preis",
            "Pivot-Zeit", "Pivot-Preis", "Leg-Groesse(Pkt)", "#Kandidaten", "War-groesster",
            "War-letzter", "Liquidity-Sweep", "Rejection-Wick", "Wick-Ratio",
            "Pivot-Sauberkeit(1-5)", "Efficiency", "Displacement", "Dist-Prev-Level",
            "Round-Dist", "Min-vor-9:30", "Impuls", "Grund", "Verworfen-weil"]
    rows, days_with, perday = [], 0, {}
    for d in dates:
        cs = candidates_for_day(days[d], lbs, a.min_abs, a.min_pct, we, prev.get(d))
        perday[len(cs)] = perday.get(len(cs), 0) + 1
        if cs:
            days_with += 1
        for i, c in enumerate(sorted(cs, key=lambda x: x["_pt"]), 1):
            rows.append({
                "Datum": d.isoformat(), "Kandidat#": i, "KORREKT(x)": "", "Richtung": c["direction"],
                "Start-Zeit": c["start_time"], "Start-Preis": c["start_price"], "Pivot-Zeit": c["pivot_time"],
                "Pivot-Preis": c["pivot_price"], "Leg-Groesse(Pkt)": c["leg_size"], "#Kandidaten": c["n"],
                "War-groesster": c["biggest"], "War-letzter": c["latest"], "Liquidity-Sweep": c["sweep"],
                "Rejection-Wick": c["wick"], "Wick-Ratio": c["wick_ratio"], "Pivot-Sauberkeit(1-5)": c["clean"],
                "Efficiency": c["efficiency"], "Displacement": c["displacement"], "Dist-Prev-Level": c["dist_level"],
                "Round-Dist": c["round_dist"], "Min-vor-9:30": c["min_before_open"], "Impuls": c["impulse"],
                "Grund": "", "Verworfen-weil": ""})
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"days={len(dates)} days_with_candidates={days_with} rows={len(rows)} -> {a.out}")
    print("candidates-per-day:", dict(sorted(perday.items())))


if __name__ == "__main__":
    main()
