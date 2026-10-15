"""P10 — Erweiterte Auswertung (Netto nach Kosten, R, Drawdown, Sharpe/Sortino,
Serien, Wochentag/Stunde, Monats-/Jahrestabelle, R-Verteilung, CSV-Export).

Stdlib only. Eingabe: Liste von ClosedTrade (wie run_backtest sie liefert).

Konventionen
  - Geld in $: Punkte x Menge x point_value (Default 20 $/Punkt, NQ).
  - Kosten: ``extra['cost_usd']`` (falls vorhanden) wird abgezogen -> Netto.
    Brutto = ohne Kosten. PF/WR/Erwartungswert/Drawdown/Sharpe laufen auf Netto.
  - R: ``extra['r0']`` = anfaengliches Risiko in Punkten je Kontrakt.
    R-Multiple = Netto-$ / (r0 x Menge x point_value). Trades ohne (gueltiges)
    r0 fehlen in den R-Kennzahlen; hat kein Trade r0, sind sie None.
  - Zeiten: naive Zeitstempel gelten als UTC; Handelstag/Wochentag/Stunde/
    Monat in New York (America/New_York). Wochentag/Stunde nach entry_time,
    Tage/Monate/Jahre nach exit_time (realisiert).
  - group_by_entry=True: Teilexits einer Position (gleiche entry_id +
    entry_time + side + entry_price) werden zu EINEM Trade zusammengefasst
    (Menge/PnL/Kosten summiert, exit_time = letzte Schliessung, mfe/mae = max).
"""

from __future__ import annotations

import csv
import math
from datetime import timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

_NY = ZoneInfo('America/New_York')
WEEKDAYS = ('Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So')
DEFAULT_R_EDGES = (-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0, 3.0)
EXTRA_COLS = ('exit_kind', 'cost_usd', 'mfe', 'mae', 'r0')


# ── Hilfen ────────────────────────────────────────────────────────────────

def _ny(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_NY)


def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def _pts(t) -> float:
    return (t.exit_price - t.entry_price) if t.side == 'long' else (t.entry_price - t.exit_price)


def records(trades, point_value: float = 20.0, group_by_entry: bool = False) -> List[dict]:
    """Normalisierte Trade-Datensaetze (ein dict je Trade bzw. Position)."""
    out: List[dict] = []
    for t in trades:
        ex = getattr(t, 'extra', None) or {}
        gross = _pts(t) * t.qty * point_value
        cost = _num(ex.get('cost_usd')) or 0.0
        out.append({
            'entry_id': t.entry_id, 'side': t.side, 'qty': t.qty,
            'entry_price': t.entry_price, 'exit_price': t.exit_price,
            'entry_time': t.entry_time, 'exit_time': t.exit_time,
            'entry_comment': t.entry_comment, 'exit_comment': t.exit_comment,
            'pnl_points': _pts(t) * t.qty,
            'gross': gross, 'cost': cost, 'net': gross - cost,
            'r0': _num(ex.get('r0')),
            'mfe': _num(ex.get('mfe')), 'mae': _num(ex.get('mae')),
            'extra': dict(ex), 'n_parts': 1,
        })
    if group_by_entry:
        groups: Dict[tuple, dict] = {}
        order: List[tuple] = []
        for r in out:
            k = (r['entry_id'], r['entry_time'], r['side'], r['entry_price'])
            g = groups.get(k)
            if g is None:
                groups[k] = dict(r, extra=dict(r['extra']))
                order.append(k)
                continue
            # Positions-Durchschnitt des Ausstiegs (mengengewichtet)
            q = g['qty'] + r['qty']
            g['exit_price'] = (g['exit_price'] * g['qty'] + r['exit_price'] * r['qty']) / q
            g['qty'] = q
            for f in ('pnl_points', 'gross', 'cost', 'net'):
                g[f] += r[f]
            if r['exit_time'] is not None and (g['exit_time'] is None or r['exit_time'] > g['exit_time']):
                g['exit_time'] = r['exit_time']
                g['exit_comment'] = r['exit_comment']
                if 'exit_kind' in r['extra']:      # Ausstiegsart = letzte Schliessung
                    g['extra']['exit_kind'] = r['extra']['exit_kind']
            for f in ('mfe', 'mae'):
                if r[f] is not None and (g[f] is None or r[f] > g[f]):
                    g[f] = r[f]
            if g['r0'] is None:
                g['r0'] = r['r0']
            g['n_parts'] += 1
            g['extra'].update({k2: v for k2, v in r['extra'].items() if k2 not in g['extra']})
            if 'cost_usd' in g['extra']:
                g['extra']['cost_usd'] = g['cost']
        out = [groups[k] for k in order]
    for r in out:
        r0 = r['r0']
        r['r'] = (r['net'] / (r0 * r['qty'] * point_value)
                  if r0 is not None and r0 > 0 and r['qty'] else None)
    return out


