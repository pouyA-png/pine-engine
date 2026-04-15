"""Example parameter sweep — template for your own strategies.

Usage:
    python scripts/example_sweep.py path/to/strategy.pine path/to/bars.csv

Edit the `grid` dict below to match the inputs your strategy exposes.
"""
import sys
import math
from pathlib import Path

from pine_engine.batch.runner import BatchRunner, export_results
from pine_engine.batch.param_grid import generate_grid


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    pine_path = sys.argv[1]
    data_path = sys.argv[2]
    out_dir = Path("output/example_sweep")
    out_dir.mkdir(parents=True, exist_ok=True)

    # ──────────────────────────────────────────────────────────────
    # Edit this grid to match your strategy's inputs.
    # Keys must match the Pine `input.*` variable names exactly.
    # ──────────────────────────────────────────────────────────────
    grid = generate_grid({
        "slPoints":      [8.0, 10.0, 12.0, 14.0],
        "pivotLeft":     [2, 3],
        "pivotRight":    [2, 3],
        "minRangeTicks": [16, 20, 24],
    })
    print(f"Grid size: {len(grid)}")

    runner = BatchRunner(
        pine_path=pine_path,
        data_paths=[data_path],
        param_grid=grid,
        # Optional date range:
        # start_date="2025-01-01",
        # end_date="2025-12-31",
        point_value=20.0,   # NQ=$20, ES=$50, MNQ=$2 — adjust for your instrument
    )

    results = runner.run(workers=4, progress=True)

    # Composite score: PF × sqrt(N), with minimum trade count gate
    for r in results:
        pf = r.get("profit_factor", 0) or 0
        n  = r.get("total_trades", 0) or 0
        exp = r.get("expectancy", 0) or 0
        r["composite"] = pf * math.sqrt(n) if (n >= 20 and exp > 0) else 0.0
    results.sort(key=lambda r: r["composite"], reverse=True)

    csv_path = out_dir / "leaderboard.csv"
    export_results(results, str(csv_path))
    print(f"\nLeaderboard saved: {csv_path}")

    # Print top 15
    print("\n" + "=" * 100)
    print(f"{'Rank':>4} | {'Comp':>6} | {'PF':>5} | {'WR%':>5} | {'N':>4} | {'NetPnL':>12} | {'Params'}")
    print("-" * 100)
    for i, r in enumerate(results[:15], 1):
        print(f"{i:4} | {r['composite']:6.2f} | {r.get('profit_factor',0):5.2f} | "
              f"{r.get('win_rate',0):5.1f} | {r.get('total_trades',0):4} | "
              f"{r.get('net_pnl',0):12,.0f} | {r.get('params', {})}")


if __name__ == "__main__":
    main()
