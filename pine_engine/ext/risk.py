"""nq.risk_* — Risiko- und Kontoregeln (FTMO-Stil), Paket P8.

Alle Regeln leben in EINEM Broker-Hook (key ``nq.risk``). Jeder Pine-Aufruf
(``nq.risk_daily_loss(1000)`` usw.) legt den Hook bei Bedarf an und setzt nur
seinen Grenzwert — idempotent, darf jede Bar erneut aufgerufen werden (letzter
Wert gilt). Ohne Aufruf existiert kein Hook -> Backtest byte-identisch.

Geld: $ = Punkte x qty x Punktwert (ctx.strategy._point_value, NQ = 20).
Realisierte Trades zaehlen abzueglich ``ClosedTrade.extra['cost_usd']``
(setzt der Kosten-Agent, falls aktiv). Die Abrechnung passiert "lazy" beim
naechsten Bar-Start, damit Kosten-Hooks, die nach uns in on_close laufen,
schon verbucht sind.

Handelstag: Standard ``Europe/Prague``, Wechsel 00:00 Ortszeit (so rechnet FTMO
den Tagesverlust). Alternative per ``nq.risk_timezone("America/New_York", 18)``
= CME-Handelstag mit Wechsel 18:00 NY. Naive Bar-Zeitstempel gelten als UTC.

Kein Lookahead: Entscheidungen in Bar t (on_bar_start/allow_entry) nutzen nur
Trades bis Ende Bar t-1 und als Markierung fuer offene Positionen den Close von
Bar t-1. Zwangsschliessungen fuellen zum Open von Bar t.
"""

from __future__ import annotations
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from pine_engine.runtime.broker import BrokerHook, ClosedTrade
from pine_engine.runtime.ext import builtin, variable, cur
from pine_engine.runtime.na import NA, is_na

HOOK_KEY = 'nq.risk'
_TZ_CACHE: dict = {}


def _zone(name):
    z = _TZ_CACHE.get(name)
    if z is None:
        z = _TZ_CACHE[name] = ZoneInfo(name)
    return z


def _num(x):
    v = cur(x)
    if v is None or is_na(v):
        return None
    return float(v)


