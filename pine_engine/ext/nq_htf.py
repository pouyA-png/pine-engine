"""nq.htf_* — hoehere Zeitebenen (HTF) aus M1-Bars (Paket P6).

Aggregation
  - Minuten-Zeitebenen (tf_minutes = 5, 15, 60, 240, ...): Kerzen sind an
    UTC-Epoch-Vielfachen ausgerichtet (Bucket = time_ms // (tf*60000)).
    60 = volle UTC-Stunden, 240 = 00/04/08/... UTC.
  - Tag: NY-Handelstag ab 18:00 America/New_York (Sommer-/Winterzeit korrekt).
  - Woche: Handelswoche ab Sonntag 18:00 NY.

Kein Lookahead
  - Eine Kerze gilt als abgeschlossen, sobald die M1-Bar verarbeitet ist, deren
    Ende (time + 1 min) das Kerzenende erreicht (z. B. 5-Min-Kerze 14:30 ist nach
    Schluss der M1-Bar 14:34 fertig) — oder spaetestens, wenn die erste Bar einer
    neuen Kerze kommt (Datenluecken, Tag/Woche: Wechsel um 18:00 NY).
  - offset >= 1: abgeschlossene Kerzen (1 = letzte abgeschlossene).
  - offset = 0: die Kerze, in der die aktuelle M1-Bar liegt, Stand "bis jetzt"
    (laufend; auf ihrer letzten M1-Bar identisch mit offset 1).

Die Aggregatoren liegen gemeinsam am ctx (je Zeitebene einer), werden ueber
einen Broker-Hook (on_bar_start, nur lesend) jede Bar gefuettert und beim
ersten Aufruf aus den eingebauten Series (max. 300 Bars) nachgefuellt.
Ohne Aufruf einer nq.htf_*-Funktion passiert nichts (kein Hook, kein Zustand).
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from pine_engine.runtime.ext import builtin, cur
from pine_engine.runtime.na import NA, is_na
from pine_engine.runtime.series import Series

NY_TZ = ZoneInfo('America/New_York')
BAR_MS = 60_000          # M1-Daten
MAX_KEEP = 5000          # abgeschlossene Kerzen je Zeitebene im Speicher
_DAY = 'D'
_WEEK = 'W'


# ── Zeit-Buckets ────────────────────────────────────────────────────────

def _session_date(ts_ms):
    """NY-Handelstag: ab 18:00 NY zaehlt schon der naechste Kalendertag."""
    ny = datetime.fromtimestamp(ts_ms / 1000, tz=NY_TZ)
    return (ny + timedelta(hours=6)).date()


def _ny_18_ms(d):
    """UTC-ms von 18:00 NY am Kalendertag d."""
    dt = datetime(d.year, d.month, d.day, 18, 0, tzinfo=NY_TZ)
    return int(dt.timestamp() * 1000)


def _bucket(tf, ts_ms):
    """-> (bucket_id, end_ms)"""
    if tf == _DAY:
        d = _session_date(ts_ms)
        return d, _ny_18_ms(d)
    if tf == _WEEK:
        d = _session_date(ts_ms)
        monday = d - timedelta(days=d.weekday())
        # Woche endet Sonntag 18:00 NY (Start der naechsten Handelswoche)
        return monday, _ny_18_ms(monday + timedelta(days=6))
    span = tf * 60_000
    b = ts_ms // span
    return b, (b + 1) * span


# ── Aggregator je Zeitebene ─────────────────────────────────────────────

class _Candle:
    __slots__ = ('bucket', 'end_ms', 'start_ms', 'o', 'h', 'l', 'c',
                 'first_idx', 'closed')

    def __init__(self, bucket, end_ms, ts, o, h, l, c, idx):
        self.bucket, self.end_ms, self.start_ms = bucket, end_ms, ts
        self.o, self.h, self.l, self.c = o, h, l, c
        self.first_idx = idx
        self.closed = False


class _Agg:
    def __init__(self, tf):
        self.tf = tf
        self.cur = None           # Kerze der aktuellen M1-Bar
        self.done = []            # abgeschlossene Kerzen (aelteste zuerst)
        self.n_done = 0           # Anzahl je abgeschlossener Kerzen (gesamt)
        self.count = 0            # Anzahl begonnener Kerzen (gesamt)
        self.last_idx = None

    def _close(self, c):
        if not c.closed:
            c.closed = True
            self.done.append(c)
            self.n_done += 1
            if len(self.done) > MAX_KEEP:
                del self.done[0]

    def feed(self, ts, o, h, l, c, idx):
        if self.last_idx is not None and idx <= self.last_idx:
            return
        self.last_idx = idx
        b, end = _bucket(self.tf, ts)
        k = self.cur
        if k is None or b != k.bucket:
            if k is not None:
                self._close(k)
            k = self.cur = _Candle(b, end, ts, o, h, l, c, idx)
            self.count += 1
        else:
            if h > k.h:
                k.h = h
            if l < k.l:
                k.l = l
            k.c = c
        if ts + BAR_MS >= k.end_ms:
            self._close(k)

    def candle(self, offset):
        if offset == 0:
            return self.cur
        if offset <= len(self.done):
            return self.done[-offset]
        return None


class _Feeder:
    """Broker-Hook: fuettert alle HTF-Aggregatoren mit jeder Bar (nur lesend)."""
    key = 'nq_htf'

    def __init__(self, aggs):
        self.aggs = aggs

    def on_bar_start(self, broker, bar):
        ts = _bar_ms(bar)
        for a in self.aggs.values():
            a.feed(ts, bar.open, bar.high, bar.low, bar.close, bar.bar_index)


def _bar_ms(bar):
    return int(bar.timestamp.timestamp() * 1000)   # wie loader.bar_timestamp_ms


def _parse_tf(tf):
    tf = cur(tf)
    if isinstance(tf, str):
        s = tf.strip().upper()
        if s in ('D', '1D'):
            return _DAY
        if s in ('W', '1W'):
            return _WEEK
        if s.isdigit():
            tf = int(s)
        else:
            raise ValueError(f'nq.htf: Zeitebene {tf!r} nicht unterstuetzt '
                             '(Minuten als Zahl, "D", "W")')
    if is_na(tf):
        raise ValueError('nq.htf: tf_minutes ist na')
    tf = int(tf)
    if tf < 1:
        raise ValueError(f'nq.htf: tf_minutes muss >= 1 sein, ist {tf}')
    return tf


def _agg(ctx, tf):
    """Aggregator zur Zeitebene holen (anlegen + nachfuellen) und aktuelle Bar einspeisen."""
    aggs = ctx.__dict__.get('_nq_htf_aggs')
    if aggs is None:
        aggs = ctx._nq_htf_aggs = {}
        ctx.strategy.broker.add_hook(_Feeder(aggs))
    a = aggs.get(tf)
    if a is None:
        a = aggs[tf] = _Agg(tf)
        t, o, h, l, c, bi = (getattr(ctx, n, None) for n in
                             ('time', 'open', 'high', 'low', 'close', 'bar_index'))
        if all(isinstance(s, Series) for s in (t, o, h, l, c, bi)):
            for k in range(len(t) - 1, 0, -1):     # aelteste zuerst, ohne aktuelle
                if not is_na(t[k]) and not is_na(bi[k]):
                    a.feed(int(t[k]), o[k], h[k], l[k], c[k], int(bi[k]))
    a.feed(ctx.bar_ts_ms, ctx.bar_open, ctx.bar_high, ctx.bar_low,
           ctx.bar_close, ctx.bar_idx)
    return a


def _off(offset):
    v = cur(offset)
    if is_na(v):
        raise ValueError('nq.htf: offset ist na')
    v = int(v)
    if v < 0:
        raise ValueError(f'nq.htf: offset muss >= 0 sein, ist {v}')
    return v


def _len(n):
    v = cur(n)
    if is_na(v) or int(v) < 1:
        raise ValueError(f'nq.htf: len muss >= 1 sein, ist {v}')
    return int(v)


def _field(ctx, tf, offset, attr):
    k = _agg(ctx, _parse_tf(tf)).candle(_off(offset))
    return NA if k is None else getattr(k, attr)


# ── 1. OHLC ─────────────────────────────────────────────────────────────

@builtin('nq.htf_open')
def htf_open(ctx, state, tf_minutes, offset=1):
    return _field(ctx, tf_minutes, offset, 'o')


@builtin('nq.htf_high')
def htf_high(ctx, state, tf_minutes, offset=1):
    return _field(ctx, tf_minutes, offset, 'h')


@builtin('nq.htf_low')
def htf_low(ctx, state, tf_minutes, offset=1):
    return _field(ctx, tf_minutes, offset, 'l')


@builtin('nq.htf_close')
def htf_close(ctx, state, tf_minutes, offset=1):
    return _field(ctx, tf_minutes, offset, 'c')


# ── 2. neue HTF-Kerze ───────────────────────────────────────────────────

@builtin('nq.htf_new_bar')
def htf_new_bar(ctx, state, tf_minutes):
    a = _agg(ctx, _parse_tf(tf_minutes))
    return a.cur is not None and a.cur.first_idx == ctx.bar_idx


# ── 3. EMA / ATR auf abgeschlossenen Kerzen ─────────────────────────────

def _new_done(state, a):
    """Seit dem letzten Aufruf an dieser Aufrufstelle abgeschlossene Kerzen."""
    seen = state.get('seen', 0)
    k = a.n_done - seen
    state['seen'] = a.n_done
    if k <= 0:
        return []
    return a.done[-k:] if k <= len(a.done) else list(a.done)


@builtin('nq.htf_ema')
def htf_ema(ctx, state, tf_minutes, length):
    a = _agg(ctx, _parse_tf(tf_minutes))
    n = _len(length)
    alpha = 2.0 / (n + 1)
    for k in _new_done(state, a):
        if 'ema' in state:
            state['ema'] = alpha * k.c + (1 - alpha) * state['ema']
        else:
            seed = state.setdefault('seed', [])
            seed.append(k.c)
            if len(seed) >= n:
                state['ema'] = sum(seed[-n:]) / n
    return state.get('ema', NA)


@builtin('nq.htf_atr')
def htf_atr(ctx, state, tf_minutes, length):
    a = _agg(ctx, _parse_tf(tf_minutes))
    n = _len(length)
    for k in _new_done(state, a):
        pc = state.get('pc')
        tr = (k.h - k.l) if pc is None else max(k.h - k.l, abs(k.h - pc), abs(k.l - pc))
        state['pc'] = k.c
        if 'atr' in state:
            state['atr'] = (tr + (n - 1) * state['atr']) / n
        else:
            seed = state.setdefault('seed', [])
            seed.append(tr)
            if len(seed) >= n:
                state['atr'] = sum(seed[-n:]) / n
    return state.get('atr', NA)


# ── 4./5. Tag und Woche ─────────────────────────────────────────────────

@builtin('nq.htf_day_open')
def htf_day_open(ctx, state, offset=1):
    return _field(ctx, _DAY, offset, 'o')


@builtin('nq.htf_day_high')
def htf_day_high(ctx, state, offset=1):
    return _field(ctx, _DAY, offset, 'h')


@builtin('nq.htf_day_low')
def htf_day_low(ctx, state, offset=1):
    return _field(ctx, _DAY, offset, 'l')


@builtin('nq.htf_day_close')
def htf_day_close(ctx, state, offset=1):
    return _field(ctx, _DAY, offset, 'c')


@builtin('nq.htf_week_high')
def htf_week_high(ctx, state, offset=1):
    return _field(ctx, _WEEK, offset, 'h')


@builtin('nq.htf_week_low')
def htf_week_low(ctx, state, offset=1):
    return _field(ctx, _WEEK, offset, 'l')


# ── 6. HTF-Bar-Index ────────────────────────────────────────────────────

@builtin('nq.htf_bar_index')
def htf_bar_index(ctx, state, tf_minutes):
    """0-basierter Index der aktuellen HTF-Kerze (ab der ersten gesehenen)."""
    return _agg(ctx, _parse_tf(tf_minutes)).count - 1


# ── 7. Highest / Lowest ueber abgeschlossene Kerzen ─────────────────────

def _extreme(ctx, tf, length, attr, fn):
    a = _agg(ctx, _parse_tf(tf))
    n = _len(length)
    if len(a.done) < n:
        return NA
    return fn(getattr(k, attr) for k in a.done[-n:])


@builtin('nq.htf_highest')
def htf_highest(ctx, state, tf_minutes, length):
    return _extreme(ctx, tf_minutes, length, 'h', max)


@builtin('nq.htf_lowest')
def htf_lowest(ctx, state, tf_minutes, length):
    return _extreme(ctx, tf_minutes, length, 'l', min)


# ── 8./10. Koerperrichtung und Spanne ───────────────────────────────────

@builtin('nq.htf_body_dir')
def htf_body_dir(ctx, state, tf_minutes, offset=1):
    k = _agg(ctx, _parse_tf(tf_minutes)).candle(_off(offset))
    if k is None:
        return NA
    return 1 if k.c > k.o else (-1 if k.c < k.o else 0)


@builtin('nq.htf_range')
def htf_range(ctx, state, tf_minutes, offset=1):
    k = _agg(ctx, _parse_tf(tf_minutes)).candle(_off(offset))
    return NA if k is None else k.h - k.l


# ── 9. request.security (nur open/high/low/close, lookahead off) ────────

@builtin('request.security', series_args=(2,))
def request_security(ctx, state, symbol, timeframe, expression, **kwargs):
    """Wert der letzten abgeschlossenen HTF-Kerze. symbol wird ignoriert
    (nur das geladene Instrument). Nur open/high/low/close als Ausdruck."""
    if kwargs.get('lookahead') not in (None, False, 'off', 'barmerge.lookahead_off'):
        raise ValueError('request.security: nur lookahead off unterstuetzt')
    attr = None
    for name, a in (('open', 'o'), ('high', 'h'), ('low', 'l'), ('close', 'c')):
        if expression is getattr(ctx, name, None):
            attr = a
            break
    if attr is None:
        raise ValueError('request.security: nur open/high/low/close als Ausdruck '
                         'unterstuetzt (sonst nq.htf_* nutzen)')
    return _field(ctx, timeframe, 1, attr)
