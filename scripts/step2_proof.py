#!/usr/bin/env python3
"""STEP 2 — empirically prove the bot's CME 'no trade' suspects with the now-runnable engine.
Proves: (1) Monday is hard-blocked even with enableMondayTrading=true (dead input);
        (2) the weekday x entry-type order matrix is degenerate (Thu/Wed dead-spots)."""
import sys, collections
sys.path.insert(0, ".")
from pine_engine.engine import compile_pine, run_backtest
from pine_engine.data.loader import load_bars_csv

BOT = "/mnt/c/Users/nader/Documents/Claude-memories/trading bot/trading_bot.pine"
WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

bars = load_bars_csv(sys.argv[1] if len(sys.argv) > 1 else "quant/nq_2yr.csv")
print(f"bars={len(bars)}  {bars[0].timestamp.date()} .. {bars[-1].timestamp.date()}")
c = compile_pine(BOT)


def as_list(res):
    if isinstance(res, list):
        return res
    for attr in ("trades", "closed_trades", "closedtrades"):
        v = getattr(res, attr, None)
        if isinstance(v, list):
            return v
    if isinstance(res, dict):
        for k in ("trades", "closed_trades"):
            if isinstance(res.get(k), list):
                return res[k]
    return list(res)


def tabulate(params, label):
    tr = as_list(run_backtest(c, bars, params))
    # dedup to distinct ENTRIES (TP1/TP2 are separate closed legs sharing one entry)
    entries = set()
    for t in tr:
        et = getattr(t, "entry_time", None)
        ec = getattr(t, "entry_comment", "?")
        if et is not None:
            entries.add((et, ec))
    byday = collections.Counter()
    bydaytype = collections.defaultdict(set)
    bydaytype_n = collections.Counter()
    for et, ec in entries:
        d = WD[et.weekday()]
        byday[d] += 1
        bydaytype[d].add(ec)
        bydaytype_n[(d, ec)] += 1
    print(f"\n[{label}]  distinct entries={len(entries)}  closed legs={len(tr)}")
    print("  entries per weekday:", {d: byday[d] for d in WD if byday[d]})
    for d in WD:
        if bydaytype[d]:
            types = {ec: bydaytype_n[(d, ec)] for ec in sorted(bydaytype[d])}
            print(f"    {d}: {types}")
    return byday


bd_def = tabulate(None, "DEFAULT (enableMondayTrading=false)")
bd_mon = tabulate({"enableMondayTrading": True}, "enableMondayTrading=TRUE")

print("\n=== VERDICT ===")
print(f"  Monday entries  default={bd_def.get('Mon',0)}  with enableMondayTrading=TRUE={bd_mon.get('Mon',0)}")
print("  -> if both 0: 'enableMondayTrading' is a DEAD input (not wired into allowTradeToday).")
print("  -> Thu only 'Long_140', Wed only 'Short_178' confirms the degenerate place-flag matrix")
print("     (UP-leg Thu => 0 orders, UP-leg Wed => 1 short).")