class RiskHook(BrokerHook):
    key = HOOK_KEY

    def __init__(self, point_value: float = 20.0):
        self.pv = float(point_value)
        self.tz = 'Europe/Prague'
        self.rollover_hour = 0
        # Regeln (None = aus)
        self.daily_loss = None
        self.daily_loss_hard = None
        self.daily_target = None
        self.max_trades_day = None
        self.max_losses_row = None
        self.cooldown_min = None
        self.max_open = None
        self.total_loss = None
        # Zustand
        self._n_synced = 0                 # schon verbuchte closed_trades
        self.realized_day: dict = {}       # Tag -> $ (netto Kosten)
        self.realized_total = 0.0
        self._pos_acc: dict = {}           # (entry_id, entry_time) -> [pnl$, last_exit]
        self.fills_day: dict = {}          # Tag -> gefuellte Entries
        self.loss_row = 0
        self.loss_row_day = None
        self.cooldown_until = None         # datetime (Bar-Zeitbasis)
        self.blocked_days: dict = {}       # Tag -> Grund
        self.hard_days: set = set()        # Tage mit Zwangsschliessung
        self.total_blocked = False
        self.last_close = None             # Close der zuletzt fertigen Bar
        self.forced_closes = 0

    # ── Zeit ──
    def day_key(self, ts: datetime):
        if ts is None:
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        loc = ts.astimezone(_zone(self.tz))
        shift = (24 - int(self.rollover_hour)) % 24
        return (loc + timedelta(hours=shift)).date()

    # ── Geld ──
    def _trade_usd(self, ct: ClosedTrade) -> float:
        d = (ct.exit_price - ct.entry_price) if ct.side == 'long' \
            else (ct.entry_price - ct.exit_price)
        usd = d * ct.qty * self.pv
        cost = (ct.extra or {}).get('cost_usd')
        if cost is not None and not is_na(cost):
            usd -= float(cost)
        return usd

    def floating(self, broker, mark) -> float:
        if mark is None or is_na(mark):
            return 0.0
        tot = 0.0
        for t in broker.open_trades.values():
            if t.remaining_qty <= 0:
                continue
            d = (mark - t.entry_price) if t.side == 'long' else (t.entry_price - mark)
            tot += d * t.remaining_qty * self.pv
        return tot

    # ── Abrechnung ──
    def sync(self, broker):
        cts = broker.closed_trades
        for ct in cts[self._n_synced:]:
            usd = self._trade_usd(ct)
            day = self.day_key(ct.exit_time)
            self.realized_day[day] = self.realized_day.get(day, 0.0) + usd
            self.realized_total += usd
            k = (ct.entry_id, ct.entry_time)
            acc = self._pos_acc.setdefault(k, [0.0, None])
            acc[0] += usd
            acc[1] = ct.exit_time
        self._n_synced = len(cts)
        # Positionen, die komplett zu sind -> Ergebnis je Position finalisieren
        done = []
        for k, (usd, last_exit) in self._pos_acc.items():
            ot = broker.open_trades.get(k[0])
            if ot is None or ot.entry_time != k[1] or ot.remaining_qty <= 0:
                done.append((last_exit or datetime.min, k, usd))
        done.sort(key=lambda x: x[0])
        for last_exit, k, usd in done:
            del self._pos_acc[k]
            day = self.day_key(last_exit) if last_exit != datetime.min else None
            if usd < 0:
                if day != self.loss_row_day:
                    self.loss_row, self.loss_row_day = 0, day
                self.loss_row += 1
                if self.cooldown_min and last_exit != datetime.min:
                    until = last_exit + timedelta(minutes=float(self.cooldown_min))
                    if self.cooldown_until is None or until > self.cooldown_until:
                        self.cooldown_until = until
            else:
                self.loss_row, self.loss_row_day = 0, day

    def evaluate(self, broker, today, mark) -> bool:
        """Regeln pruefen, Sperren setzen. True = heute (oder dauerhaft) gesperrt."""
        if self.total_blocked:
            return True
        r_day = self.realized_day.get(today, 0.0)
        need_float = self.daily_loss_hard is not None or self.total_loss is not None
        flt = self.floating(broker, mark) if need_float else 0.0
        reason = None
        if self.daily_loss is not None and r_day <= -self.daily_loss:
            reason = 'daily_loss'
        if self.daily_loss_hard is not None and r_day + flt <= -self.daily_loss_hard:
            reason = 'daily_loss_hard'
            self.hard_days.add(today)
        if self.daily_target is not None and r_day >= self.daily_target:
            reason = reason or 'daily_target'
        if self.max_trades_day is not None and self.fills_day.get(today, 0) >= self.max_trades_day:
            reason = reason or 'max_trades_day'
        if (self.max_losses_row is not None and self.loss_row_day == today
                and self.loss_row >= self.max_losses_row):
            reason = reason or 'max_losses_row'
        if self.total_loss is not None and self.realized_total + flt <= -self.total_loss:
            self.total_blocked = True
            return True
        if reason is not None and today not in self.blocked_days:
            self.blocked_days[today] = reason
        return today in self.blocked_days

    # ── Hook-Methoden ──
    def on_bar_start(self, broker, bar):
        today = self.day_key(bar.timestamp)
        self.sync(broker)
        blocked = self.evaluate(broker, today, self.last_close)
        if blocked:
            broker.pending_orders.clear()
        if (self.total_blocked or today in self.hard_days) and broker.open_trades:
            self._flatten(broker, bar,
                          'RISK_TOTAL' if self.total_blocked else 'RISK_DAILY_HARD')

    def _flatten(self, broker, bar, comment):
        for eid, t in list(broker.open_trades.items()):
            if t.remaining_qty > 0:
                broker.record_close(ClosedTrade(
                    entry_id=t.entry_id, side=t.side, qty=t.remaining_qty,
                    entry_price=t.entry_price, exit_price=bar.open,
                    entry_comment=t.entry_comment, exit_comment=comment,
                    entry_time=t.entry_time, exit_time=bar.timestamp))
                t.remaining_qty = 0
                self.forced_closes += 1
            del broker.open_trades[eid]
            for xid in [x for x, s in broker.exit_orders.items() if s['from_entry'] == eid]:
                broker.exit_orders.pop(xid, None)

    def allow_entry(self, broker, order, bar):
        today = self.day_key(bar.timestamp)
        if self.total_blocked or today in self.blocked_days:
            return False
        if self.cooldown_until is not None and bar.timestamp < self.cooldown_until:
            return False
        if self.max_open is not None and len(broker.open_trades) >= self.max_open:
            return False
        if self.max_trades_day is not None and self.fills_day.get(today, 0) >= self.max_trades_day:
            return False
        return True

    def on_fill(self, broker, trade, bar):
        d = self.day_key(bar.timestamp)
        self.fills_day[d] = self.fills_day.get(d, 0) + 1

    def after_exits(self, broker, bar):
        self.last_close = bar.close


