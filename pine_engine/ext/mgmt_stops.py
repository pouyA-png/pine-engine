"""P7 Positionsmanagement: Break-even, Trailing, Zeit-Exits (nq.be_*, nq.trail_*, nq.time_*, nq.eod_*).

Alles laeuft ueber EINEN BrokerHook (key 'nq.mgmt_stops'). Jeder Pine-Aufruf setzt
nur Parameter im Hook (idempotent, erneuter Aufruf ersetzt die Parameter) und wirkt
ab der naechsten Bar (Pine-Aufruf in Bar t -> Hooks ab Bar t+1).

Begriffe
  Position     = OpenTrade des Brokers = eine Entry-Id (z. B. 'Long_078').
  Entry-Gruppe = alle Exit-Specs mit derselben from_entry-Id. Der Bot fuellt EINE
                 Order 'Long_078' (qty = 2 Haelften) und haengt zwei Exits daran
                 (ExL078_tp1 / ExL078_tp2, beide from_entry='Long_078'). TP1 ist also
                 eine Teilschliessung derselben Position; kein Praefix-Matching noetig.
  R            = |Entry - erster Stop| (r0), gemerkt beim ersten before_exits nach der
                 Fuellung aus der ersten Exit-Spec mit gueltigem Stop (trade.extra['r0']).
  Extrem       = bestes Hoch (long) / Tief (short) seit Fuellung, NUR aus abgeschlossenen
                 Bars (in after_exits gemerkt, in before_exits der Folgebar angewandt).
                 Fuellbar: nur max(Entry, Close) bzw. min(Entry, Close) — ihr Hoch/Tief
                 kann vor der Fuellung gelegen haben.

Kein Lookahead: Stops in Bar t nutzen nur Bars bis t-1. Stops werden nur verschaerft.
Das Skript registriert strategy.exit oft jede Bar neu -> der Stand liegt in
trade.extra['mgmt_stop'] und wird in before_exits erneut auf alle Specs gelegt.
"""

from __future__ import annotations
import math
from datetime import timezone
from zoneinfo import ZoneInfo

from pine_engine.runtime.broker import BrokerHook, ClosedTrade
from pine_engine.runtime.ext import builtin, cur
from pine_engine.runtime.na import is_na

HOOK_KEY = 'nq.mgmt_stops'
_NY = ZoneInfo('America/New_York')
_HL_MAX = 500


def _num(x):
    x = cur(x)
    if x is None or is_na(x):
        return None
    return float(x)


def _valid_stop(s):
    try:
        return s is not None and not is_na(s) and not math.isnan(s) and s > 0
    except TypeError:
        return False


