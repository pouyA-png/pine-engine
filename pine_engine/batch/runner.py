"""Batch runner — parallel parameter sweep across multiple datasets.

Usage:
    from pine_engine.batch.runner import BatchRunner
    from pine_engine.batch.param_grid import generate_grid, generate_range

    runner = BatchRunner(
        pine_path="trading_bot.pine",
        data_paths=["nq_2024.csv"],
        param_grid=generate_grid({
            "slPoints": generate_range(8, 14, 0.5),
            "pivotLeft": [1, 2, 3],
            "pivotRight": [1, 2, 3],
        })
    )
    results = runner.run(workers=4)
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import time
import csv

from pine_engine.engine import compile_pine, run_backtest, CompiledPine
from pine_engine.data.loader import load_bars_csv
from pine_engine.runtime.broker import Bar, ClosedTrade
from pine_engine.reporting.stats import compute_stats, format_stats


def _run_single(pine_source: str, bars_path: str, params: Dict,
                start_date: str = None, end_date: str = None,
                point_value: float = 1.0) -> Dict[str, Any]:
    """Run a single backtest (called in worker process)."""
    compiled = compile_pine(pine_source)
    bars = load_bars_csv(bars_path, start_date=start_date, end_date=end_date)
    trades = run_backtest(compiled, bars, params)
    stats = compute_stats(trades, point_value=point_value)
    stats['params'] = params
    stats['data_path'] = bars_path
    return stats


class BatchRunner:
    """Run parameter sweeps in parallel."""

    def __init__(self, pine_path: str, data_paths: List[str],
                 param_grid: List[Dict[str, Any]],
                 start_date: str = None, end_date: str = None,
                 point_value: float = 1.0):
        self.pine_path = pine_path
        self.data_paths = data_paths
        self.param_grid = param_grid
        self.start_date = start_date
        self.end_date = end_date
        self.point_value = point_value

        # Read source once (will be re-compiled in each worker)
        self.pine_source = Path(pine_path).read_text()

    def total_runs(self) -> int:
        return len(self.param_grid) * len(self.data_paths)

    def run(self, workers: int = 4, progress: bool = True) -> List[Dict[str, Any]]:
        """Run all parameter combinations in parallel.

        Args:
            workers: Number of parallel processes
            progress: Print progress updates

        Returns:
            List of stats dicts, one per run, sorted by profit_factor desc
        """
        total = self.total_runs()
        if progress:
            print(f"Starting batch: {len(self.param_grid)} param sets × "
                  f"{len(self.data_paths)} datasets = {total} runs")
            print(f"Workers: {workers}")

        results = []
        completed = 0
        t0 = time.time()

        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for params in self.param_grid:
                for data_path in self.data_paths:
                    future = pool.submit(
                        _run_single,
                        self.pine_source, data_path, params,
                        self.start_date, self.end_date, self.point_value)
                    futures[future] = (params, data_path)

            for future in as_completed(futures):
                completed += 1
                try:
                    stats = future.result()
                    results.append(stats)
                except Exception as e:
                    params, data_path = futures[future]
                    if progress:
                        print(f"  ERROR [{completed}/{total}]: {e} | params={params}")

                if progress and completed % max(1, total // 20) == 0:
                    elapsed = time.time() - t0
                    rate = completed / elapsed if elapsed > 0 else 0
                    eta = (total - completed) / rate if rate > 0 else 0
                    print(f"  [{completed}/{total}] {rate:.1f} runs/sec, ETA {eta:.0f}s")

        elapsed = time.time() - t0
        if progress:
            print(f"\nCompleted {total} runs in {elapsed:.1f}s "
                  f"({total/elapsed:.1f} runs/sec)")

        # Sort by profit factor descending
        results.sort(key=lambda r: r.get('profit_factor', 0), reverse=True)
        return results

    def run_sequential(self, progress: bool = True) -> List[Dict[str, Any]]:
        """Run all combinations sequentially (for debugging)."""
        total = self.total_runs()
        results = []
        compiled = compile_pine(self.pine_source)

        # Load data once per file
        data_cache = {}
        for dp in self.data_paths:
            if progress:
                print(f"Loading {dp}...")
            data_cache[dp] = load_bars_csv(dp, self.start_date, self.end_date)

        t0 = time.time()
        for i, params in enumerate(self.param_grid):
            for data_path in self.data_paths:
                bars = data_cache[data_path]
                trades = run_backtest(compiled, bars, params)
                stats = compute_stats(trades, point_value=self.point_value)
                stats['params'] = params
                stats['data_path'] = data_path
                results.append(stats)

                if progress and (i + 1) % max(1, len(self.param_grid) // 10) == 0:
                    elapsed = time.time() - t0
                    print(f"  [{i+1}/{len(self.param_grid)}] {elapsed:.1f}s")

        results.sort(key=lambda r: r.get('profit_factor', 0), reverse=True)

        if progress:
            elapsed = time.time() - t0
            print(f"Completed {total} runs in {elapsed:.1f}s")

        return results


def export_results(results: List[Dict[str, Any]], filepath: str):
    """Export batch results to CSV leaderboard."""
    if not results:
        return

    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Collect all param keys
    all_param_keys = set()
    for r in results:
        all_param_keys.update(r.get('params', {}).keys())
    param_keys = sorted(all_param_keys)

    stat_cols = ['total_trades', 'winners', 'losers', 'win_rate',
                 'profit_factor', 'net_pnl', 'gross_profit', 'gross_loss',
                 'avg_winner', 'avg_loser', 'expectancy',
                 'max_drawdown', 'max_drawdown_pct',
                 'trading_days', 'max_consec_wins', 'max_consec_losses',
                 'final_equity']

    with open(path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['rank'] + param_keys + stat_cols + ['data_path'])

        for rank, r in enumerate(results, 1):
            params = r.get('params', {})
            row = [rank]
            row.extend(params.get(k, '') for k in param_keys)
            row.extend(r.get(c, '') for c in stat_cols)
            row.append(r.get('data_path', ''))
            writer.writerow(row)


def print_leaderboard(results: List[Dict[str, Any]], top_n: int = 20):
    """Print top results as a formatted table."""
    if not results:
        print("No results.")
        return

    print(f"\n{'='*80}")
    print(f"TOP {min(top_n, len(results))} PARAMETER SETS (by Profit Factor)")
    print(f"{'='*80}")
    print(f"{'Rank':>4} | {'PF':>6} | {'WR%':>5} | {'Trades':>6} | {'Net PnL':>10} | {'MaxDD%':>6} | Params")
    print(f"{'-'*4}-+-{'-'*6}-+-{'-'*5}-+-{'-'*6}-+-{'-'*10}-+-{'-'*6}-+-{'-'*30}")

    for i, r in enumerate(results[:top_n], 1):
        pf = r.get('profit_factor', 0)
        wr = r.get('win_rate', 0)
        trades = r.get('total_trades', 0)
        net = r.get('net_pnl', 0)
        dd = r.get('max_drawdown_pct', 0)
        params = r.get('params', {})

        # Show only non-default params
        param_str = ', '.join(f'{k}={v}' for k, v in sorted(params.items()))
        if len(param_str) > 50:
            param_str = param_str[:47] + '...'

        print(f"{i:4} | {pf:6.2f} | {wr:5.1f} | {trades:6} | {net:10,.0f} | {dd:5.1f}% | {param_str}")
