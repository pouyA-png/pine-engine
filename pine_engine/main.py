#!/usr/bin/env python3
"""Pine Engine CLI — run Pine Script backtests from the command line.

Usage:
    python -m pine_engine.main run trading_bot.pine --data nq_1m.csv
    python -m pine_engine.main run trading_bot.pine --data nq_1m.csv --start 2024-01-01 --end 2024-12-31
    python -m pine_engine.main compile trading_bot.pine --output generated.py
    python -m pine_engine.main info trading_bot.pine
"""

import argparse
import sys
import time
from pathlib import Path

from pine_engine.engine import compile_pine, run_backtest
from pine_engine.data.loader import load_bars_csv


def cmd_run(args):
    """Run a backtest."""
    print(f"Compiling {args.pine}...")
    compiled = compile_pine(args.pine)
    print(f"  Inputs: {len(compiled.inputs)}")
    print(f"  Strategy: {compiled.strategy_settings.get('name', 'unnamed')}")
    print(f"  Default params: {len(compiled.get_default_params())}")

    print(f"\nLoading data from {args.data}...")
    bars = load_bars_csv(args.data, start_date=args.start, end_date=args.end)
    print(f"  Loaded {len(bars)} bars")
    if bars:
        print(f"  Range: {bars[0].timestamp} → {bars[-1].timestamp}")

    # Parse parameter overrides
    params = {}
    if args.param:
        for p in args.param:
            key, val = p.split('=', 1)
            try:
                params[key] = int(val)
            except ValueError:
                try:
                    params[key] = float(val)
                except ValueError:
                    params[key] = val

    print(f"\nRunning backtest ({len(bars)} bars)...")
    t0 = time.time()
    trades = run_backtest(compiled, bars, params if params else None)
    elapsed = time.time() - t0

    print(f"\n{'='*60}")
    print(f"RESULTS ({elapsed:.1f}s, {len(bars)/max(elapsed,0.001):.0f} bars/sec)")
    print(f"{'='*60}")
    print(f"Total trades: {len(trades)}")

    if trades:
        wins = [t for t in trades if _pnl(t) > 0]
        losses = [t for t in trades if _pnl(t) <= 0]
        total_win = sum(_pnl(t) for t in wins)
        total_loss = abs(sum(_pnl(t) for t in losses))
        pf = total_win / total_loss if total_loss > 0 else float('inf')
        wr = len(wins) / len(trades) * 100

        print(f"Winners: {len(wins)}, Losers: {len(losses)}")
        print(f"Win Rate: {wr:.1f}%")
        print(f"Profit Factor: {pf:.2f}")
        print(f"Gross Profit: {total_win:.2f}")
        print(f"Gross Loss: {total_loss:.2f}")
        print(f"Net Profit: {total_win - total_loss:.2f}")

        # Show last 10 trades
        print(f"\nLast {min(10, len(trades))} trades:")
        for t in trades[-10:]:
            pnl = _pnl(t)
            print(f"  {t.entry_time} | {t.side:5} | entry={t.entry_price:.2f} "
                  f"exit={t.exit_price:.2f} | {t.exit_comment:12} | PnL={pnl:+.2f}")


def _pnl(trade) -> float:
    """Calculate PnL for a trade."""
    if trade.side == 'long':
        return (trade.exit_price - trade.entry_price) * trade.qty
    else:
        return (trade.entry_price - trade.exit_price) * trade.qty


def cmd_compile(args):
    """Compile Pine to Python and optionally save."""
    print(f"Compiling {args.pine}...")
    compiled = compile_pine(args.pine)

    if args.output:
        Path(args.output).write_text(compiled.python_code)
        print(f"Generated Python saved to {args.output}")
        print(f"  {len(compiled.python_code)} chars, {compiled.python_code.count(chr(10))} lines")
    else:
        print(compiled.python_code)


def cmd_info(args):
    """Show info about a Pine file."""
    compiled = compile_pine(args.pine)
    print(f"File: {args.pine}")
    print(f"Inputs ({len(compiled.inputs)}):")
    for name, info in compiled.inputs.items():
        default = info.get('default', '?')
        itype = info.get('type', '?')
        print(f"  {name}: {itype} = {default}")
    print(f"\nStrategy settings:")
    for k, v in compiled.strategy_settings.items():
        print(f"  {k}: {v}")


def main():
    parser = argparse.ArgumentParser(description="Pine Script v5 Backtesting Engine")
    sub = parser.add_subparsers(dest='command')

    # run command
    run_p = sub.add_parser('run', help='Run a backtest')
    run_p.add_argument('pine', help='Path to .pine file')
    run_p.add_argument('--data', required=True, help='Path to CSV data file')
    run_p.add_argument('--start', help='Start date YYYY-MM-DD')
    run_p.add_argument('--end', help='End date YYYY-MM-DD')
    run_p.add_argument('--param', action='append', help='Parameter override: key=value')

    # compile command
    comp_p = sub.add_parser('compile', help='Compile Pine to Python')
    comp_p.add_argument('pine', help='Path to .pine file')
    comp_p.add_argument('--output', '-o', help='Output Python file')

    # info command
    info_p = sub.add_parser('info', help='Show Pine file info')
    info_p.add_argument('pine', help='Path to .pine file')

    args = parser.parse_args()

    if args.command == 'run':
        cmd_run(args)
    elif args.command == 'compile':
        cmd_compile(args)
    elif args.command == 'info':
        cmd_info(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