def _pf(values: Sequence[float]) -> float:
    gp = sum(v for v in values if v > 0)
    gl = -sum(v for v in values if v <= 0)
    if gl > 0:
        return gp / gl
    return float('inf') if gp > 0 else 0.0


def _streaks(values: Sequence[float]):
    mw = ml = cw = cl = 0
    for v in values:
        if v > 0:
            cw += 1
            cl = 0
            mw = max(mw, cw)
        else:
            cl += 1
            cw = 0
            ml = max(ml, cl)
    return mw, ml


def _drawdown(recs, initial_capital):
    """Max-DD ($, % vom Startkapital) und laengste DD-Dauer (Tage) auf Netto-Equity
    nach Schliessungen (sortiert nach exit_time)."""
    eq = initial_capital
    peak = initial_capital
    peak_time = None
    mdd = 0.0
    longest = 0.0
    in_dd_since = None
    last_time = None
    first_time = None
    for r in recs:
        tm = r['exit_time']
        if first_time is None:
            first_time = tm
        eq += r['net']
        last_time = tm
        if eq >= peak:
            if in_dd_since is not None and tm is not None:
                longest = max(longest, (tm - in_dd_since).total_seconds() / 86400.0)
            in_dd_since = None
            peak = eq
            peak_time = tm
        else:
            if in_dd_since is None:
                # DD beginnt am letzten Hoch (bzw. am ersten Trade, wenn das Hoch der Start ist)
                in_dd_since = peak_time if peak_time is not None else first_time
            mdd = max(mdd, peak - eq)
    if in_dd_since is not None and last_time is not None:
        longest = max(longest, (last_time - in_dd_since).total_seconds() / 86400.0)
    pct = mdd / initial_capital * 100.0 if initial_capital else 0.0
    return mdd, pct, longest


def _daily(recs):
    days: Dict[Any, float] = {}
    for r in recs:
        d = _ny(r['exit_time'])
        key = d.date() if d is not None else None
        days[key] = days.get(key, 0.0) + r['net']
    return days


def _sharpe_sortino(daily: Sequence[float], periods: int = 252):
    n = len(daily)
    if n < 2:
        return None, None
    mean = sum(daily) / n
    var = sum((x - mean) ** 2 for x in daily) / (n - 1)
    sd = math.sqrt(var)
    sharpe = mean / sd * math.sqrt(periods) if sd > 0 else None
    dd = math.sqrt(sum(min(0.0, x) ** 2 for x in daily) / n)
    sortino = mean / dd * math.sqrt(periods) if dd > 0 else None
    return sharpe, sortino


def _bucket(recs, keyfn):
    out: Dict[Any, dict] = {}
    for r in recs:
        k = keyfn(r)
        b = out.setdefault(k, {'n': 0, 'net': 0.0, 'wins': 0})
        b['n'] += 1
        b['net'] += r['net']
        b['wins'] += 1 if r['net'] > 0 else 0
    for b in out.values():
        b['win_rate'] = b['wins'] / b['n'] * 100.0 if b['n'] else 0.0
        b['avg'] = b['net'] / b['n'] if b['n'] else 0.0
    return dict(sorted(out.items(), key=lambda kv: (kv[0] is None, kv[0])))


def r_histogram(rs: Sequence[float], edges: Sequence[float] = DEFAULT_R_EDGES) -> List[dict]:
    """Buckets [a, b) mit offenem Rand links/rechts: (<e0), [e0,e1), ..., (>=eN)."""
    edges = sorted(edges)
    bounds = [-math.inf] + list(edges) + [math.inf]
    out = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        if a == -math.inf:
            label = f'<{b:g}'
        elif b == math.inf:
            label = f'>={a:g}'
        else:
            label = f'[{a:g},{b:g})'
        out.append({'bucket': label, 'lo': a, 'hi': b,
                    'n': sum(1 for x in rs if a <= x < b)})
    return out


