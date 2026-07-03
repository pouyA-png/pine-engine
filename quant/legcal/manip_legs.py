#!/usr/bin/env python3
"""Test PRINCIPLED leg-DRAWING variants (not selection) against the v25 leg, by outcome-R.

The trading principle (Pouya): the pre-open leg is a real liquidity manipulation — price
sweeps a reference liquidity level (overnight / pre-open range extreme), then DISPLACES; the
pivot where displacement starts becomes the level algos defend at 09:30. So a principled leg
DRAWING anchors start = swept extreme, pivot = displacement origin.

Variants drawn per NY day from 1m bars:
  v25     : ground-truth v25 leg (from engine, baseline +116.6R)  [loaded, not recomputed]
  WINDOW  : leg-window 08:00-09:30 high<->low, chronological (v25's core logic, reimplemented)
  SWEEP_ON: sweep of OVERNIGHT range (00:00-08:00) extreme during 08:00-09:30 -> displacement pivot
  SWEEP_PO: sweep of PRE-OPEN early range (07:00-08:00) extreme during 08:00-09:30 -> pivot
  ACCUM   : last 30min of window (accumulation zone) high<->low chronological
  DISP_ORI: window extreme, but pivot pulled to the displacement-origin (biggest-body start)

Each drawing -> (start,pivot) -> outcome_sim R with the real v25 level/trade model.
Compares full-year + split-half stability. A win must beat v25 in BOTH halves.
"""
import json, sys
from datetime import date as Date, time
from zoneinfo import ZoneInfo
sys.path.insert(0, "/home/pouya/pine-engine/quant/legcal")
from outcome_sim import simulate_day

NY = ZoneInfo("America/New_York"); UTC = ZoneInfo("UTC")


def stream_days(path, start_date=None):
    """-> {ny_date: {'on':[(min,o,h,l,c)], 'win':[...], 'rth':[(o,h,l)]}}
    on = overnight 00:00-08:00 NY, win = leg window 08:00-09:30, rth = 09:30-16:00."""
    from datetime import datetime
    cut = datetime.fromisoformat(start_date + "T00:00:00").replace(tzinfo=UTC) if start_date else None
    out = {}; cur = None; on = []; win = []; rth = []
    def flush():
        if cur is not None:
            out[cur] = {"on": on[:], "win": win[:], "rth": rth[:]}
    with open(path) as f:
        f.readline()
        for line in f:
            c0 = line.find(",")
            if c0 < 0:
                continue
            ts = datetime.fromisoformat(line[:c0])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if cut and ts < cut:
                continue
            ny = ts.astimezone(NY); d = ny.date()
            if d != cur:
                flush(); cur = d; on = []; win = []; rth = []
            p = line.rstrip("\n").split(",")
            o, h, l, c = float(p[1]), float(p[2]), float(p[3]), float(p[4])
            m = ny.hour * 60 + ny.minute
            if 0 <= m < 480:                      # 00:00-08:00
                on.append((m, o, h, l, c))
            elif 480 <= m < 570:                  # 08:00-09:30 leg window
                win.append((m, o, h, l, c))
            if time(9, 30) <= ny.time() <= time(16, 0):
                rth.append((o, h, l))
    flush()
    return out


def draw_window(win):
    """v25 core: window high<->low ordered chronologically (start = earlier extreme)."""
    if not win:
        return None
    hi = max(win, key=lambda b: b[2]); lo = min(win, key=lambda b: b[3])
    hi_i = win.index(hi); lo_i = win.index(lo)
    if hi_i <= lo_i:
        return {"start": hi[2], "pivot": lo[3]}     # high first -> down leg
    return {"start": lo[3], "pivot": hi[2]}         # low first -> up leg


def draw_accum(win, mins=30):
    if not win:
        return None
    end_m = max(b[0] for b in win)
    acc = [b for b in win if b[0] >= end_m - mins]
    return draw_window(acc)


