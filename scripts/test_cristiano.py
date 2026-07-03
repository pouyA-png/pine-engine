#!/usr/bin/env python3
"""THE decisive test: do Cristiano's REAL hand-drawn deviation-legs beat v25's own leg?
Inject his 203 drawn legs into the engine on their dates (NQ_continuous 2021-2022) and compare
per-day PnL to baseline v25 (its own leg) on the same days.
"""
import sys, json
sys.path.insert(0, "/home/pouya/pine-engine")
from zoneinfo import ZoneInfo

BASE = "/tmp/claude-1000/-home-pouya/df461499-5170-4d6c-bc06-333ca04eea33/scratchpad/bot_lastyear.pine"
DATA = "/mnt/d/C-Transfer-2026-06-11/Claude-memories/HistoricalTradingData/NQ_continuous_1m.csv"
LEGS = "/tmp/claude-1000/-home-pouya/df461499-5170-4d6c-bc06-333ca04eea33/scratchpad/legs_cristiano.json"
ANCHOR = "    _haveAnchors = startP != 0.0 and endP != 0.0"
NY = ZoneInfo("America/New_York"); PV = 20.0
START, END = "2021-03-01", "2022-11-01"


def override_block(legs):
    blk = ['    _ovKey = year(time,"America/New_York")*10000 + month(time,"America/New_York")*100 + dayofmonth(time,"America/New_York")']
    for d in sorted(legs):
        y, m, dd = d.split("-")
        key = int(y) * 10000 + int(m) * 100 + int(dd)
        blk.append(f"    if _ovKey == {key}")
        blk.append(f'        startP := {legs[d]["start"]:.2f}')
        blk.append(f'        endP   := {legs[d]["pivot"]:.2f}')
        blk.append('        startB := bar_index - 5')
        blk.append('        endB   := bar_index - 1')
    return "\n".join(blk) + "\n"


def per_day_pnl(trades):
    out = {}
    for t in trades:
        if not t.exit_time:
            continue
        d = t.entry_time.astimezone(NY).date().isoformat()
        sgn = 1 if t.side == "long" else -1
        out[d] = out.get(d, 0.0) + (t.exit_price - t.entry_price) * sgn * t.qty * PV
    return out


def main():
    from pine_engine.engine import compile_pine, run_backtest
    from pine_engine.data.loader import load_bars_csv
    legs = json.load(open(LEGS))
    labeled = set(legs)
    src = open(BASE).read()
    print(f"loading bars {START}..{END} ...", flush=True)
    bars = load_bars_csv(DATA, start_date=START, end_date=END)
    print(f"bars={len(bars)}", flush=True)

    print("run 1/2: v25 baseline (own leg) ...", flush=True)
    c0 = compile_pine(BASE)
    v25 = per_day_pnl(run_backtest(c0, bars, {"slPoints": 13.5}))

    print("run 2/2: Cristiano legs injected ...", flush=True)
    inj = src.replace(ANCHOR, override_block(legs) + ANCHOR, 1)
    pine2 = "/tmp/claude-1000/-home-pouya/df461499-5170-4d6c-bc06-333ca04eea33/scratchpad/inj_cristiano.pine"
    open(pine2, "w").write(inj)
    c1 = compile_pine(pine2)
    cris = per_day_pnl(run_backtest(c1, bars, {"slPoints": 13.5}))

    # compare on labeled days
    rows = []
    for d in sorted(labeled):
        rows.append((d, cris.get(d), v25.get(d)))

    def summ(name, vals):
        v = [x for x in vals if x is not None]
        if not v:
            return f"{name}: n=0"
        w = sum(1 for x in v if x > 0)
        gp = sum(x for x in v if x > 0); gl = -sum(x for x in v if x < 0)
        return (f"{name:12s} n={len(v):3d} WR={100*w/len(v):4.0f}% total=${sum(v):+8.0f} "
                f"PF={gp/gl if gl else 99:.2f} avg=${sum(v)/len(v):+6.0f}")

    cris_traded = [c for d, c, v in rows if c is not None]
    v25_on_labeled = [v for d, c, v in rows if v is not None]
    print("\n=== auf den 203 von Cristiano gelabelten Tagen ===")
    print(summ("CRISTIANO", [c for d, c, v in rows]))
    print(summ("V25", [v for d, c, v in rows]))
    # head-to-head where both traded
    both = [(c, v) for d, c, v in rows if c is not None and v is not None]
    if both:
        cw = sum(1 for c, v in both if c > v); vw = sum(1 for c, v in both if v > c); eq = sum(1 for c, v in both if c == v)
        print(f"\nHEAD-TO-HEAD (beide handelten, n={len(both)}): Cristiano besser {cw} · v25 besser {vw} · gleich {eq}")
        print(f"  Cristiano total ${sum(c for c,v in both):+.0f}  vs  v25 total ${sum(v for c,v in both):+.0f}")
    print(f"\nCristiano traded {len(cris_traded)}/{len(labeled)} labeled days; v25 traded {len(v25_on_labeled)}.")
    json.dump({"rows": rows}, open("/tmp/claude-1000/-home-pouya/df461499-5170-4d6c-bc06-333ca04eea33/scratchpad/cristiano_cmp.json", "w"))
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
