#!/usr/bin/env python3
"""Inject an external per-day leg (date->start,pivot) into the REAL v25 pine and run it
through pine-engine -> REAL PF (full management, tick-sim). Measures the TRUE leg-headroom:
  python3 inject_leg.py <legs.json> [label]
legs.json: {"YYYY-MM-DD": {"start": float, "pivot": float}, ...}
Splices an override right before `_haveAnchors` so it replaces v25's own leg selection.
Days not in legs.json fall back to v25's own leg. Prints H1/H2/YEAR PF + net.
"""
import sys, json
sys.path.insert(0, "/home/pouya/pine-engine")

BASE = "/tmp/claude-1000/-home-pouya/df461499-5170-4d6c-bc06-333ca04eea33/scratchpad/bot_lastyear.pine"
DATA = "/home/pouya/pine-engine/quant/nq_lastyear.csv"
SPLIT = "2025-09-13"
ANCHOR = "    _haveAnchors = startP != 0.0 and endP != 0.0"


def build_override(legs):
    # array.* is broken in the engine (returns nan) -> use an if-chain on the NY date key.
    blk = ["    // ── INJECTED LEG OVERRIDE (experiment) ──",
           '    _ovKey = year(time,"America/New_York")*10000 + month(time,"America/New_York")*100 + dayofmonth(time,"America/New_York")']
    for d in sorted(legs):
        y, m, dd = d.split("-")
        key = int(y) * 10000 + int(m) * 100 + int(dd)
        blk.append(f"    if _ovKey == {key}")
        blk.append(f'        startP := {legs[d]["start"]:.2f}')
        blk.append(f'        endP   := {legs[d]["pivot"]:.2f}')
        blk.append('        startB := bar_index - 5')
        blk.append('        endB   := bar_index - 1')
    blk.append("")
    return "\n".join(blk)


def main():
    legs = json.load(open(sys.argv[1]))
    label = sys.argv[2] if len(sys.argv) > 2 else sys.argv[1]
    src = open(BASE).read()
    if ANCHOR not in src:
        print("ANCHOR not found!"); sys.exit(1)
    inj = build_override(legs) + "\n" + ANCHOR
    src2 = src.replace(ANCHOR, inj, 1)
    out_pine = f"/tmp/claude-1000/-home-pouya/df461499-5170-4d6c-bc06-333ca04eea33/scratchpad/inj_{label}.pine"
    open(out_pine, "w").write(src2)

    from pine_engine.engine import compile_pine, run_backtest
    from pine_engine.data.loader import load_bars_csv
    from pine_engine.reporting.stats import compute_stats
    c = compile_pine(out_pine)
    print(f"[{label}] override days={len(legs)}", flush=True)
    for lbl, sd, ed in [("H1", None, SPLIT), ("H2", "2025-09-14", None), ("YEAR", None, None)]:
        bars = load_bars_csv(DATA, start_date=sd, end_date=ed)
        tr = run_backtest(c, bars, {"slPoints": 13.5})
        st = compute_stats(tr, point_value=20.0)
        print(f"  {lbl:5s} PF={st['profit_factor']:.2f} Net={st['net_pnl']:+.0f} "
              f"Trades={st['total_trades']} WR={st['win_rate']*100:.0f}%", flush=True)


if __name__ == "__main__":
    main()
