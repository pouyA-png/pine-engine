"""strategy.*-Kennzahlen als Pine-Variablen (Paket P1c).

Liest ausschliesslich den Zustand von ``ctx.strategy.broker`` — keine Hooks,
keine Aenderung an Orders/Fills. Ohne Aufruf dieser Namen aendert sich kein
Backtest.

Geldwerte in $ (Pine-Standard: Kontowaehrung) = Punkte x Menge x Punktwert
(``ctx.strategy._point_value``, Default 20 $/Punkt). Keine Kosten/Kommission.
Jede (Teil-)Schliessung ist ein eigener geschlossener Trade (wie im Broker).

Zeiten in ms wie Pine ``time`` (gleiche Umrechnung wie data.loader.bar_timestamp_ms).
Handelstag fuer nq.day_netprofit = New-York-Kalendertag der exit_time
(naive Zeitstempel gelten als UTC).
"""

from __future__ import annotations
from datetime import timezone
from zoneinfo import ZoneInfo

from pine_engine.runtime.ext import builtin, variable, cur
from pine_engine.runtime.na import NA, is_na

_NY = ZoneInfo('America/New_York')
_STATE_KEY = '__strategy_vars__'   # gemeinsamer Cache je ctx (in ctx.ext_states)


# ── Helfer ──────────────────────────────────────────────────────────────

def _pv(ctx) -> float:
    return float(getattr(ctx.strategy, '_point_value', 20.0))


def _pts(side, entry, exit_, qty) -> float:
    d = (exit_ - entry) if side == 'long' else (entry - exit_)
    return d * qty


def _ms(dt):
    if dt is None:
        return NA
    return int(dt.timestamp() * 1000)


def _ny_date(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_NY).date()


def _idx(k):
    if is_na(k):
        return None
    try:
        return int(cur(k))
    except (TypeError, ValueError):
        return None


def _shared(ctx) -> dict:
    """Gemeinsamer, inkrementeller Cache der realisierten Kennzahlen."""
    st = ctx.ext_states.get(_STATE_KEY)
    if st is None:
        st = ctx.ext_states[_STATE_KEY] = {
            'n': 0, 'net': 0.0, 'gp': 0.0, 'gl': 0.0,
            'win': 0, 'loss': 0, 'even': 0,
            'peak': 0.0, 'trough': 0.0, 'mdd': 0.0, 'mru': 0.0,
            'day': {}, 'ts2idx': {},
        }
    # Bar-Zeit -> bar_index merken (fuer entry_bar_index jenseits der Series-Lookback)
    if ctx.bar_ts_ms:
        st['ts2idx'][ctx.bar_ts_ms] = ctx.bar_idx
    trades = ctx.strategy.broker.closed_trades
    if len(trades) < st['n']:            # Broker neu -> Cache neu
        ctx.ext_states.pop(_STATE_KEY, None)
        return _shared(ctx)
    pv = _pv(ctx)
    for t in trades[st['n']:]:
        p = _pts(t.side, t.entry_price, t.exit_price, t.qty) * pv
        st['net'] += p
        if p > 0:
            st['gp'] += p
            st['win'] += 1
        elif p < 0:
            st['gl'] += -p
            st['loss'] += 1
        else:
            st['even'] += 1
        eq = st['net']
        st['peak'] = max(st['peak'], eq)
        st['trough'] = min(st['trough'], eq)
        st['mdd'] = max(st['mdd'], st['peak'] - eq)
        st['mru'] = max(st['mru'], eq - st['trough'])
        d = _ny_date(t.exit_time)
        st['day'][d] = st['day'].get(d, 0.0) + p
    st['n'] = len(trades)
    return st


def _open_list(ctx):
    return [t for t in ctx.strategy.broker.open_trades.values() if t.remaining_qty > 0]


def _open_at(ctx, k):
    i = _idx(k)
    trades = list(ctx.strategy.broker.open_trades.values())
    if i is None or not (0 <= i < len(trades)):
        return None
    return trades[i]


def _closed_at(ctx, k):
    i = _idx(k)
    trades = ctx.strategy.broker.closed_trades
    if i is None or not (0 <= i < len(trades)):
        return None
    return trades[i]


# ── Position ───────────────────────────────────────────────────────────

@variable('strategy.position_size')
def position_size(ctx, state):
    """Netto-Restmenge offener Trades: long +, short −, flat 0 (Kontrakte)."""
    return sum(t.remaining_qty if t.side == 'long' else -t.remaining_qty
               for t in _open_list(ctx))


@variable('strategy.position_avg_price')
def position_avg_price(ctx, state):
    """Mengengewichteter Einstiegspreis aller offenen Restmengen; flat -> na."""
    ts = _open_list(ctx)
    q = sum(t.remaining_qty for t in ts)
    if q <= 0:
        return NA
    return sum(t.entry_price * t.remaining_qty for t in ts) / q


@variable('strategy.openprofit')
def openprofit(ctx, state):
    """Unrealisierter PnL aller offenen Restmengen zum aktuellen Close ($)."""
    c = ctx.bar_close
    return sum(_pts(t.side, t.entry_price, c, t.remaining_qty)
               for t in _open_list(ctx)) * _pv(ctx)