# ── Hauptfunktion ─────────────────────────────────────────────────────────

def summary(trades, point_value: float = 20.0, initial_capital: float = 100000.0,
            group_by_entry: bool = False,
            r_edges: Sequence[float] = DEFAULT_R_EDGES) -> Dict[str, Any]:
    """Alle Kennzahlen als dict (Geld in $, R in R, Dauer in Tagen)."""
    recs = records(trades, point_value, group_by_entry)
    # chronologisch nach Schliessung (stabil; ohne exit_time ans Ende)
    recs = ([r for r in sorted((r for r in recs if r['exit_time'] is not None),
                               key=lambda r: r['exit_time'])]
            + [r for r in recs if r['exit_time'] is None])
    n = len(recs)
    nets = [r['net'] for r in recs]
    gross = [r['gross'] for r in recs]
    wins = [v for v in nets if v > 0]
    losses = [v for v in nets if v <= 0]
    rs = [r['r'] for r in recs if r['r'] is not None]
    mdd, mdd_pct, dd_days = _drawdown(recs, initial_capital)
    daily = _daily(recs)
    sharpe, sortino = _sharpe_sortino(list(daily.values()))
    mw, ml = _streaks(nets)
    s: Dict[str, Any] = {
        'count': n,
        'group_by_entry': group_by_entry,
        'gross_usd': sum(gross),
        'cost_usd': sum(r['cost'] for r in recs),
        'net_usd': sum(nets),
        'gross_profit_usd': sum(wins),
        'gross_loss_usd': -sum(losses),
        'profit_factor': _pf(nets) if n else 0.0,
        'profit_factor_gross': _pf(gross) if n else 0.0,
        'win_rate': len(wins) / n * 100.0 if n else 0.0,
        'winners': len(wins), 'losers': len(losses),
        'avg_win_usd': sum(wins) / len(wins) if wins else 0.0,
        'avg_loss_usd': sum(losses) / len(losses) if losses else 0.0,
        'expectancy_usd': sum(nets) / n if n else 0.0,
        'expectancy_r': sum(rs) / len(rs) if rs else None,
        'r_count': len(rs),
        'max_drawdown_usd': mdd,
        'max_drawdown_pct': mdd_pct,
        'max_drawdown_days': dd_days,
        'trading_days': len(daily),
        'sharpe_daily': sharpe,
        'sortino_daily': sortino,
        'max_consec_wins': mw,
        'max_consec_losses': ml,
        'by_weekday': _bucket(recs, lambda r: (_ny(r['entry_time']).weekday()
                                                if r['entry_time'] else None)),
        'by_hour': _bucket(recs, lambda r: (_ny(r['entry_time']).hour
                                             if r['entry_time'] else None)),
        'by_month': {k: v['net'] for k, v in _bucket(
            recs, lambda r: (_ny(r['exit_time']).strftime('%Y-%m')
                             if r['exit_time'] else None)).items()},
        'by_year': {k: v['net'] for k, v in _bucket(
            recs, lambda r: (_ny(r['exit_time']).year
                             if r['exit_time'] else None)).items()},
        'r_hist': r_histogram(rs, r_edges) if rs else None,
        'initial_capital': initial_capital,
        'point_value': point_value,
    }
    mfes = [r['mfe'] for r in recs if r['mfe'] is not None]
    maes = [r['mae'] for r in recs if r['mae'] is not None]
    s['avg_mfe_pts'] = sum(mfes) / len(mfes) if mfes else None
    s['avg_mae_pts'] = sum(maes) / len(maes) if maes else None
    return s


# ── Ausgabe ───────────────────────────────────────────────────────────────

def _f(v, fmt='{:,.2f}'):
    if v is None:
        return '-'
    if isinstance(v, float) and math.isinf(v):
        return 'inf'
    return fmt.format(v)


