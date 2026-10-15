"""P4 — Pine-Standardbibliothek: math / str / syminfo / timeframe / Zeit.

Nur Namen, die codegen.BUILTIN_MAP NICHT schon kennt (BUILTIN_MAP gewinnt
dort immer: hour minute dayofweek year month dayofmonth, math.abs/min/max/
round/floor/ceil/exp, na, str.tostring bleiben unberuehrt).

Instrument-Annahmen (NQ, M1): mintick 0.25 Punkte, 20 $/Punkt,
Exchange-Zeitzone America/New_York, Chart-Timeframe 1 Minute.

Bewusst NICHT implementiert:
  last_bar_index / last_bar_time / barstate.islast — sie kennen das Ende des
  Datensatzes schon auf Bar 0 (Lookahead). Eine Strategie, die davon abhaengt,
  verhielte sich im Backtest anders als live.
"""

from __future__ import annotations

import math
import random
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_EVEN, InvalidOperation

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo

from pine_engine.runtime.ext import builtin, variable, constant, cur, hist
from pine_engine.runtime.na import NA, is_na

EXCHANGE_TZ = 'America/New_York'
MINTICK = 0.25
POINTVALUE = 20.0
BAR_MS = 60_000          # Chart-Timeframe 1 Minute

# ─────────────────────────────── Konstanten ────────────────────────────────
constant('syminfo.mintick', MINTICK)
constant('syminfo.pointvalue', POINTVALUE)
constant('syminfo.ticker', 'NQ')
constant('syminfo.tickerid', 'CME_MINI:NQ1!')
constant('syminfo.timezone', EXCHANGE_TZ)
constant('syminfo.currency', 'USD')
constant('timeframe.period', '1')
constant('timeframe.multiplier', 1)
constant('timeframe.isintraday', True)
constant('timeframe.isminutes', True)
constant('timeframe.isseconds', False)
constant('timeframe.isdaily', False)
constant('timeframe.isweekly', False)
constant('timeframe.ismonthly', False)
constant('timeframe.isdwm', False)


def _num(x):
    x = cur(x)
    return NA if is_na(x) else x


# ─────────────────────────────── math.* ────────────────────────────────────
@builtin('math.sqrt')
def math_sqrt(ctx, state, x):
    x = _num(x)
    return NA if is_na(x) or x < 0 else math.sqrt(x)


@builtin('math.pow')
def math_pow(ctx, state, base, exponent):
    b, e = _num(base), _num(exponent)
    if is_na(b) or is_na(e):
        return NA
    try:
        r = math.pow(b, e)
    except (ValueError, OverflowError, ZeroDivisionError):
        return NA
    return r


@builtin('math.log')
def math_log(ctx, state, x):
    x = _num(x)
    return NA if is_na(x) or x <= 0 else math.log(x)


@builtin('math.log10')
def math_log10(ctx, state, x):
    x = _num(x)
    return NA if is_na(x) or x <= 0 else math.log10(x)


@builtin('math.sign')
def math_sign(ctx, state, x):
    x = _num(x)
    if is_na(x):
        return NA
    return 1.0 if x > 0 else (-1.0 if x < 0 else 0.0)


@builtin('math.avg')
def math_avg(ctx, state, *xs):
    vals = [_num(x) for x in xs]
    if not vals or any(is_na(v) for v in vals):
        return NA
    return sum(vals) / len(vals)


@builtin('math.sum', series_args=(0,))
def math_sum(ctx, state, source, length):
    """Gleitende Summe der letzten `length` Werte (inkl. aktueller Bar).
    na, solange weniger als `length` Werte vorliegen oder einer davon na ist."""
    n = int(length)
    buf = hist(state, 'src', cur(source), maxlen=max(n, 1))
    if n <= 0 or len(buf) < n:
        return NA
    win = buf[-n:]
    if any(is_na(v) for v in win):
        return NA
    return float(sum(win))


def _round_half_away(x, step):
    q = x / step
    q = math.floor(q + 0.5) if q >= 0 else -math.floor(-q + 0.5)
    # auf Tick-Raster, Float-Rauschen entfernen
    return round(q * step, 10)


@builtin('math.round_to_mintick')
def math_round_to_mintick(ctx, state, x):
    x = _num(x)
    return NA if is_na(x) else _round_half_away(x, MINTICK)


@builtin('math.random')
def math_random(ctx, state, min=0.0, max=1.0, seed=None):
    """Gleichverteilt in [min, max). Mit seed: reproduzierbare Folge je
    Aufrufstelle. Ohne seed ebenfalls deterministisch (Seed 0) — Backtests
    sollen reproduzierbar sein (Pine waere ohne seed zufaellig)."""
    rng = state.get('rng')
    if rng is None:
        s = 0 if seed is None or is_na(seed) else int(seed)
        rng = state['rng'] = random.Random(s)
    lo, hi = _num(min), _num(max)
    if is_na(lo) or is_na(hi):
        return NA
    return lo + (hi - lo) * rng.random()


