"""Trade statistics — PF, WR, DD, Sharpe, equity curve, FTMO metrics."""

from __future__ import annotations
from typing import List, Dict, Any
from pine_engine.runtime.broker import ClosedTrade


def compute_stats(trades: List[ClosedTrade], point_value: float = 1.0,
                  initial_capital: float = 100000.0) -> Dict[str, Any]:
    """Compute comprehensive trade statistics.

    Args:
        trades: List of ClosedTrade objects
        point_value: Dollar value per point (NQ=$20, ES=$50, CFD=varies)
        initial_capital: Starting account balance

    Returns:
        Dictionary of statistics
    """
    if not trades:
        return {'total_trades': 0, 'net_pnl': 0.0, 'profit_factor': 0.0}

    pnls = []
    for t in trades:
        if t.side == 'long':
            pnl = (t.exit_price - t.entry_price) * t.qty * point_value
        else:
            pnl = (t.entry_price - t.exit_price) * t.qty * point_value
        pnls.append(pnl)

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    # Equity curve
    equity = [initial_capital]
    for p in pnls:
        equity.append(equity[-1] + p)

    # Max drawdown
    peak = initial_capital
    max_dd = 0.0
    max_dd_pct = 0.0
    for eq in equity:
        if eq > peak:
            peak = eq
        dd = peak - eq
        dd_pct = dd / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd_pct

    # Daily PnL (group by date)
    daily_pnl = {}
    for t, pnl in zip(trades, pnls):
        if t.exit_time:
            day = t.exit_time.strftime('%Y-%m-%d')
        else:
            day = 'unknown'
        daily_pnl[day] = daily_pnl.get(day, 0.0) + pnl

    worst_day = min(daily_pnl.values()) if daily_pnl else 0.0
    best_day = max(daily_pnl.values()) if daily_pnl else 0.0
    trading_days = len(daily_pnl)

    # Consecutive wins/losses
    max_consec_wins = 0
    max_consec_losses = 0
    curr_wins = 0
    curr_losses = 0
    for p in pnls:
        if p > 0:
            curr_wins += 1
            curr_losses = 0
            max_consec_wins = max(max_consec_wins, curr_wins)
        else:
            curr_losses += 1
            curr_wins = 0
            max_consec_losses = max(max_consec_losses, curr_losses)

    return {
        'total_trades': len(trades),
        'winners': len(wins),
        'losers': len(losses),
        'win_rate': len(wins) / len(trades) * 100 if trades else 0,
        'profit_factor': gross_profit / gross_loss if gross_loss > 0 else float('inf'),
        'gross_profit': gross_profit,
        'gross_loss': gross_loss,
        'net_pnl': gross_profit - gross_loss,
        'avg_winner': gross_profit / len(wins) if wins else 0,
        'avg_loser': gross_loss / len(losses) if losses else 0,
        'largest_winner': max(wins) if wins else 0,
        'largest_loser': min(losses) if losses else 0,  # Most negative
        'expectancy': (gross_profit - gross_loss) / len(trades) if trades else 0,
        'max_drawdown': max_dd,
        'max_drawdown_pct': max_dd_pct,
        'worst_day': worst_day,
        'best_day': best_day,
        'trading_days': trading_days,
        'max_consec_wins': max_consec_wins,
        'max_consec_losses': max_consec_losses,
        'equity_curve': equity,
        'final_equity': equity[-1],
    }


def format_stats(stats: Dict[str, Any]) -> str:
    """Format statistics for display."""
    if stats['total_trades'] == 0:
        return "No trades."

    lines = [
        f"Total Trades:      {stats['total_trades']}",
        f"Winners:           {stats['winners']}  |  Losers: {stats['losers']}",
        f"Win Rate:          {stats['win_rate']:.1f}%",
        f"Profit Factor:     {stats['profit_factor']:.2f}",
        f"Net P&L:           {stats['net_pnl']:,.2f}",
        f"Gross Profit:      {stats['gross_profit']:,.2f}",
        f"Gross Loss:        {stats['gross_loss']:,.2f}",
        f"Avg Winner:        {stats['avg_winner']:,.2f}",
        f"Avg Loser:         {stats['avg_loser']:,.2f}",
        f"Largest Winner:    {stats['largest_winner']:,.2f}",
        f"Expectancy:        {stats['expectancy']:,.2f}",
        f"Max Drawdown:      {stats['max_drawdown']:,.2f} ({stats['max_drawdown_pct']:.1f}%)",
        f"Best Day:          {stats['best_day']:,.2f}",
        f"Worst Day:         {stats['worst_day']:,.2f}",
        f"Trading Days:      {stats['trading_days']}",
        f"Max Consec Wins:   {stats['max_consec_wins']}",
        f"Max Consec Losses: {stats['max_consec_losses']}",
        f"Final Equity:      {stats['final_equity']:,.2f}",
    ]
    return '\n'.join(lines)