# ── Realisierte Kennzahlen ─────────────────────────────────────────────

@variable('strategy.netprofit')
def netprofit(ctx, state):
    return _shared(ctx)['net']


@variable('strategy.grossprofit')
def grossprofit(ctx, state):
    return _shared(ctx)['gp']


@variable('strategy.grossloss')
def grossloss(ctx, state):
    """Summe der Verluste als positive Zahl ($) — wie Pine."""
    return _shared(ctx)['gl']


@variable('strategy.wintrades')
def wintrades(ctx, state):
    return _shared(ctx)['win']


@variable('strategy.losstrades')
def losstrades(ctx, state):
    return _shared(ctx)['loss']


@variable('strategy.eventrades')
def eventrades(ctx, state):
    return _shared(ctx)['even']


@variable('strategy.max_drawdown')
def max_drawdown(ctx, state):
    """Groesster Rueckgang der realisierten Equity vom Hoch ($, positiv)."""
    return _shared(ctx)['mdd']


@variable('strategy.max_runup')
def max_runup(ctx, state):
    """Groesster Anstieg der realisierten Equity vom Tief ($, positiv)."""
    return _shared(ctx)['mru']


@variable('strategy.initial_capital')
def initial_capital(ctx, state):
    return float(ctx.strategy._initial_capital)


@variable('strategy.closedtrades.first_index')
def closedtrades_first_index(ctx, state):
    """Index des aeltesten geschlossenen Trades (hier immer 0, nichts wird verworfen)."""
    return 0


@variable('nq.day_netprofit')
def day_netprofit(ctx, state):
    """Realisierter PnL ($) des heutigen NY-Kalendertags (nach exit_time)."""
    st = _shared(ctx)
    today = _ny_date(ctx.strategy.broker._current_bar_time)
    return st['day'].get(today, 0.0)


# ── strategy.opentrades.* ──────────────────────────────────────────────

@builtin('strategy.opentrades.size')
def opentrades_size(ctx, state, k):
    t = _open_at(ctx, k)
    if t is None:
        return NA
    return t.remaining_qty if t.side == 'long' else -t.remaining_qty


@builtin('strategy.opentrades.entry_time')
def opentrades_entry_time(ctx, state, k):
    t = _open_at(ctx, k)
    return NA if t is None else _ms(t.entry_time)


@builtin('strategy.opentrades.entry_bar_index')
def opentrades_entry_bar_index(ctx, state, k):
    """bar_index der Fuellbar, abgeleitet aus entry_time (kein Broker-Hook).

    Suche: trade.extra['entry_bar_index'] -> Series ctx.time/ctx.bar_index
    (letzte 300 Bars) -> eigene ts->bar_index-Tabelle (nur Bars, in denen
    irgendein strategy_vars-Name ausgewertet wurde) -> na.
    """
    t = _open_at(ctx, k)
    if t is None:
        return NA
    if 'entry_bar_index' in t.extra:
        return t.extra['entry_bar_index']
    ms = _ms(t.entry_time)
    if is_na(ms):
        return NA
    ts_s = getattr(ctx, 'time', None)
    bi_s = getattr(ctx, 'bar_index', None)
    if ts_s is not None and bi_s is not None:
        for off in range(len(ts_s)):
            v = ts_s[off]
            if v == ms:
                return bi_s[off]
            if not is_na(v) and v < ms:
                break
    return _shared(ctx)['ts2idx'].get(ms, NA)


# ── strategy.closedtrades.* ────────────────────────────────────────────

@builtin('strategy.closedtrades.entry_price')
def closedtrades_entry_price(ctx, state, k):
    t = _closed_at(ctx, k)
    return NA if t is None else t.entry_price


@builtin('strategy.closedtrades.exit_price')
def closedtrades_exit_price(ctx, state, k):
    t = _closed_at(ctx, k)
    return NA if t is None else t.exit_price


@builtin('strategy.closedtrades.entry_time')
def closedtrades_entry_time(ctx, state, k):
    t = _closed_at(ctx, k)
    return NA if t is None else _ms(t.entry_time)


@builtin('strategy.closedtrades.exit_time')
def closedtrades_exit_time(ctx, state, k):
    t = _closed_at(ctx, k)
    return NA if t is None else _ms(t.exit_time)


@builtin('strategy.closedtrades.max_runup')
def closedtrades_max_runup(ctx, state, k):
    """extra['mfe'] (Punkte, positiv) x qty x Punktwert in $; ohne MFE-Plugin na."""
    t = _closed_at(ctx, k)
    if t is None or t.extra.get('mfe') is None:
        return NA
    return abs(float(t.extra['mfe'])) * t.qty * _pv(ctx)


@builtin('strategy.closedtrades.max_drawdown')
def closedtrades_max_drawdown(ctx, state, k):
    """extra['mae'] (Punkte, positiv) x qty x Punktwert in $; ohne MAE-Plugin na."""
    t = _closed_at(ctx, k)
    if t is None or t.extra.get('mae') is None:
        return NA
    return abs(float(t.extra['mae'])) * t.qty * _pv(ctx)
