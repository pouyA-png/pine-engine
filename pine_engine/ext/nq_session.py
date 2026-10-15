"""NQ-Session + Tageslevel (Paket P5, Namensraum nq.sess_/nq.rth_/nq.eth_/nq.pd_/nq.or_).

Zeitbasis: Bar-Zeitstempel sind UTC (naive Zeitstempel werden als UTC gelesen)
und werden nach America/New_York umgerechnet (zoneinfo, DST-sicher).

Handelstag: beginnt um 18:00 NY und endet um 18:00 NY des Folgetags. Der
Handelstag traegt das Datum des Kalendertags, an dessen Ende er schliesst
(Sonntag 18:00 NY -> Handelstag Montag).

  RTH  = 09:30-16:00 NY (Regular Trading Hours)
  ETH  = alles andere (Extended Trading Hours)
  Overnight (fuer nq.eth_high/low) = 18:00-09:30 NY des laufenden Handelstags

Kein Lookahead: alle Tageswerte enthalten nur Bars bis einschliesslich der
aktuellen Bar (Stand bei Bar-Schluss, wie Pine mit calc_on_every_tick=false).

Technik: EIN gemeinsamer Tracker je Backtest (``ctx._nq_sess``). Beim ersten
nq.*-Aufruf haengt er sich als Broker-Hook (key 'nq.sess', nur on_bar_start)
ein und sieht ab dann jede Bar — auch wenn spaetere Aufrufe nur bedingt laufen.
Bars VOR dem ersten Aufruf kennt er nicht (Aufrufe daher ab Bar 0, also
unbedingt auf oberster Ebene, platzieren). Ohne nq.*-Aufruf wird nichts
registriert -> Standardverhalten byte-identisch.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from pine_engine.runtime.ext import builtin, variable, cur
from pine_engine.runtime.na import NA, is_na

NY = ZoneInfo('America/New_York')
_DAY_START = 18 * 60          # 18:00 NY in Minuten
_RTH_START = 9 * 60 + 30      # 09:30
_RTH_END = 16 * 60            # 16:00


def _to_min(hhmm) -> int:
    """930 / '0930' / '09:30' -> Minuten seit Mitternacht."""
    if isinstance(hhmm, str):
        s = hhmm.strip().replace(':', '')
        v = int(s)
    else:
        v = int(hhmm)
    h, m = divmod(v, 100)
    if not (0 <= h <= 24 and 0 <= m < 60):
        raise ValueError(f'nq.sess: ungueltige Uhrzeit {hhmm!r} (HHMM erwartet)')
    return (h * 60 + m) % 1440


def _day_off(minute_of_day: int) -> int:
    """Minuten seit Handelstag-Beginn (18:00 NY)."""
    return (minute_of_day - _DAY_START) % 1440


class _Tracker:
    """Laufende Session-/Tageswerte, einmal pro Bar gefuettert."""

    key = 'nq.sess'   # Broker-Hook-Key

    def __init__(self):
        self.last_key = None          # (bar_index, ts) der zuletzt gefuetterten Bar
        self.last_ts = None
        self.interval_s = None        # kleinster beobachteter Bar-Abstand
        self.day = None               # Handelstag (date)
        self.day_index = -1
        self.first_bar = False
        self.new_rth = False
        self.bars_since_open = 0
        self.rth_bars = 0
        self.ny = None                # NY-datetime der aktuellen Bar
        self.minute = 0               # NY-Minute des Tages
        self.rth = False
        self.is_dst = False
        # heute
        self.rth_open = NA
        self.rth_high = NA
        self.rth_low = NA
        self.rth_close = NA
        self.eth_high = NA
        self.eth_low = NA
        self.or_bars = []             # [(offset_min ab 09:30, high, low)] heute RTH
        self.or_cache = {}            # minutes -> (hi, lo) sobald fertig
        # Vortag (letzter abgeschlossener RTH-Tag)
        self.pd_high = NA
        self.pd_low = NA
        self.pd_close = NA

    # Broker-Hook: jede Bar, vor Entries/Exits (Daten erst fuer execute_bar genutzt)
    def on_bar_start(self, broker, bar):
        self.feed(bar.timestamp, bar.open, bar.high, bar.low, bar.close, bar.bar_index)

    def feed(self, ts, o, h, l, c, bar_index):
        k = (bar_index, ts)
        if k == self.last_key:
            return
        self.last_key = k
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if self.last_ts is not None:
            d = (ts - self.last_ts).total_seconds()
            if d > 0 and (self.interval_s is None or d < self.interval_s):
                self.interval_s = d
        self.last_ts = ts

        ny = ts.astimezone(NY)
        self.ny = ny
        self.minute = ny.hour * 60 + ny.minute
        self.is_dst = bool(ny.dst())
        # Handelstag: ab 18:00 NY zaehlt der naechste Kalendertag
        day = (ny + timedelta(days=1)).date() if self.minute >= _DAY_START else ny.date()

        self.first_bar = day != self.day
        if self.first_bar:
            if self.day is not None and not is_na(self.rth_high):
                self.pd_high, self.pd_low, self.pd_close = self.rth_high, self.rth_low, self.rth_close
            self.day = day
            self.day_index += 1
            self.bars_since_open = 0
            self.rth_bars = 0
            self.rth_open = self.rth_high = self.rth_low = self.rth_close = NA
            self.eth_high = self.eth_low = NA
            self.or_bars = []
            self.or_cache = {}
        else:
            self.bars_since_open += 1

        self.rth = _RTH_START <= self.minute < _RTH_END
        self.new_rth = False
        if self.rth:
            if is_na(self.rth_open):
                self.new_rth = True
                self.rth_open = o
                self.rth_high, self.rth_low = h, l
                self.rth_bars = 0
            else:
                self.rth_high = max(self.rth_high, h)
                self.rth_low = min(self.rth_low, l)
                self.rth_bars += 1
            self.rth_close = c
            self.or_bars.append((self.minute - _RTH_START, h, l))
        elif self.minute >= _DAY_START or self.minute < _RTH_START:
            # Overnight 18:00-09:30
            self.eth_high = h if is_na(self.eth_high) else max(self.eth_high, h)
            self.eth_low = l if is_na(self.eth_low) else min(self.eth_low, l)

    def opening_range(self, minutes):
        m = int(minutes)
        if m <= 0 or not self.or_bars:
            return NA, NA
        hit = self.or_cache.get(m)
        if hit is not None:
            return hit
        # fertig, sobald die aktuelle Bar das Fensterende erreicht (Bar-Ende >= 09:30+m)
        step = (self.interval_s or 60.0) / 60.0
        cur_off = self.minute - _RTH_START
        if not self.rth and cur_off >= m:
            done = True
        else:
            done = self.rth and cur_off + step >= m
        if not done:
            return NA, NA
        inside = [(hh, ll) for off, hh, ll in self.or_bars if off < m]
        if not inside:
            return NA, NA
        res = (max(x[0] for x in inside), min(x[1] for x in inside))
        self.or_cache[m] = res
        return res


def _tr(ctx) -> _Tracker:
    t = getattr(ctx, '_nq_sess', None)
    broker = ctx.strategy.broker
    if t is None:
        t = _Tracker()
        ctx._nq_sess = t
        broker.add_hook(t)
    ts = broker._current_bar_time
    if ts is None:
        ts = datetime.fromtimestamp(ctx.bar_ts_ms / 1000.0, tz=timezone.utc)
    t.feed(ts, ctx.bar_open, ctx.bar_high, ctx.bar_low, ctx.bar_close, ctx.bar_idx)
    return t


# ── 1. Zeitfenster ─────────────────────────────────────────────────────────

@builtin('nq.sess_in')
def nq_sess_in(ctx, state, start_hhmm, end_hhmm=None):
    """True, wenn die Bar-Startzeit (NY) in [start, end) liegt; Uebernacht erlaubt.
    Auch als ein Argument: nq.sess_in("0930-1600")."""
    t = _tr(ctx)
    s = cur(start_hhmm)
    e = cur(end_hhmm) if end_hhmm is not None else None
    if e is None:
        if isinstance(s, str) and '-' in s:
            s, e = s.split('-', 1)
        else:
            raise ValueError('nq.sess_in braucht start und end (oder "HHMM-HHMM")')
    a, b = _to_min(s), _to_min(e)
    m = t.minute
    if a == b:
        return True
    if a < b:
        return a <= m < b
    return m >= a or m < b


# ── 2. RTH/ETH ─────────────────────────────────────────────────────────────

@variable('nq.rth')
def nq_rth(ctx, state):
    return _tr(ctx).rth


@variable('nq.eth')
def nq_eth(ctx, state):
    return not _tr(ctx).rth


# ── 3. Minuten seit Uhrzeit ────────────────────────────────────────────────

@builtin('nq.sess_minutes_since')
def nq_sess_minutes_since(ctx, state, hhmm):
    """Minuten seit hhmm (NY) im laufenden Handelstag (Start 18:00); na davor."""
    t = _tr(ctx)
    ref = _day_off(_to_min(cur(hhmm)))
    now = _day_off(t.minute)
    return now - ref if now >= ref else NA


# ── 4. RTH heute ───────────────────────────────────────────────────────────

@variable('nq.rth_open')
def nq_rth_open(ctx, state):
    return _tr(ctx).rth_open


@variable('nq.rth_high')
def nq_rth_high(ctx, state):
    return _tr(ctx).rth_high


@variable('nq.rth_low')
def nq_rth_low(ctx, state):
    return _tr(ctx).rth_low


@variable('nq.rth_bars_since_open')
def nq_rth_bars_since_open(ctx, state):
    t = _tr(ctx)
    return NA if is_na(t.rth_open) else t.rth_bars


# ── 5. Vortag (letzter abgeschlossener RTH-Tag) ────────────────────────────

@variable('nq.pd_high')
def nq_pd_high(ctx, state):
    return _tr(ctx).pd_high


@variable('nq.pd_low')
def nq_pd_low(ctx, state):
    return _tr(ctx).pd_low


@variable('nq.pd_close')
def nq_pd_close(ctx, state):
    return _tr(ctx).pd_close


# ── 6. Overnight ───────────────────────────────────────────────────────────

@variable('nq.eth_high')
def nq_eth_high(ctx, state):
    return _tr(ctx).eth_high


@variable('nq.eth_low')
def nq_eth_low(ctx, state):
    return _tr(ctx).eth_low


# ── 7. Opening Range ───────────────────────────────────────────────────────

@builtin('nq.or_high')
def nq_or_high(ctx, state, minutes):
    return _tr(ctx).opening_range(cur(minutes))[0]


@builtin('nq.or_low')
def nq_or_low(ctx, state, minutes):
    return _tr(ctx).opening_range(cur(minutes))[1]


# ── 8.-10. Tagesstruktur ───────────────────────────────────────────────────

@variable('nq.sess_first_bar')
def nq_sess_first_bar(ctx, state):
    return _tr(ctx).first_bar


@variable('nq.sess_new_rth')
def nq_sess_new_rth(ctx, state):
    return _tr(ctx).new_rth


@variable('nq.sess_day_index')
def nq_sess_day_index(ctx, state):
    return _tr(ctx).day_index


@variable('nq.sess_weekday')
def nq_sess_weekday(ctx, state):
    """Wochentag des Handelstags, 1=Mo..7=So (Sonntagabend -> 1=Mo)."""
    return _tr(ctx).day.isoweekday()


@variable('nq.sess_is_dst')
def nq_sess_is_dst(ctx, state):
    return _tr(ctx).is_dst


@variable('nq.sess_bars_since_open')
def nq_sess_bars_since_open(ctx, state):
    return _tr(ctx).bars_since_open
