"""nq.cost_* / nq.fill_* — Handelskosten und realistische Fuellungen (Paket P9).

Umsetzung als EIN BrokerHook (key ``nq.costs``), der beim ersten Aufruf einer
der Funktionen registriert wird. Jeder Aufruf setzt nur einen Parameter
(idempotent: jede Bar erneut aufrufen ist unschaedlich). Ohne Aufruf ist der
Backtest byte-identisch.

Zwei Arten von Kosten:
  1. Verbuchte Kosten (Preise unveraendert): nq.cost_points, nq.cost_commission.
     Pro (Teil-)Schliessung in ClosedTrade.extra:
       extra['cost_points'] = Round-Turn-Kosten je Kontrakt in Punkten
                              (cost_points + commission_usd / Punktwert)
       extra['cost_usd']    = cost_points x qty x Punktwert (20 $/Punkt)
  2. Kosten im Preis (Fuellpreis wird adversativ verschoben): fill_slippage,
     fill_stop_slippage, fill_spread, fill_round_tick. Die Summe der
     Verschiebung je Kontrakt (Einstieg + Ausstieg, Punkte) steht informativ in
     extra['fill_adj_points'] — sie ist im Preis schon enthalten, NICHT in
     cost_usd.

Fuellarten (order.extra['kind'], Legacy strategy.order = 'limit'):
  - market/stop-Einstiege: Slippage immer.
  - limit/stoplimit-Einstiege: Slippage nur mit limits=true; fuellt der Broker
    zum Open jenseits des Limits (Gap), ist das marktfaehig -> Slippage, aber
    hoechstens bis zum Limit.
  - Ausstiege ueber adjust_exit: TP wie Limit (Gap -> hoechstens bis TP),
    SL/Trail = Stop (exit_pts + stop_pts).
  - Alle anderen Schliessungen (strategy.close/close_all, Reversal, Plugin-
    Flattening wie EOD/Risk) laufen nicht ueber adjust_exit; sie gelten als
    Marktfuellung und ihr Preis wird in on_close angepasst (Hooks, die VOR
    diesem Hook registriert wurden, sehen in ihrem on_close noch den
    unangepassten Preis).

Reihenfolge der Preisanpassung: Slippage -> Spread -> Tick-Rundung.
"""

from __future__ import annotations
import math

from pine_engine.runtime.ext import builtin, variable, cur
from pine_engine.runtime.na import is_na

TICK = 0.25
HOOK_KEY = 'nq.costs'


def _num(x, name, default=None):
    v = cur(x)
    if v is None or is_na(v):
        if default is not None:
            return default
        raise ValueError(f'{name}: Wert ist na')
    v = float(v)
    if v < 0:
        raise ValueError(f'{name}: Wert muss >= 0 sein, ist {v}')
    return v


def _flag(x) -> bool:
    v = cur(x)
    return bool(v) and not is_na(v)


def _valid_level(x) -> bool:
    if x is None:
        return False
    try:
        return not (math.isnan(x) or x <= 0)
    except TypeError:
        return False