class MgmtStopsHook(BrokerHook):
    key = HOOK_KEY

    def __init__(self):
        self.be = {}      # name -> params
        self.trail = {}
        self.time = {}
        self.eod = None   # (hh, mm)
        self._eod_done_day = None

    # ── Hilfen ──

    @staticmethod
    def _specs(broker, trade):
        return [(eid, s) for eid, s in broker.exit_orders.items()
                if s['from_entry'] == trade.entry_id]

    def _close(self, broker, trade, px, bar, comment, kind):
        ct = ClosedTrade(
            entry_id=trade.entry_id, side=trade.side, qty=trade.remaining_qty,
            entry_price=trade.entry_price, exit_price=px,
            entry_comment=trade.entry_comment, exit_comment=comment,
            entry_time=trade.entry_time, exit_time=bar.timestamp)
        ct.extra['exit_kind'] = kind
        broker.record_close(ct)
        trade.remaining_qty = 0
        broker.open_trades.pop(trade.entry_id, None)
        for eid, _ in self._specs(broker, trade):
            broker.exit_orders.pop(eid, None)

    @staticmethod
    def _eff_stop(broker, eid, s, tr):
        """Wirksamer Stop einer Spec (Preis-Stop oder loss in Ticks)."""
        fn = getattr(broker, '_exit_levels', None)
        if fn is not None:
            try:
                sl = fn(eid, s, tr)[1]
            except Exception:
                sl = s.get('stop')
        else:
            sl = s.get('stop')
        return sl if _valid_stop(sl) else None

    @staticmethod
    def _ny(bar):
        ts = bar.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(_NY)

    # ── EOD: vor jeder Fuellung der Bar ──

    def on_bar_start(self, broker, bar):
        if self.eod is None:
            return
        ny = self._ny(bar)
        if (ny.hour, ny.minute) < self.eod or self._eod_done_day == ny.date():
            return
        self._eod_done_day = ny.date()
        broker.pending_orders.clear()
        for tr in list(broker.open_trades.values()):
            if tr.remaining_qty > 0:
                self._close(broker, tr, bar.open, bar, 'EOD_FLAT', 'eod')
        broker.open_trades.clear()
        broker.exit_orders.clear()

    def allow_entry(self, broker, order, bar):
        # Nach dem EOD-Flat bis Ende des NY-Kalendertags keine neuen Fuellungen.
        if self.eod is not None and self._eod_done_day == self._ny(bar).date():
            return False
        return True

    def on_fill(self, broker, trade, bar):
        trade.extra.setdefault('mgmt_fill_bar', bar.bar_index)

    def adjust_exit(self, broker, trade, spec, px, is_tp, bar):
        if is_tp:
            trade.extra['mgmt_tp_done'] = True
        else:
            ms = trade.extra.get('mgmt_stop')
            if ms is not None and spec.get('stop') == ms and trade.extra.get('mgmt_src'):
                trade.extra['_mgmt_kind'] = trade.extra['mgmt_src']
        return px

    def on_close(self, broker, ct):
        tr = broker.open_trades.get(ct.entry_id)
        if tr is not None:
            if 'r0' in tr.extra:
                ct.extra.setdefault('r0', tr.extra['r0'])   # fuer R-Kennzahlen (metrics_ext)
            k = tr.extra.pop('_mgmt_kind', None)
            if k:
                ct.extra['exit_kind'] = k   # 'sl' des Brokers -> 'be' / 'trail'

    # ── Zeit-Exits + Stop-Nachzug ──

    def before_exits(self, broker, bar):
        for tr in list(broker.open_trades.values()):
            if tr.remaining_qty <= 0:
                continue
            x = tr.extra
            # Zeit-Exits zum Open dieser Bar (Entscheidung nur aus Zeit/Bar-Zaehler)
            ts = self.time.get('stop')
            if ts is not None and not x.get('mgmt_tp_done') and tr.entry_time is not None:
                if (bar.timestamp - tr.entry_time).total_seconds() >= ts * 60:
                    self._close(broker, tr, bar.open, bar, 'TIME_STOP', 'time')
                    continue
            mb = self.time.get('max_bars')
            if mb is not None and x.get('mgmt_bars_held', 0) >= mb:
                self._close(broker, tr, bar.open, bar, 'TIME_MAX_BARS', 'time')
                continue

            specs = self._specs(broker, tr)
            if 'r0' not in x:
                for eid, s in specs:
                    sl = self._eff_stop(broker, eid, s, tr)
                    if sl is not None:
                        r0 = abs(tr.entry_price - sl)
                        if r0 > 0:
                            x['r0'] = r0
                        break
            if not self.be and not self.trail:
                continue
            self._update_stop(tr)
            ms = x.get('mgmt_stop')
            if ms is None:
                continue
            long = tr.side == 'long'
            if not specs:
                # Position ohne eigene Exit-Spec: Stop-only-Spec des Hooks anlegen.
                broker.exit_orders['__mgmt_' + tr.entry_id] = {
                    'from_entry': tr.entry_id, 'qty': tr.remaining_qty,
                    'limit': None, 'stop': ms,
                    'comment_profit': 'MGMT', 'comment_loss': 'MGMT_STOP'}
                continue
            own = '__mgmt_' + tr.entry_id
            if own in broker.exit_orders and len(specs) > 1:
                broker.exit_orders.pop(own, None)
            for eid, s in specs:
                if eid == own and len(specs) > 1:
                    continue
                st = s.get('stop')
                if not _valid_stop(st):
                    s['stop'] = ms
                elif long and ms > st:
                    s['stop'] = ms
                elif (not long) and ms < st:
                    s['stop'] = ms

    def _update_stop(self, tr):
        x = tr.extra
        long = tr.side == 'long'
        sgn = 1.0 if long else -1.0
        e = tr.entry_price
        r0 = x.get('r0')
        ext = x.get('mgmt_ext')
        fav = (ext - e) * sgn if ext is not None else 0.0
        cands = []   # (stop, quelle)
        p = self.be.get('after_partial')
        if p is not None and x.get('mgmt_tp_done'):
            cands.append((e + sgn * p, 'be'))
        p = self.be.get('at_r')
        if p is not None and r0 and fav >= p[0] * r0:
            cands.append((e + sgn * p[1] * r0, 'be'))
        p = self.be.get('at_points')
        if p is not None and fav >= p[0]:
            cands.append((e + sgn * p[1], 'be'))
        p = self.trail.get('r')
        if p is not None and r0 and ext is not None and fav >= p[0] * r0:
            cands.append((ext - sgn * p[1] * r0, 'trail'))
        p = self.trail.get('points')
        if p is not None and ext is not None and fav >= p[0]:
            cands.append((ext - sgn * p[1], 'trail'))
        p = self.trail.get('step')
        if p is not None and r0 and p > 0:
            k = math.floor(fav / (p * r0) + 1e-9)
            if k >= 2:
                cands.append((e + sgn * (k - 1) * p * r0, 'trail'))
        p = self.trail.get('bars')
        if p is not None:
            hl = x.get('mgmt_hl', [])
            if len(hl) >= p:
                last = hl[-p:]
                lvl = min(l for _, l in last) if long else max(h for h, _ in last)
                cands.append((lvl, 'trail'))
        for lvl, src in cands:
            cur_s = x.get('mgmt_stop')
            if cur_s is None or (long and lvl > cur_s) or ((not long) and lvl < cur_s):
                x['mgmt_stop'] = lvl
                x['mgmt_src'] = src

    def after_exits(self, broker, bar):
        # Merken fuer die Folgebar: Extrem, Bar-Hoch/Tief, gehaltene Bars.
        for tr in broker.open_trades.values():
            if tr.remaining_qty <= 0:
                continue
            x = tr.extra
            fill_bar = (x.get('mgmt_fill_bar') == bar.bar_index
                        or ('mgmt_fill_bar' not in x and tr.entry_time == bar.timestamp))
            if tr.side == 'long':
                best = max(tr.entry_price, bar.close) if fill_bar else bar.high
                x['mgmt_ext'] = best if x.get('mgmt_ext') is None else max(x['mgmt_ext'], best)
            else:
                best = min(tr.entry_price, bar.close) if fill_bar else bar.low
                x['mgmt_ext'] = best if x.get('mgmt_ext') is None else min(x['mgmt_ext'], best)
            hl = x.setdefault('mgmt_hl', [])
            hl.append((bar.high, bar.low))
            if len(hl) > _HL_MAX:
                del hl[0]
            x['mgmt_bars_held'] = x.get('mgmt_bars_held', 0) + 1