# ─────────────────────────────── nz / fixnan ───────────────────────────────
@builtin('nz')
def nz(ctx, state, source, replacement=0):
    v = cur(source)
    return replacement if is_na(v) else v


@builtin('fixnan', series_args=(0,))
def fixnan(ctx, state, source):
    v = cur(source)
    if not is_na(v):
        state['last'] = v
        return v
    return state.get('last', NA)


# ─────────────────────────────── Zeit ──────────────────────────────────────
_OFFSET_RE = re.compile(r'^(?:GMT|UTC)\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?$', re.I)


def _tz(name):
    """Pine-Zeitzone: IANA-Name oder 'UTC'/'GMT' oder 'GMT+2'/'UTC-05:00'.
    (Pine: 'GMT+2' = UTC+2, keine POSIX-Umkehrung.)"""
    if name is None or is_na(name) or name == '':
        return ZoneInfo(EXCHANGE_TZ)
    s = str(name).strip()
    if s.upper() in ('UTC', 'GMT'):
        return timezone.utc
    m = _OFFSET_RE.match(s)
    if m:
        sign = 1 if m.group(1) == '+' else -1
        mins = int(m.group(2)) * 60 + int(m.group(3) or 0)
        return timezone(sign * timedelta(minutes=mins))
    return ZoneInfo(s)


def _dt(ts_ms, tz=None):
    return datetime.fromtimestamp(ts_ms / 1000, tz=_tz(tz))


@variable('time_close')
def time_close_var(ctx, state):
    """Ende der aktuellen Bar (= Oeffnung + 1 Minute), UTC ms."""
    return ctx.bar_ts_ms + BAR_MS


def _weekofyear(ts_ms, tz=None):
    if is_na(ts_ms):
        return NA
    return _dt(ts_ms, tz).isocalendar()[1]


def _second(ts_ms, tz=None):
    if is_na(ts_ms):
        return NA
    return _dt(ts_ms, tz).second


@variable('weekofyear')
def weekofyear_var(ctx, state):
    return _weekofyear(ctx.bar_ts_ms)


@builtin('weekofyear', series_args=(0,))
def weekofyear_fn(ctx, state, time, timezone=None):
    return _weekofyear(cur(time), timezone)


@variable('second')
def second_var(ctx, state):
    return _second(ctx.bar_ts_ms)


@builtin('second', series_args=(0,))
def second_fn(ctx, state, time, timezone=None):
    return _second(cur(time), timezone)


@builtin('timestamp')
def timestamp(ctx, state, *args, **kw):
    """timestamp(tz, y, m, d, hh, mm[, ss]) oder timestamp(y, m, d, hh, mm[, ss])
    (Exchange-TZ New York) oder timestamp("2026-01-05T09:30:00-05:00") -> UTC ms."""
    args = list(args)
    tz = kw.pop('timezone', None)
    if len(args) == 1 and isinstance(args[0], str) and tz is None:
        s = args[0].strip().replace('Z', '+00:00')
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(EXCHANGE_TZ))
        return int(dt.timestamp() * 1000)
    if args and isinstance(args[0], str):
        tz = args.pop(0)
    names = ('year', 'month', 'day', 'hour', 'minute', 'second')
    vals = args + [kw.pop(n) for n in names[len(args):] if n in kw]
    if any(is_na(v) for v in vals):
        return NA
    vals = [int(v) for v in vals]
    while len(vals) < 6:
        vals.append(0 if len(vals) >= 3 else 1)
    y, mo, d, hh, mi, ss = vals
    # Pine erlaubt Ueberlauf (z. B. Tag 32 / Monat 13) — normalisieren
    y += (mo - 1) // 12
    mo = (mo - 1) % 12 + 1
    naive = datetime(y, mo, 1) + timedelta(days=d - 1, hours=hh, minutes=mi, seconds=ss)
    dt = naive.replace(tzinfo=_tz(tz))
    return int(dt.timestamp() * 1000)


_SESS_RE = re.compile(r'^(\d{4})-(\d{4})$')


def _parse_session(sess: str):
    """'0930-1600', '1800-0930:23456', '0930-1200,1300-1600:23456' ->
    ([(start_min, end_min), ...], set_of_pine_days)."""
    s = str(sess).strip()
    days = set(range(1, 8))
    if ':' in s:
        s, d = s.split(':', 1)
        days = {int(c) for c in d.strip() if c.isdigit()}
    spans = []
    for part in s.split(','):
        m = _SESS_RE.match(part.strip())
        if not m:
            raise ValueError(f'time(): Session {sess!r} nicht im Format HHMM-HHMM')
        a, b = m.group(1), m.group(2)
        spans.append((int(a[:2]) * 60 + int(a[2:]), int(b[:2]) * 60 + int(b[2:])))
    return spans, days


