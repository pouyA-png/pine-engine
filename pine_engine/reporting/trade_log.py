"""Trade log export — per-trade CSV output."""

from __future__ import annotations
from typing import List
from pathlib import Path
import csv

from pine_engine.runtime.broker import ClosedTrade


def export_trade_log(trades: List[ClosedTrade], filepath: str,
                     point_value: float = 1.0):
    """Export trades to CSV.

    Args:
        trades: List of ClosedTrade objects
        filepath: Output CSV path
        point_value: Dollar value per point
    """
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'trade_num', 'side', 'entry_time', 'exit_time',
            'entry_price', 'exit_price', 'qty',
            'entry_comment', 'exit_comment',
            'pnl_points', 'pnl_dollars'
        ])
        for i, t in enumerate(trades, 1):
            if t.side == 'long':
                pnl_pts = t.exit_price - t.entry_price
            else:
                pnl_pts = t.entry_price - t.exit_price
            pnl_usd = pnl_pts * t.qty * point_value

            writer.writerow([
                i, t.side,
                t.entry_time.isoformat() if t.entry_time else '',
                t.exit_time.isoformat() if t.exit_time else '',
                f'{t.entry_price:.2f}', f'{t.exit_price:.2f}', t.qty,
                t.entry_comment, t.exit_comment,
                f'{pnl_pts:.2f}', f'{pnl_usd:.2f}'
            ])


def load_tv_trade_log(filepath: str) -> List[dict]:
    """Load TradingView exported trade list (German or English headers).

    TV exports have entry+exit rows per trade. This consolidates them.
    """
    path = Path(filepath)
    trades = []

    with open(path, 'r', newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

        # Detect language from headers
        is_german = any('Typ' in h for h in headers)

        # Column mappings
        if is_german:
            col_num = 'Trade #'
            col_type = 'Typ'
            col_dt = 'Datum und Uhrzeit'
            col_signal = 'Signal'
            col_price = 'Preis USD'
            col_qty = 'Größe (Menge)'
            col_pnl = 'G&V netto USD'
        else:
            col_num = 'Trade #'
            col_type = 'Type'
            col_dt = 'Date/Time'
            col_signal = 'Signal'
            col_price = 'Price USD'
            col_qty = 'Contracts'
            col_pnl = 'Profit USD'

        # Group by trade number
        raw = {}
        for row in reader:
            num = row.get(col_num, '').strip()
            if not num:
                continue
            if num not in raw:
                raw[num] = {}

            typ = row.get(col_type, '')
            is_entry = 'Einstieg' in typ or 'Entry' in typ.lower()
            is_exit = 'Ausstieg' in typ or 'Exit' in typ.lower()

            if is_entry:
                raw[num]['entry_time'] = row.get(col_dt, '').strip()
                raw[num]['entry_signal'] = row.get(col_signal, '').strip()
                raw[num]['entry_price'] = float(row.get(col_price, '0').strip())
                raw[num]['qty'] = int(float(row.get(col_qty, '0').strip()))
                raw[num]['side'] = 'long' if 'Long' in typ else 'short'
            elif is_exit:
                raw[num]['exit_time'] = row.get(col_dt, '').strip()
                raw[num]['exit_signal'] = row.get(col_signal, '').strip()
                raw[num]['exit_price'] = float(row.get(col_price, '0').strip())
                try:
                    raw[num]['pnl'] = float(row.get(col_pnl, '0').strip())
                except ValueError:
                    raw[num]['pnl'] = 0.0

        # Build trade list
        for num in sorted(raw.keys(), key=lambda x: int(x)):
            t = raw[num]
            if 'entry_price' in t and 'exit_price' in t:
                trades.append(t)

    return trades
