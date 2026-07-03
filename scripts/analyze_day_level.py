"""Run vvv1_all_days (UP-only, all weekdays, all levels) and bucket trades by
(day_of_week x entry_level) to find best-performing combinations.
"""
import sys
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, '/home/pouya/pine-engine')

from pine_engine.engine import compile_pine, run_backtest
from pine_engine.data.loader import load_bars_csv

PINE = "/mnt/c/Users/nader/Documents/Claude-memories/trading bot/vvv1_all_days.pine"
DATA = "/mnt/c/Users/nader/Documents/Claude-memories/HistoricalTradingData/NQ_continuous_1m.csv"
OUT = Path("/home/pouya/pine-engine/output/vvv1")
OUT.mkdir(parents=True, exist_ok=True)

POINT_VALUE = 20.0  # NQ E-mini

print("Compiling...")
compiled = compile_pine(PINE)
print("Loading bars...")
bars = load_bars_csv(DATA, start_date="2025-03-14", end_date="2026-03-13")
print(f"  {len(bars)} bars loaded")
print("Running backtest...")
trades = run_backtest(compiled, bars, compiled.get_default_params())
print(f"  {len(trades)} trades")

DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
LEVELS = ['Long_078', 'Long_140', 'Short_178', 'Short_254']

def pnl_dollars(t):
    pts = (t.exit_price - t.entry_price) if t.side == 'long' else (t.entry_price - t.exit_price)
    return pts * t.qty * POINT_VALUE

# Bucket trades by (day, level)
buckets = defaultdict(list)
for t in trades:
    if t.entry_id not in LEVELS:
        continue
    # NY-equivalent day: entries happen 13:30-16:00 UTC = 09:30-12:00 NY, same weekday
    dow = DAYS[t.entry_time.weekday()]
    buckets[(dow, t.entry_id)].append(t)

# Compute stats per bucket
def bucket_stats(ts):
    if not ts:
        return None
    pnls = [pnl_dollars(t) for t in ts]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    wr = 100 * len(wins) / len(ts)
    net = sum(pnls)
    avg = net / len(ts)
    return {
        'n': len(ts),
        'wins': len(wins),
        'losses': len(losses),
        'wr': wr,
        'pf': pf,
        'net': net,
        'avg': avg,
        'gross_profit': gross_profit,
        'gross_loss': gross_loss,
    }

# Matrix display
print("\n" + "="*120)
print("MATRIX: Net PnL by (Day of Week x Entry Level)")
print("="*120)
header = f"{'Day':>5} |"
for lvl in LEVELS:
    header += f" {lvl:>10} |"
header += f" {'TOTAL':>10}"
print(header)
print("-"*120)

day_totals = defaultdict(lambda: {'n':0, 'net':0.0})
level_totals = defaultdict(lambda: {'n':0, 'net':0.0})

for day in DAYS[:5]:  # Mon-Fri only
    row = f"{day:>5} |"
    day_net = 0
    day_n = 0
    for lvl in LEVELS:
        stats = bucket_stats(buckets.get((day, lvl), []))
        if stats:
            row += f" ${stats['net']:>8,.0f}({stats['n']:>2}) |"
            day_net += stats['net']
            day_n += stats['n']
            level_totals[lvl]['net'] += stats['net']
            level_totals[lvl]['n'] += stats['n']
        else:
            row += f" {'—':>10} |"
    row += f" ${day_net:>8,.0f}({day_n})"
    day_totals[day] = {'n': day_n, 'net': day_net}
    print(row)

print("-"*120)
tot_row = f"{'TOT':>5} |"
grand_net = 0
grand_n = 0
for lvl in LEVELS:
    lvl_net = level_totals[lvl]['net']
    lvl_n = level_totals[lvl]['n']
    tot_row += f" ${lvl_net:>8,.0f}({lvl_n:>2}) |"
    grand_net += lvl_net
    grand_n += lvl_n
tot_row += f" ${grand_net:>8,.0f}({grand_n})"
print(tot_row)

# Detailed per-bucket table
print("\n" + "="*120)
print("FULL BUCKET STATS (sorted by Net PnL desc)")
print("="*120)
print(f"{'Day':>5} | {'Level':>10} | {'N':>3} | {'W':>3} | {'L':>3} | {'WR%':>5} | {'PF':>6} | {'Net':>10} | {'Avg':>8} | {'GProf':>8} | {'GLoss':>8}")
print("-"*120)

all_buckets = []
for (day, lvl), ts in buckets.items():
    s = bucket_stats(ts)
    if s:
        all_buckets.append((day, lvl, s))
all_buckets.sort(key=lambda x: x[2]['net'], reverse=True)

for day, lvl, s in all_buckets:
    pf_str = f"{s['pf']:.2f}" if s['pf'] != float('inf') else "inf"
    print(f"{day:>5} | {lvl:>10} | {s['n']:>3} | {s['wins']:>3} | {s['losses']:>3} | {s['wr']:>4.1f} | {pf_str:>6} | ${s['net']:>8,.0f} | ${s['avg']:>6,.0f} | ${s['gross_profit']:>6,.0f} | ${s['gross_loss']:>6,.0f}")

# Save CSV
csv_path = OUT / "day_level_matrix.csv"
with open(csv_path, 'w') as f:
    f.write("day,level,n,wins,losses,win_rate,profit_factor,net_pnl,avg_pnl,gross_profit,gross_loss\n")
    for day, lvl, s in all_buckets:
        pf_str = f"{s['pf']:.2f}" if s['pf'] != float('inf') else "inf"
        f.write(f"{day},{lvl},{s['n']},{s['wins']},{s['losses']},{s['wr']:.1f},{pf_str},{s['net']:.0f},{s['avg']:.0f},{s['gross_profit']:.0f},{s['gross_loss']:.0f}\n")
print(f"\nSaved: {csv_path}")

# Highlight profitable buckets
print("\n" + "="*80)
print("PROFITABLE BUCKETS (net > 0)")
print("="*80)
profitable = [b for b in all_buckets if b[2]['net'] > 0]
if not profitable:
    print("  None.")
else:
    for day, lvl, s in profitable:
        pf_str = f"{s['pf']:.2f}" if s['pf'] != float('inf') else "inf"
        print(f"  {day} {lvl}: N={s['n']} WR={s['wr']:.1f}% PF={pf_str} Net=${s['net']:,.0f} Avg=${s['avg']:,.0f}")

# Per-day totals
print("\n=== DAY TOTALS ===")
for day in DAYS[:5]:
    d = day_totals[day]
    print(f"  {day}: {d['n']:>3} trades, Net=${d['net']:>10,.0f}")

# Per-level totals
print("\n=== LEVEL TOTALS ===")
for lvl in LEVELS:
    l = level_totals[lvl]
    print(f"  {lvl:>10}: {l['n']:>3} trades, Net=${l['net']:>10,.0f}")
