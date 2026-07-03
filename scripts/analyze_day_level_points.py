"""Re-analyze with POINTS-based PnL (1 contract per trade) to strip the
position-sizing artifact from the dollar analysis.
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

compiled = compile_pine(PINE)
bars = load_bars_csv(DATA, start_date="2025-03-14", end_date="2026-03-13")
trades = run_backtest(compiled, bars, compiled.get_default_params())
print(f"Loaded {len(trades)} trades")

DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
LEVELS = ['Long_078', 'Long_140', 'Short_178', 'Short_254']

def pnl_points(t):
    """PnL in POINTS (1 contract) — strips qty bias."""
    return (t.exit_price - t.entry_price) if t.side == 'long' else (t.entry_price - t.exit_price)

buckets = defaultdict(list)
for t in trades:
    if t.entry_id not in LEVELS:
        continue
    dow = DAYS[t.entry_time.weekday()]
    buckets[(dow, t.entry_id)].append(t)

def stats(ts):
    if not ts:
        return None
    pts = [pnl_points(t) for t in ts]
    wins = [p for p in pts if p > 0]
    losses = [p for p in pts if p <= 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    pf = gp / gl if gl > 0 else float('inf')
    return {
        'n': len(ts),
        'wins': len(wins),
        'wr': 100*len(wins)/len(ts),
        'pf': pf,
        'net_pts': sum(pts),
        'avg_pts': sum(pts)/len(ts),
        'gp': gp,
        'gl': gl,
    }

print("\n" + "="*120)
print("MATRIX: Net POINTS per contract, by (Day x Level) — qty-neutral view")
print("="*120)
hdr = f"{'Day':>5} |"
for lvl in LEVELS:
    hdr += f" {lvl:>14} |"
hdr += f" {'TOTAL':>12}"
print(hdr)
print("-"*120)

day_tot = defaultdict(lambda: {'n':0, 'net':0})
lvl_tot = defaultdict(lambda: {'n':0, 'net':0})

for day in DAYS[:5]:
    row = f"{day:>5} |"
    dnet = 0
    dn = 0
    for lvl in LEVELS:
        s = stats(buckets.get((day, lvl), []))
        if s:
            row += f" {s['net_pts']:>7.1f}pt (n={s['n']:>2}) |"
            dnet += s['net_pts']; dn += s['n']
            lvl_tot[lvl]['net'] += s['net_pts']; lvl_tot[lvl]['n'] += s['n']
        else:
            row += f" {'—':>14} |"
    row += f" {dnet:>7.1f}pt (n={dn:>2})"
    day_tot[day] = {'n':dn, 'net':dnet}
    print(row)

print("-"*120)
tot = f"{'TOT':>5} |"
g_n = g_net = 0
for lvl in LEVELS:
    l = lvl_tot[lvl]
    tot += f" {l['net']:>7.1f}pt (n={l['n']:>2}) |"
    g_net += l['net']; g_n += l['n']
tot += f" {g_net:>7.1f}pt (n={g_n})"
print(tot)

print("\n" + "="*100)
print("FULL BUCKETS — sorted by Net Points desc (qty-neutral)")
print("="*100)
print(f"{'Day':>5} | {'Level':>10} | {'N':>3} | {'W':>3} | {'WR%':>5} | {'PF':>6} | {'NetPts':>9} | {'AvgPts':>7}")
print("-"*100)

rows = []
for (day, lvl), ts in buckets.items():
    s = stats(ts)
    if s:
        rows.append((day, lvl, s))
rows.sort(key=lambda x: x[2]['net_pts'], reverse=True)
for day, lvl, s in rows:
    pf_s = f"{s['pf']:.2f}" if s['pf'] != float('inf') else "inf"
    print(f"{day:>5} | {lvl:>10} | {s['n']:>3} | {s['wins']:>3} | {s['wr']:>4.1f} | {pf_s:>6} | {s['net_pts']:>8.1f} | {s['avg_pts']:>6.2f}")

# CSV
csv_path = OUT / "day_level_matrix_points.csv"
with open(csv_path, 'w') as f:
    f.write("day,level,n,wins,win_rate,profit_factor,net_points,avg_points,gross_points,loss_points\n")
    for day, lvl, s in rows:
        pf_s = f"{s['pf']:.2f}" if s['pf'] != float('inf') else "inf"
        f.write(f"{day},{lvl},{s['n']},{s['wins']},{s['wr']:.1f},{pf_s},{s['net_pts']:.1f},{s['avg_pts']:.2f},{s['gp']:.1f},{s['gl']:.1f}\n")
print(f"\nSaved: {csv_path}")

print("\n=== PROFITABLE BUCKETS (points-based) ===")
profit = [b for b in rows if b[2]['net_pts'] > 0]
if not profit:
    print("  None.")
for day, lvl, s in profit:
    pf_s = f"{s['pf']:.2f}" if s['pf'] != float('inf') else "inf"
    print(f"  {day} {lvl:>10}: N={s['n']} WR={s['wr']:.1f}% PF={pf_s} Net={s['net_pts']:+.1f}pt Avg={s['avg_pts']:+.2f}pt")

print("\n=== DAY TOTALS (points) ===")
for day in DAYS[:5]:
    d = day_tot[day]
    print(f"  {day}: N={d['n']:>3}  Net={d['net']:+.1f}pt  Avg={d['net']/d['n'] if d['n'] else 0:+.2f}pt")

print("\n=== LEVEL TOTALS (points) ===")
for lvl in LEVELS:
    l = lvl_tot[lvl]
    print(f"  {lvl:>10}: N={l['n']:>3}  Net={l['net']:+.1f}pt  Avg={l['net']/l['n'] if l['n'] else 0:+.2f}pt")
