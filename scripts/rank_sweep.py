#!/usr/bin/env python3
"""For each recency-rank k, inject 'pick the k-th candidate each day' into the REAL v25 pine,
run through pine-engine, and record per-day PnL. -> matrix {date: {rank: pnl}} measured in the
REAL engine (full management). Then: true real-engine oracle (best rank/day) + characterise what
distinguishes the winning leg, so a PRE-OPEN rule can be designed to capture the ceiling.
"""
import sys, json
sys.path.insert(0, "/home/pouya/pine-engine")
from zoneinfo import ZoneInfo

BASE = "/tmp/claude-1000/-home-pouya/df461499-5170-4d6c-bc06-333ca04eea33/scratchpad/bot_lastyear.pine"
DATA = "/home/pouya/pine-engine/quant/nq_lastyear.csv"
LY = "/tmp/claude-1000/-home-pouya/df461499-5170-4d6c-bc06-333ca04eea33/scratchpad/lastyear"
ANCHOR = "    _haveAnchors = startP != 0.0 and endP != 0.0"
NY = ZoneInfo("America/New_York")
PV = 20.0
MAXRANK = 16


def override_block(legs):
    blk = ["    _ovKey = year(time,\"America/New_York\")*10000 + month(time,\"America/New_York\")*100 + dayofmonth(time,\"America/New_York\")"]
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
        pnl = (t.exit_price - t.entry_price) * sgn * t.qty * PV
        out[d] = out.get(d, 0.0) + pnl
    return out


def main():
    from pine_engine.engine import compile_pine, run_backtest
    from pine_engine.data.loader import load_bars_csv
    meta = json.load(open(f"{LY}/days.json"))
    src = open(BASE).read()
    bars = load_bars_csv(DATA)
    matrix = {}      # date -> {rank: pnl}
    rank_days = {}   # rank -> set of dates that had that rank
    for k in range(MAXRANK):
        legs = {}
        for d in sorted(meta):
            cands = meta[d]["cands"]; order = meta[d]["recency_order"]
            if k < len(order):
                c = cands[order[k]]
                legs[d] = {"start": c["start"], "pivot": c["pivot"]}
        if not legs:
            continue
        src2 = src.replace(ANCHOR, override_block(legs) + ANCHOR, 1)
        pine = f"/tmp/claude-1000/-home-pouya/df461499-5170-4d6c-bc06-333ca04eea33/scratchpad/rk_{k}.pine"
        open(pine, "w").write(src2)
        c = compile_pine(pine)
        trades = run_backtest(c, bars, {"slPoints": 13.5})
        pnl = per_day_pnl(trades)
        rank_days[k] = set(legs)
        for d, v in pnl.items():
            matrix.setdefault(d, {})[k] = v
        tot = sum(pnl.values())
        print(f"rank {k:2d}: days={len(legs)} totalPnL={tot:+.0f} tradedDays={len(pnl)}", flush=True)

    json.dump({"matrix": matrix, "rank_days": {k: sorted(v) for k, v in rank_days.items()}},
              open(f"{LY}/rank_pnl.json", "w"))

    # real-engine oracle: best rank per day (only over days that traded under SOME rank)
    oracle_pnl = 0.0; best_rank_hist = {}
    for d, rr in matrix.items():
        if not rr:
            continue
        bk = max(rr, key=lambda k: rr[k])
        oracle_pnl += rr[bk]
        best_rank_hist[bk] = best_rank_hist.get(bk, 0) + 1
    print(f"\nREAL-ENGINE ORACLE (best rank/day): totalPnL={oracle_pnl:+.0f}")
    print(f"  best-rank histogram: {dict(sorted(best_rank_hist.items()))}")
    print(f"  days with any trade: {len(matrix)}")
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
