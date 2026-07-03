#!/usr/bin/env python3
"""Run the REAL v25_engine.pine via pine-engine and extract, per NY trading day,
WHAT THE BOT DRAWS: its detected leg (start/pivot), the 7 Gann/Fib levels, and the
blue Accumulation-Zone box. x-coords are Berlin minutes (to match the dashboard tmin axis).

We do NOT re-implement the strategy — we execute the real .pine and read the engine's
persistent `var` values (ctx.v_<name>) at each 09:30 NY open bar.

Usage (standalone test):
  python3 bot_overlay.py <v25.pine> <bars_1m.csv> [start_date] [end_date]
"""
import sys, os, json
from zoneinfo import ZoneInfo
sys.path.insert(0, "/home/pouya/pine-engine")
from pine_engine.engine import compile_pine, RuntimeContext
from pine_engine.data.loader import load_bars_csv

NY = ZoneInfo("America/New_York"); BERLIN = ZoneInfo("Europe/Berlin")


def _num(x):
    """float or None (handles the engine's NA object, nan, non-numerics)."""
    try:
        f = float(x)
        return f if f == f else None
    except Exception:
        return None


def bot_overlays(pine_path, csv_path, start_date=None, end_date=None):
    c = compile_pine(pine_path)
    bars = load_bars_csv(csv_path, start_date=start_date, end_date=end_date)
    n = len(bars)

    def bermin(idx):
        i = _num(idx)
        if i is None: return None
        i = int(i)
        if not (0 <= i < n): return None
        be = bars[i].timestamp.astimezone(BERLIN)
        return be.hour * 60 + be.minute

    ctx = RuntimeContext(params=c.get_default_params()); c.initialize(ctx)
    out = {}; seen = set()
    for bar in bars:
        ctx.strategy.process_bar(bar); ctx.update_bar(bar); c.execute_bar(ctx)
        ny = bar.timestamp.astimezone(NY)
        if not (ny.hour == 9 and ny.minute == 30 and ny.date() not in seen):
            continue
        seen.add(ny.date())
        g = lambda nm: getattr(ctx, "v_" + nm, None)
        sp, ep = _num(g("legStartPrice")), _num(g("legEndPrice"))
        if sp is None or ep is None:
            continue   # bot found no valid leg that day
        x0, x1 = bermin(g("legStartBar")), bermin(g("legEndBar"))
        lvl = lambda nm: (round(_num(g(nm)), 2) if _num(g(nm)) is not None else None)
        ah, al = _num(g("frozenAccumHigh")), _num(g("frozenAccumLow"))
        bx0, bx1 = bermin(g("frozenAccumStart")), bermin(g("frozenAccumEnd"))
        box = None
        if ah is not None and al is not None and bx0 is not None and bx1 is not None:
            box = {"hi": round(ah, 2), "lo": round(al, 2), "x0": min(bx0, bx1), "x1": max(bx0, bx1)}
        out[ny.date().isoformat()] = {
            "dir": "up" if g("legIsUp") else "down",
            "leg": {"x0": x0, "p0": round(sp, 2), "x1": x1, "p1": round(ep, 2)},
            "lvls": {"n140": lvl("lvl_n140"), "n078": lvl("lvl_n078"), "l000": lvl("lvl_000"),
                     "l050": lvl("lvl_050"), "l100": lvl("lvl_100"), "l178": lvl("lvl_178"), "l254": lvl("lvl_254")},
            "box": box,
        }
    return out


if __name__ == "__main__":
    pine, csv = sys.argv[1], sys.argv[2]
    sd = sys.argv[3] if len(sys.argv) > 3 else None
    ed = sys.argv[4] if len(sys.argv) > 4 else None
    ov = bot_overlays(pine, csv, sd, ed)
    print(f"days with bot leg: {len(ov)}")
    for d in sorted(ov)[:3]:
        print(d, json.dumps(ov[d]))