class CostHook:
    """Broker-Plugin fuer Kosten + Fuellrealismus. Alle Parameter default 0/aus."""
    key = HOOK_KEY

    def __init__(self, point_value: float = 20.0):
        self.point_value = point_value
        self.cost_pts = 0.0          # Round-Turn je Kontrakt, Punkte
        self.commission_usd = 0.0    # Round-Turn je Kontrakt, $
        self.slip_entry = 0.0        # Punkte, adversativ
        self.slip_exit = 0.0         # Punkte, adversativ
        self.slip_limits = False     # Slippage auch auf Limit-Einstiege/TP
        self.stop_slip = 0.0         # Punkte, nur Stop-Ausloesungen
        self.half_spread = 0.0       # Punkte je Seite
        self.tt_entry_ticks = 0      # Trade-Through fuer Limit-Einstiege
        self.tt_tp_ticks = 0         # Trade-Through fuer TP-Limits
        self.round_tick = False
        # intern
        self._tp_orig = {}           # exit_id -> (spec, Original-Limit) waehrend der Bar
        self._in_exit = False        # naechster record_close kommt aus process_exits
        self._last_exit_adj = 0.0
        self._last_entry_adj = 0.0
        self._net_idx = 0
        self._net_sum = 0.0

    # ── Hilfen ──
    @staticmethod
    def _adverse(px, pts, side, is_entry):
        """Preis um pts verschlechtern (Long-Einstieg/Short-Ausstieg: hoeher)."""
        up = (side == 'long') == is_entry
        return px + pts if up else px - pts

    @staticmethod
    def _round_adverse(px, side, is_entry):
        up = (side == 'long') == is_entry
        q = px / TICK
        n = math.ceil(q - 1e-9) if up else math.floor(q + 1e-9)
        return n * TICK

    def _finish(self, px, side, is_entry):
        if self.half_spread:
            px = self._adverse(px, self.half_spread, side, is_entry)
        if self.round_tick:
            px = self._round_adverse(px, side, is_entry)
        return px

    # ── Einstiege ──
    @staticmethod
    def _kind(order):
        return order.extra.get('kind', 'limit')   # Legacy strategy.order = Limit

    def allow_entry(self, broker, order, bar):
        if not self.tt_entry_ticks or self._kind(order) != 'limit':
            return True
        d = self.tt_entry_ticks * TICK
        lim = order.limit_price
        if order.side == 'long':
            return bar.open <= lim or bar.low <= lim - d
        return bar.open >= lim or bar.high >= lim + d

    def adjust_fill(self, broker, order, px, bar):
        raw = px
        side = order.side
        kind = self._kind(order)
        if self.slip_entry:
            if kind in ('market', 'stop'):
                px = self._adverse(px, self.slip_entry, side, True)
            elif self.slip_limits:
                px = self._adverse(px, self.slip_entry, side, True)
            elif px != order.limit_price:
                # Limit/Stop-Limit marktfaehig zum Open: Slippage bis hoechstens zum Limit
                lim = order.limit_price
                px = self._adverse(px, self.slip_entry, side, True)
                px = min(px, lim) if side == 'long' else max(px, lim)
        px = self._finish(px, side, True)
        self._last_entry_adj = (px - raw) if side == 'long' else (raw - px)
        return px

    def on_fill(self, broker, trade, bar):
        trade.extra['nq_fill_adj_entry'] = self._last_entry_adj
        self._last_entry_adj = 0.0

    # ── TP-Trade-Through: TP waehrend der Pruefung um ticks nach aussen schieben ──
    def before_exits(self, broker, bar):
        self._tp_orig = {}
        if not self.tt_tp_ticks:
            return
        for eid, spec in broker.exit_orders.items():
            tr = broker.open_trades.get(spec.get('from_entry'))
            if tr is None:
                continue          # auch from_entry="" (Seite je Position) -> nicht verschoben
            mt = spec.get('mintick', TICK) or TICK
            d = self.tt_tp_ticks * mt
            lim, prof = spec.get('limit'), spec.get('profit')
            ok_l, ok_p = _valid_level(lim), _valid_level(prof)
            if not (ok_l or ok_p):
                continue
            self._tp_orig[eid] = (spec, lim, prof, d if tr.side == 'long' else -d)
            if ok_l:
                spec['limit'] = lim + (d if tr.side == 'long' else -d)
            if ok_p:
                spec['profit'] = prof + self.tt_tp_ticks

    def after_exits(self, broker, bar):
        for eid, (spec, lim, prof, _) in self._tp_orig.items():
            spec['limit'] = lim   # auch ausgeloeste (entfernte) Specs — harmlos
            if 'profit' in spec:
                spec['profit'] = prof
        self._tp_orig = {}

    def _tp_shift(self, spec):
        for s, _, _, sd in self._tp_orig.values():
            if s is spec:
                return sd
        return None

    # ── Ausstiege ──
    @staticmethod
    def _tp_level(broker, spec, trade):
        fn = getattr(broker, '_exit_levels', None)
        if fn is not None:
            try:
                return fn(None, spec, trade)[0]
            except Exception:
                pass
        lim = spec.get('limit')
        return lim if _valid_level(lim) else None

    def adjust_exit(self, broker, trade, spec, px, is_tp, bar):
        side = trade.side
        raw = px
        if is_tp:
            sd = self._tp_shift(spec) or 0.0
            gap = px == bar.open          # TP marktfaehig zum Open (besser als TP)
            if not gap:
                px -= sd                  # Fuellung zum echten TP (Trade-Through)
            raw = px   # Rueckstellung aufs echte TP ist keine Kostenverschiebung
            if self.slip_exit and (gap or self.slip_limits):
                px2 = self._adverse(px, self.slip_exit, side, False)
                if not self.slip_limits:  # Gap: hoechstens bis zum TP verschlechtern
                    tp = self._tp_level(broker, spec, trade)
                    if tp is not None:
                        tp -= sd
                        px2 = max(px2, tp) if side == 'long' else min(px2, tp)
                px = px2
        else:
            slip = self.slip_exit + self.stop_slip
            if slip:
                px = self._adverse(px, slip, side, False)
        px = self._finish(px, side, False)
        self._in_exit = True
        self._last_exit_adj = (raw - px) if side == 'long' else (px - raw)
        return px

    # ── Verbuchung ──
    def on_close(self, broker, ct):
        side = ct.side
        if self._in_exit:
            self._in_exit = False
            ex = self._last_exit_adj
        else:
            # strategy.close/close_all: Marktfuellung zum Close
            raw = ct.exit_price
            px = raw
            slip = self.slip_exit
            if slip:
                px = self._adverse(px, slip, side, False)
            px = self._finish(px, side, False)
            ct.exit_price = px
            ex = (raw - px) if side == 'long' else (px - raw)
        tr = broker.open_trades.get(ct.entry_id)
        adj_entry = tr.extra.get('nq_fill_adj_entry', 0.0) if tr is not None else 0.0
        cpts = self.cost_pts + self.commission_usd / self.point_value
        ct.extra['cost_points'] = cpts
        ct.extra['cost_usd'] = cpts * ct.qty * self.point_value
        ct.extra['fill_adj_points'] = adj_entry + ex


