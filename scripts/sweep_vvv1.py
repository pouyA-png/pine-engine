"""vvv1 UP-only parameter sweep: 125 combinations over last 365 days."""
import sys
import math
from pathlib import Path
sys.path.insert(0, '/home/pouya/pine-engine')

from pine_engine.batch.runner import BatchRunner, export_results
from pine_engine.batch.param_grid import generate_grid

PINE = "/mnt/c/Users/nader/Documents/Claude-memories/trading bot/vvv1_testing.pine"
DATA = "/mnt/c/Users/nader/Documents/Claude-memories/HistoricalTradingData/NQ_continuous_1m.csv"
OUT_DIR = Path("/home/pouya/pine-engine/output/vvv1")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 5 x 5 x 5 = 125 combos
grid = generate_grid({
    "slPoints":       [6.0, 9.0, 12.0, 15.0, 18.0],
    "slPointsWedThu": [8.0, 11.0, 14.0, 17.0, 20.0],
    "minRangeTicks":  [12, 20, 28, 40, 55],
})
print(f"Grid size: {len(grid)}")

runner = BatchRunner(
    pine_path=PINE,
    data_paths=[DATA],
    param_grid=grid,
    start_date="2025-03-14",
    end_date="2026-03-13",
    point_value=20.0,
)

results = runner.run(workers=8, progress=True)

csv_path = OUT_DIR / "sweep_leaderboard.csv"
export_results(results, str(csv_path))
print(f"\nLeaderboard saved: {csv_path}")

for r in results:
    pf = r.get('profit_factor', 0) or 0
    n = r.get('total_trades', 0) or 0
    exp = r.get('expectancy', 0) or 0
    if n < 20 or exp <= 0:
        r['composite'] = 0.0
    else:
        r['composite'] = pf * math.sqrt(n)

results.sort(key=lambda r: r['composite'], reverse=True)

print("\n" + "="*120)
print(f"{'Rank':>4} | {'Comp':>6} | {'PF':>5} | {'WR%':>5} | {'N':>4} | {'NetPnL':>10} | {'DD%':>5} | {'SL':>5} | {'SL_WT':>5} | {'MinRng':>6}")
print("-"*120)
for i, r in enumerate(results[:25], 1):
    p = r.get('params', {})
    print(f"{i:4} | {r['composite']:6.2f} | {r.get('profit_factor',0):5.2f} | {r.get('win_rate',0):5.1f} | {r.get('total_trades',0):4} | {r.get('net_pnl',0):10,.0f} | {r.get('max_drawdown_pct',0):4.1f}% | {p.get('slPoints',0):5.1f} | {p.get('slPointsWedThu',0):5.1f} | {p.get('minRangeTicks',0):6}")

top_path = OUT_DIR / "top25.txt"
with open(top_path, 'w') as f:
    f.write("Top 25 by composite (PF * sqrt(N), requires N>=20 and expectancy>0):\n\n")
    f.write(f"{'Rank':>4} | {'Comp':>6} | {'PF':>5} | {'WR%':>5} | {'N':>4} | {'NetPnL':>10} | {'DD%':>5} | {'SL':>5} | {'SL_WT':>5} | {'MinRng':>6}\n")
    for i, r in enumerate(results[:25], 1):
        p = r.get('params', {})
        f.write(f"{i:4} | {r['composite']:6.2f} | {r.get('profit_factor',0):5.2f} | {r.get('win_rate',0):5.1f} | {r.get('total_trades',0):4} | {r.get('net_pnl',0):10,.0f} | {r.get('max_drawdown_pct',0):4.1f}% | {p.get('slPoints',0):5.1f} | {p.get('slPointsWedThu',0):5.1f} | {p.get('minRangeTicks',0):6}\n")

# Also sort by pure PF and NetPnL for cross-reference
print("\n=== TOP 10 BY PURE PROFIT FACTOR ===")
by_pf = sorted([r for r in results if r.get('total_trades',0) >= 20],
               key=lambda r: r.get('profit_factor', 0), reverse=True)[:10]
for i, r in enumerate(by_pf, 1):
    p = r.get('params', {})
    print(f"  {i:2}. PF={r.get('profit_factor',0):5.2f} WR={r.get('win_rate',0):4.1f}% N={r.get('total_trades',0):3} PnL={r.get('net_pnl',0):>10,.0f} | SL={p.get('slPoints')} SL_WT={p.get('slPointsWedThu')} MR={p.get('minRangeTicks')}")

print("\n=== TOP 10 BY NET PROFIT ===")
by_pnl = sorted([r for r in results if r.get('total_trades',0) >= 20],
                key=lambda r: r.get('net_pnl', 0), reverse=True)[:10]
for i, r in enumerate(by_pnl, 1):
    p = r.get('params', {})
    print(f"  {i:2}. PnL={r.get('net_pnl',0):>10,.0f} PF={r.get('profit_factor',0):5.2f} WR={r.get('win_rate',0):4.1f}% N={r.get('total_trades',0):3} | SL={p.get('slPoints')} SL_WT={p.get('slPointsWedThu')} MR={p.get('minRangeTicks')}")

# Axis-level aggregation
print("\n=== AXIS ANALYSIS (avg PF by param value, N>=20 only) ===")
from collections import defaultdict
axes = ['slPoints', 'slPointsWedThu', 'minRangeTicks']
for axis in axes:
    groups = defaultdict(list)
    for r in results:
        if r.get('total_trades', 0) >= 20:
            groups[r['params'][axis]].append(r.get('profit_factor', 0))
    print(f"\n  {axis}:")
    for v in sorted(groups.keys()):
        vals = groups[v]
        avg = sum(vals) / len(vals) if vals else 0
        print(f"    {v:>5}: avg PF = {avg:5.2f}  (n_configs={len(vals)})")