def _pine_dow(dt):
    return dt.isoweekday() % 7 + 1          # 1=So ... 7=Sa


def in_session(ts_ms, sess, tz=None) -> bool:
    spans, days = _parse_session(sess)
    dt = _dt(ts_ms, tz)
    t = dt.hour * 60 + dt.minute
    for a, b in spans:
        if a == b:                          # 24h-Session
            inside, trade_day = True, dt
        elif a < b:
            inside, trade_day = a <= t < b, dt
        else:                               # Uebernacht: gehoert zum Folgetag
            if t >= a:
                inside, trade_day = True, dt + timedelta(days=1)
            else:
                inside, trade_day = t < b, dt
        if inside and _pine_dow(trade_day) in days:
            return True
    return False


def _tf_minutes(tf):
    if tf is None or is_na(tf) or str(tf).strip() in ('', '1'):
        return 1
    s = str(tf).strip()
    if s.isdigit() and 60 % int(s) == 0:
        return int(s)
    raise NotImplementedError(
        f'time(): Timeframe {tf!r} nicht unterstuetzt (nur Minuten, die 60 teilen)')


@builtin('time')
def time_fn(ctx, state, timeframe=None, session=None, timezone=None, bars_back=0):
    """Pine time(timeframe, session, timezone): Oeffnungszeit (UTC ms) der Bar
    des Timeframes, na wenn die aktuelle Bar ausserhalb der Session liegt."""
    if bars_back:
        raise NotImplementedError('time(): bars_back wird nicht unterstuetzt')
    n = _tf_minutes(timeframe)
    ts = ctx.bar_ts_ms
    if session is not None and not is_na(session) and str(session) != '':
        if not in_session(ts, session, timezone):
            return NA
    step = n * BAR_MS
    return ts - ts % step


# ─────────────────────────────── str.* ─────────────────────────────────────
def _fmt_num(x, pattern=None):
    if isinstance(x, bool):
        return 'true' if x else 'false'
    if is_na(x):
        return 'NaN'
    if pattern:                              # z. B. '#.##' / '0.00'
        frac = pattern.split('.', 1)[1] if '.' in pattern else ''
        mn = frac.count('0')
        mx = mn + frac.count('#')
        grouping = ',' in pattern
    else:                                    # Pine/Java-Default: '#,##0.###'
        mn, mx, grouping = 0, 3, True
    try:
        d = Decimal(repr(float(x))).quantize(Decimal(1).scaleb(-mx), rounding=ROUND_HALF_EVEN)
    except InvalidOperation:
        return str(x)
    s = f'{d:,.{mx}f}' if grouping else f'{d:.{mx}f}'
    if mx > mn and '.' in s:
        whole, frac_s = s.split('.')
        frac_s = frac_s.rstrip('0')
        if len(frac_s) < mn:
            frac_s = frac_s.ljust(mn, '0')
        s = whole + ('.' + frac_s if frac_s else '')
    if s.startswith('-') and float(d) == 0:
        s = s[1:]
    return s


def _fmt_val(v, pattern=None):
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return _fmt_num(v, pattern)
    return str(v)


_FMT_RE = re.compile(r'\{(\d+)(?:\s*,\s*number\s*(?:,\s*([#0.,]+))?)?\s*\}')


@builtin('str.format')
def str_format(ctx, state, fmt, *args):
    """'{0}'-Platzhalter (Java-MessageFormat-Teilmenge): Zahlen per Default
    mit Tausenderpunkt ',' und max. 3 Nachkommastellen; '{0,number,#.##}'."""
    def rep(m):
        i = int(m.group(1))
        if i >= len(args):
            return m.group(0)
        v = cur(args[i])
        return _fmt_val(v, m.group(2))
    return _FMT_RE.sub(rep, str(fmt))


def _s(x):
    return '' if x is None or (isinstance(x, float) and is_na(x)) else str(x)


@builtin('str.contains')
def str_contains(ctx, state, source, str):
    return _s(str) in _s(source)


@builtin('str.startswith')
def str_startswith(ctx, state, source, str):
    return _s(source).startswith(_s(str))


@builtin('str.endswith')
def str_endswith(ctx, state, source, str):
    return _s(source).endswith(_s(str))


@builtin('str.length')
def str_length(ctx, state, string):
    return len(_s(string))


@builtin('str.upper')
def str_upper(ctx, state, source):
    return _s(source).upper()


@builtin('str.lower')
def str_lower(ctx, state, source):
    return _s(source).lower()


@builtin('str.replace_all')
def str_replace_all(ctx, state, source, target, replacement):
    t = _s(target)
    return _s(source) if t == '' else _s(source).replace(t, _s(replacement))


@builtin('str.tonumber')
def str_tonumber(ctx, state, string):
    try:
        v = float(_s(string).strip())
    except ValueError:
        return NA
    return NA if math.isinf(v) else v