def draw_sweep(win, ref_hi, ref_lo):
    """Sweep of a reference range: find the window bar that most exceeds ref extreme (liquidity grab),
    that's the start; pivot = the opposite displacement extreme AFTER the sweep bar."""
    if not win or ref_hi is None:
        return None
    # how far above ref_hi / below ref_lo does the window poke?
    up_sweep = max(win, key=lambda b: b[2])      # highest high
    dn_sweep = min(win, key=lambda b: b[3])      # lowest low
    over = up_sweep[2] - ref_hi                  # >0 if swept the high (bullish liquidity grab -> expect down)
    under = ref_lo - dn_sweep[3]                 # >0 if swept the low
    if over <= 0 and under <= 0:
        return draw_window(win)                   # no sweep -> fall back to window swing
    if over >= under:                             # swept the HIGH -> start=that high, pivot=subsequent low
        si = win.index(up_sweep)
        after = win[si:]
        piv = min(after, key=lambda b: b[3])
        return {"start": up_sweep[2], "pivot": piv[3]}
    else:                                          # swept the LOW -> start=low, pivot=subsequent high
        si = win.index(dn_sweep)
        after = win[si:]
        piv = max(after, key=lambda b: b[2])
        return {"start": dn_sweep[3], "pivot": piv[2]}


def draw_disp_origin(win):
    """Window swing, but pivot snapped to the start of the biggest-body bar (displacement origin)."""
    base = draw_window(win)
    if not base or not win:
        return base
    big = max(win, key=lambda b: abs(b[4] - b[1]))   # biggest body
    # pivot = open of the displacement bar (where the impulse began)
    base = dict(base)
    # keep direction, replace pivot with displacement-origin price closest to it
    base["pivot"] = big[1]
    return base


def R(drawing, d, rth):
    if not drawing or drawing["start"] is None or drawing["pivot"] is None:
        return 0.0
    if abs(drawing["start"] - drawing["pivot"]) < 1e-6:
        return 0.0
    return simulate_day(drawing["start"], drawing["pivot"], Date.fromisoformat(d).weekday(), rth)["total_R"]


def main():
    data = stream_days("/home/pouya/pine-engine/quant/nq_lastyear.csv", "2025-03-13")
    v25 = json.load(open("/tmp/claude-1000/-home-pouya/df461499-5170-4d6c-bc06-333ca04eea33/scratchpad/lastyear/v25legs.json"))
    dates = sorted(d.isoformat() for d in data if data[d]["rth"] and data[d]["win"])
    half = len(dates) // 2
    variants = {"WINDOW": [], "SWEEP_ON": [], "SWEEP_PO": [], "ACCUM": [], "DISP_ORI": []}
    vh = {k: ([], []) for k in variants}; v25h = ([], [])
    for idx, d in enumerate(dates):
        day = data[Date.fromisoformat(d)]
        win = [(b[0], b[1], b[2], b[3], b[4]) for b in day["win"]]
        on = day["on"]; rth = day["rth"]
        on_hi = max((b[2] for b in on), default=None); on_lo = min((b[3] for b in on), default=None)
        po = [b for b in on if b[0] >= 420]      # 07:00-08:00
        po_hi = max((b[2] for b in po), default=on_hi); po_lo = min((b[3] for b in po), default=on_lo)
        h = 0 if idx < half else 1
        draws = {
            "WINDOW": draw_window(win),
            "SWEEP_ON": draw_sweep(win, on_hi, on_lo),
            "SWEEP_PO": draw_sweep(win, po_hi, po_lo),
            "ACCUM": draw_accum(win, 30),
            "DISP_ORI": draw_disp_origin(win),
        }
        for k, dr in draws.items():
            vh[k][h].append(R(dr, d, rth))
        if d in v25:
            v25h[h].append(R(v25[d], d, rth))

    def tot(a): return sum(a)
    def wr(a): return 100 * sum(1 for x in a if x > 0) / max(1, len(a))
    print(f"{'drawing':12s} {'H1':>9s} {'H2':>9s} {'YEAR':>9s} {'WR':>6s} {'øR':>6s}")
    def line(n, h1, h2):
        a = h1 + h2; print(f"{n:12s} {tot(h1):+9.1f} {tot(h2):+9.1f} {tot(a):+9.1f} {wr(a):5.0f}% {sum(a)/len(a):+6.2f}")
    line("V25-LEG *", *v25h)
    for k in variants:
        line(k, *vh[k])
    print("\n* Messlatte. Sieg nur wenn Variante V25-LEG in BEIDEN Hälften schlägt (sonst Overfit/Zufall).")


if __name__ == "__main__":
    main()