def _hook(ctx) -> MgmtStopsHook:
    b = ctx.strategy.broker
    h = b.get_hook(HOOK_KEY)
    if h is None:
        h = b.add_hook(MgmtStopsHook())
    return h


# ── Pine-Funktionen ──

@builtin('nq.be_after_partial')
def be_after_partial(ctx, state, offset_points=0.0):
    _hook(ctx).be['after_partial'] = _num(offset_points) or 0.0
    return True


@builtin('nq.be_at_r')
def be_at_r(ctx, state, trigger_r, offset_r=0.0):
    _hook(ctx).be['at_r'] = (_num(trigger_r), _num(offset_r) or 0.0)
    return True


@builtin('nq.be_at_points')
def be_at_points(ctx, state, trigger_points, offset_points=0.0):
    _hook(ctx).be['at_points'] = (_num(trigger_points), _num(offset_points) or 0.0)
    return True


@builtin('nq.be_off')
def be_off(ctx, state):
    _hook(ctx).be.clear()
    return True


@builtin('nq.trail_r')
def trail_r(ctx, state, start_r, dist_r):
    _hook(ctx).trail['r'] = (_num(start_r), _num(dist_r))
    return True


@builtin('nq.trail_points')
def trail_points(ctx, state, start_points, dist_points):
    _hook(ctx).trail['points'] = (_num(start_points), _num(dist_points))
    return True


@builtin('nq.trail_step')
def trail_step(ctx, state, step_r=1.0):
    _hook(ctx).trail['step'] = _num(step_r)
    return True


@builtin('nq.trail_bars')
def trail_bars(ctx, state, n):
    _hook(ctx).trail['bars'] = max(1, int(_num(n)))
    return True


@builtin('nq.trail_off')
def trail_off(ctx, state):
    _hook(ctx).trail.clear()
    return True


@builtin('nq.time_stop')
def time_stop(ctx, state, minutes):
    _hook(ctx).time['stop'] = _num(minutes)
    return True


@builtin('nq.time_max_bars')
def time_max_bars(ctx, state, n):
    _hook(ctx).time['max_bars'] = int(_num(n))
    return True


@builtin('nq.time_off')
def time_off(ctx, state):
    _hook(ctx).time.clear()
    return True


@builtin('nq.eod_flat')
def eod_flat(ctx, state, hhmm_ny):
    v = int(_num(hhmm_ny))
    _hook(ctx).eod = (v // 100, v % 100)
    return True


@builtin('nq.eod_off')
def eod_off(ctx, state):
    _hook(ctx).eod = None
    return True