def format_summary(s: Dict[str, Any]) -> str:
    if not s['count']:
        return 'Keine Trades.'
    L = [
        f"Trades:            {s['count']}" + ('  (je Position)' if s['group_by_entry'] else ''),
        f"Netto $:           {_f(s['net_usd'])}   (Brutto {_f(s['gross_usd'])}, Kosten {_f(s['cost_usd'])})",
        f"Profit Factor:     {_f(s['profit_factor'])}   (brutto {_f(s['profit_factor_gross'])})",
        f"Win Rate:          {_f(s['win_rate'], '{:.1f}')} %   ({s['winners']} / {s['losers']})",
        f"Erwartung/Trade:   {_f(s['expectancy_usd'])} $   {_f(s['expectancy_r'], '{:+.3f}')} R  (R-Trades: {s['r_count']})",
        f"Max Drawdown:      {_f(s['max_drawdown_usd'])} $  ({_f(s['max_drawdown_pct'], '{:.2f}')} % vom Startkapital)",
        f"Laengste DD-Dauer: {_f(s['max_drawdown_days'], '{:.1f}')} Tage",
        f"Sharpe (Tag, x252): {_f(s['sharpe_daily'], '{:.2f}')}   Sortino: {_f(s['sortino_daily'], '{:.2f}')}   Handelstage: {s['trading_days']}",
        f"Serien:            max {s['max_consec_wins']} Gewinner / {s['max_consec_losses']} Verlierer in Folge",
    ]
    if s['avg_mfe_pts'] is not None:
        L.append(f"MFE/MAE (Mittel):  {_f(s['avg_mfe_pts'])} / {_f(s['avg_mae_pts'])} Punkte")
    L.append('\nWochentag (NY, Entry):  n | Netto $ | WR %')
    for k, b in s['by_weekday'].items():
        name = WEEKDAYS[k] if k is not None else '?'
        L.append(f"  {name:3} {b['n']:5d} | {b['net']:12,.2f} | {b['win_rate']:5.1f}")
    L.append('Stunde (NY, Entry):     n | Netto $ | WR %')
    for k, b in s['by_hour'].items():
        L.append(f"  {('%02d' % k) if k is not None else '?':3} {b['n']:5d} | {b['net']:12,.2f} | {b['win_rate']:5.1f}")
    # Jahr x Monat
    L.append('Monat/Jahr (NY, Exit, Netto $):')
    L.append('  Jahr ' + ''.join(f'{m:>10}' for m in range(1, 13)) + f"{'Summe':>12}")
    for y, tot in s['by_year'].items():
        if y is None:
            continue
        row = []
        for m in range(1, 13):
            v = s['by_month'].get(f'{y}-{m:02d}')
            row.append(f'{v:>10,.0f}' if v is not None else f"{'':>10}")
        L.append(f'  {y} ' + ''.join(row) + f'{tot:>12,.0f}')
    if s['r_hist']:
        L.append('R-Verteilung:')
        for b in s['r_hist']:
            L.append(f"  {b['bucket']:>12} {b['n']:5d}")
    return '\n'.join(L)


def export_trades(trades, filepath: str, point_value: float = 20.0,
                  group_by_entry: bool = False) -> int:
    """CSV je Trade inkl. extra-Spalten. Rueckgabe: Anzahl Zeilen."""
    recs = records(trades, point_value, group_by_entry)
    more = sorted({k for r in recs for k in r['extra']
                   if not str(k).startswith('_') and k not in EXTRA_COLS})
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    head = ['trade_num', 'entry_id', 'side', 'entry_time', 'exit_time',
            'entry_price', 'exit_price', 'qty', 'entry_comment', 'exit_comment',
            'pnl_points', 'gross_usd', 'net_usd', 'r_mult', 'n_parts'] + list(EXTRA_COLS) + more

    def cell(v):
        if v is None:
            return ''
        if isinstance(v, float):
            return f'{v:.4f}'.rstrip('0').rstrip('.') if v == v else ''
        return v

    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(head)
        for i, r in enumerate(recs, 1):
            ex = r['extra']
            row = [i, r['entry_id'], r['side'],
                   r['entry_time'].isoformat() if r['entry_time'] else '',
                   r['exit_time'].isoformat() if r['exit_time'] else '',
                   cell(r['entry_price']), cell(r['exit_price']), r['qty'],
                   r['entry_comment'], r['exit_comment'],
                   cell(r['pnl_points']), cell(r['gross']), cell(r['net']),
                   cell(r['r']), r['n_parts'],
                   cell(ex.get('exit_kind')), cell(r['cost'] if 'cost_usd' in ex else None),
                   cell(r['mfe']), cell(r['mae']), cell(r['r0'])]
            row += [cell(ex.get(k)) for k in more]
            w.writerow(row)
    return len(recs)