# ── Pine-Anbindung ──────────────────────────────────────────────────────

def _hook(ctx) -> RiskHook:
    b = ctx.strategy.broker
    h = b.get_hook(HOOK_KEY)
    if h is None:
        h = b.add_hook(RiskHook(getattr(ctx.strategy, '_point_value', 20.0)))
        h.last_close = ctx.bar_close
    return h


def _bar_dt(ctx):
    # Bar-Zeitstempel wie ihn der Broker sieht (naiv = UTC); ctx.bar_ts_ms
    # interpretiert naive Zeiten in der lokalen Zone und wird hier nicht benutzt.
    ts = ctx.strategy.broker._current_bar_time
    return ts if ts is not None else datetime.fromtimestamp(ctx.bar_ts_ms / 1000.0, tz=timezone.utc)


def _setter(attr, as_int=False):
    def fn(ctx, state, value):
        v = _num(value)
        h = _hook(ctx)
        if v is None or v <= 0:
            setattr(h, attr, None)          # na / 0 = Regel aus
        else:
            setattr(h, attr, int(v) if as_int else v)
        return True
    return fn


builtin('nq.risk_daily_loss')(_setter('daily_loss'))
builtin('nq.risk_daily_loss_hard')(_setter('daily_loss_hard'))
builtin('nq.risk_daily_target')(_setter('daily_target'))
builtin('nq.risk_max_trades_day')(_setter('max_trades_day', as_int=True))
builtin('nq.risk_max_losses_row')(_setter('max_losses_row', as_int=True))
builtin('nq.risk_cooldown')(_setter('cooldown_min'))
builtin('nq.risk_max_open')(_setter('max_open', as_int=True))
builtin('nq.risk_total_loss')(_setter('total_loss'))


@builtin('nq.risk_timezone')
def nq_risk_timezone(ctx, state, tz='Europe/Prague', rollover_hour=NA):
    """Handelstag-Definition: Zeitzone + Stunde des Tageswechsels (Ortszeit).
    Ohne rollover_hour: 18 fuer America/New_York, sonst 0."""
    h = _hook(ctx)
    tz = str(cur(tz))
    _zone(tz)   # wirft bei unbekannter Zone
    r = _num(rollover_hour)
    if r is None:
        r = 18 if tz == 'America/New_York' else 0
    h.tz, h.rollover_hour = tz, int(r) % 24
    return True


@builtin('nq.risk_qty')
def nq_risk_qty(ctx, state, risk_usd, entry, stop):
    """Kontrakte fuer ein $-Risiko: floor(risk / (|entry-stop| x Punktwert)), min 0."""
    r, e, s = _num(risk_usd), _num(entry), _num(stop)
    if r is None or e is None or s is None:
        return NA
    dist = abs(e - s)
    pv = float(getattr(ctx.strategy, '_point_value', 20.0))
    if dist <= 0 or pv <= 0 or r <= 0:
        return 0
    return max(0, int(math.floor(r / (dist * pv) + 1e-9)))


@variable('nq.risk_blocked')
def nq_risk_blocked(ctx, state):
    """true, wenn ab der naechsten Bar keine neuen Entries erlaubt sind
    (Tages- oder Dauersperre). Stand: Ende der aktuellen Bar."""
    h = ctx.strategy.broker.get_hook(HOOK_KEY)
    if h is None:
        return False
    b = ctx.strategy.broker
    h.sync(b)
    return bool(h.evaluate(b, h.day_key(_bar_dt(ctx)), ctx.bar_close))


@variable('nq.risk_day_pnl')
def nq_risk_day_pnl(ctx, state):
    """Tages-PnL in $: realisiert (netto Kosten) + offen zum aktuellen Close."""
    h = _hook(ctx)
    b = ctx.strategy.broker
    h.sync(b)
    today = h.day_key(_bar_dt(ctx))
    return h.realized_day.get(today, 0.0) + h.floating(b, ctx.bar_close)