def _hook(ctx) -> CostHook:
    broker = ctx.strategy.broker
    h = broker.get_hook(HOOK_KEY)
    if h is None:
        pv = getattr(ctx.strategy, '_point_value', 20.0) or 20.0
        h = broker.add_hook(CostHook(point_value=pv))
    return h


# ── Pine-Funktionen ──────────────────────────────────────────────────────

@builtin('nq.cost_points')
def nq_cost_points(ctx, state, pts):
    """Round-Turn-Kosten je Kontrakt in Punkten (nur verbucht)."""
    v = _num(pts, 'nq.cost_points')
    _hook(ctx).cost_pts = v
    return v


@builtin('nq.cost_commission')
def nq_cost_commission(ctx, state, usd_per_contract):
    """Round-Turn-Kommission je Kontrakt in $ (nur verbucht)."""
    v = _num(usd_per_contract, 'nq.cost_commission')
    _hook(ctx).commission_usd = v
    return v


@builtin('nq.fill_slippage')
def nq_fill_slippage(ctx, state, entry_pts, exit_pts=0.0, limits=False):
    """Adverse Slippage in Punkten fuer marktfaehige Fuellungen (Stop, close,
    Gap-Fuellungen von Limits bis hoechstens zum Limit); limits=true auch auf
    Limit-Einstiege und TP-Fuellungen."""
    h = _hook(ctx)
    h.slip_entry = _num(entry_pts, 'nq.fill_slippage', 0.0)
    h.slip_exit = _num(exit_pts, 'nq.fill_slippage', 0.0)
    h.slip_limits = _flag(limits)
    return h.slip_entry + h.slip_exit


@builtin('nq.fill_stop_slippage')
def nq_fill_stop_slippage(ctx, state, pts):
    """Zusaetzliche adverse Slippage in Punkten nur bei Stop-Ausloesungen."""
    v = _num(pts, 'nq.fill_stop_slippage')
    _hook(ctx).stop_slip = v
    return v


@builtin('nq.fill_spread')
def nq_fill_spread(ctx, state, pts):
    """Spread in Punkten; je Fuellung (Ein- und Ausstieg) wird der halbe Spread
    adversativ auf den Preis gerechnet."""
    v = _num(pts, 'nq.fill_spread')
    _hook(ctx).half_spread = v / 2.0
    return v


@builtin('nq.fill_trade_through')
def nq_fill_trade_through(ctx, state, ticks):
    """Limit-Einstieg fuellt nur, wenn das Bar-Extrem das Limit um >= ticks
    (1 Tick = 0.25 Punkte) durchschreitet. Fuellpreis = Limit (Gap-Open: Open)."""
    v = int(_num(ticks, 'nq.fill_trade_through'))
    _hook(ctx).tt_entry_ticks = v
    return v


@builtin('nq.fill_tp_trade_through')
def nq_fill_tp_trade_through(ctx, state, ticks):
    """TP-Limit fuellt nur bei Durchschreiten um >= ticks; sonst kein TP in der Bar."""
    v = int(_num(ticks, 'nq.fill_tp_trade_through'))
    _hook(ctx).tt_tp_ticks = v
    return v


@builtin('nq.fill_round_tick')
def nq_fill_round_tick(ctx, state, on=True):
    """Fuellpreise adversativ auf 0.25 runden."""
    v = _flag(on)
    _hook(ctx).round_tick = v
    return v


@builtin('nq.cost_off')
def nq_cost_off(ctx, state):
    """Alle Kosten/Fuellregeln ab jetzt ausschalten (Hook entfernen)."""
    broker = ctx.strategy.broker
    broker.hooks = [h for h in broker.hooks if getattr(h, 'key', '') != HOOK_KEY]
    return True


@variable('nq.cost_net_pnl')
def nq_cost_net_pnl(ctx, state):
    """Realisierter Netto-PnL in $: Brutto (Preise inkl. Fuellanpassungen)
    minus extra['cost_usd'] aller geschlossenen Trades."""
    closed = ctx.strategy.broker.closed_trades
    pv = getattr(ctx.strategy, '_point_value', 20.0) or 20.0
    i = state.get('i', 0)
    s = state.get('s', 0.0)
    while i < len(closed):
        ct = closed[i]
        d = (ct.exit_price - ct.entry_price) if ct.side == 'long' \
            else (ct.entry_price - ct.exit_price)
        s += d * ct.qty * pv - ct.extra.get('cost_usd', 0.0)
        i += 1
    state['i'], state['s'] = i, s
    return s
