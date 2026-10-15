"""Broker Emulator — order matching engine replicating TradingView's strategy tester.

Ported from the proven BrokerEmulator in trading_bot.py. This handles:
  - Pending limit order fills
  - Exit order (SL/TP) processing with same-bar disambiguation
  - Position tracking with partial closes
  - Replace semantics for strategy.exit() re-registration

Fill rules (calc_on_every_tick=false):
  - Long limit at P: fills if bar.low <= P. Fill price = min(open, P)
  - Short limit at P: fills if bar.high >= P. Fill price = max(open, P)

TP/SL same-bar disambiguation:
  - Open gaps through SL → SL at open
  - Open gaps through TP → TP at open
  - Bearish bar → SL first (longs), TP first (shorts)
  - Bullish bar → TP first (longs), SL first (shorts)
"""

from __future__ import annotations
import math
import os
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from datetime import datetime

from pine_engine.runtime.na import is_na

# PINE_INTRABAR: 'tv' (default, TV bar-direction heuristic) | 'worst' (always SL when both
# TP and SL are reachable in the same bar) | 'best' (always TP). Analysis-only escape hatch
# to bound the same-bar ambiguity; default behavior is byte-identical to before.

# PINE_ENTRYBAR_STOP: 'off' (default, TV parity: kein Exit in der Einstiegs-Bar) |
# 'on' (Stop/Ziel ab der Fuellung aktiv, gegen die volle Bar-Spanne) | 'gap' (nur die
# beweisbaren Faelle: Fuellpreis == Bar-Open). Ausgewertet in StrategyAPI, siehe
# strategy.py:process_entrybar_exits(). Der zweite Durchgang benutzt exakt dieselbe
# Heuristik wie process_exits (inkl. PINE_INTRABAR), nur auf die in GENAU DIESER Bar
# gefuellten Positionen beschraenkt.


@dataclass
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    bar_index: int


@dataclass
class LimitOrder:
    order_id: str
    side: str          # 'long' or 'short'
    qty: int
    limit_price: float
    comment: str
    active: bool = True
    extra: dict = field(default_factory=dict)   # frei fuer Plugins


@dataclass
class OpenTrade:
    entry_id: str
    side: str
    qty: int
    entry_price: float
    entry_comment: str
    entry_time: Optional[datetime] = None
    remaining_qty: int = field(init=False)
    fired_exit_ids: set = field(default_factory=set)
    extra: dict = field(default_factory=dict)   # frei fuer Plugins (MFE/MAE, Trail-Stand ...)

    def __post_init__(self):
        self.remaining_qty = self.qty


@dataclass
class ClosedTrade:
    entry_id: str
    side: str
    qty: int
    entry_price: float
    exit_price: float
    entry_comment: str
    exit_comment: str
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    extra: dict = field(default_factory=dict)   # frei fuer Plugins (Kosten, R, MFE ...)


class BrokerHook:
    """Basisklasse fuer Broker-Plugins (pine_engine/ext/*). Alle Methoden optional.

    Reihenfolge je Bar (process_entries -> process_exits):
      on_bar_start(broker, bar)                     vor jeder Fuellung dieser Bar
      allow_entry(broker, order, bar) -> bool       False = Order fuellt in dieser Bar nicht
      adjust_fill(broker, order, px, bar) -> px     Einstiegspreis (Slippage ...)
      on_fill(broker, trade, bar)                   nach dem Anlegen der Position
      before_exits(broker, bar)                     vor der SL/TP-Pruefung (nur Regeldurchgang)
      adjust_exit(broker, trade, spec, px, is_tp, bar) -> px   Ausstiegspreis
      on_close(broker, closed_trade)                jede (Teil-)Schliessung, auch close/close_all
      after_exits(broker, bar)                      nach der SL/TP-Pruefung (nur Regeldurchgang)
    Ohne registrierte Hooks ist das Verhalten byte-identisch zu vorher.
    """
    key: str = ''   # gleicher key = ersetzt den alten Hook (add_hook)


class BrokerEmulator:
    """Replicates TradingView's strategy order matching exactly."""

    def __init__(self):
        self.pending_orders: Dict[str, LimitOrder] = {}
        self.open_trades: Dict[str, OpenTrade] = {}
        self.closed_trades: List[ClosedTrade] = []
        self.exit_orders: Dict[str, dict] = {}
        self._current_bar_time: Optional[datetime] = None
        self._current_bar_close: float = 0.0
        self._current_bar_open: float = 0.0
        # Entry-Ids, die in der zuletzt verarbeiteten Bar gefuellt wurden
        # (Basis fuer den zweiten Ausstiegs-Durchgang, PINE_ENTRYBAR_STOP).
        self.last_filled_entry_ids: List[str] = []
        self.hooks: list = []
        # (exit_id, entry_id), im Regeldurchgang der aktuellen Bar geprueft
        self._checked_exit_keys: set = set()

    # ── Plugin-Hooks ──

    def add_hook(self, hook):
        """Hook registrieren; ein Hook mit gleichem ``key`` wird ersetzt."""
        key = getattr(hook, 'key', '') or ''
        if key:
            self.hooks = [h for h in self.hooks if getattr(h, 'key', '') != key]
        self.hooks.append(hook)
        return hook

    def get_hook(self, key: str):
        for h in self.hooks:
            if getattr(h, 'key', '') == key:
                return h
        return None

    def _call_hooks(self, name, *args):
        for h in list(self.hooks):
            fn = getattr(h, name, None)
            if fn is not None:
                fn(self, *args)

    def _allow_entry(self, order, bar) -> bool:
        for h in self.hooks:
            fn = getattr(h, 'allow_entry', None)
            if fn is not None and fn(self, order, bar) is False:
                return False
        return True

    def _adjust_fill(self, order, px, bar):
        for h in self.hooks:
            fn = getattr(h, 'adjust_fill', None)
            if fn is not None:
                px = fn(self, order, px, bar)
        return px

    def _adjust_exit(self, trade, spec, px, is_tp, bar):
        for h in self.hooks:
            fn = getattr(h, 'adjust_exit', None)
            if fn is not None:
                px = fn(self, trade, spec, px, is_tp, bar)
        return px

    def record_close(self, ct: 'ClosedTrade'):
        """Einziger Weg, eine Schliessung zu verbuchen (Hooks sehen jede)."""
        self.closed_trades.append(ct)
        if self.hooks:
            self._call_hooks('on_close', ct)

    def place_limit_order(self, order_id: str, side: str, qty: int,
                          limit_price: float, comment: str):
        self.pending_orders[order_id] = LimitOrder(
            order_id=order_id, side=side, qty=qty,
            limit_price=limit_price, comment=comment)

    def place_order(self, order_id: str, side: str, qty, limit=None, stop=None,
                    comment: str = "", *, entry: bool = False, pyramiding: int = 0,
                    oca_name=None, oca_type=None, expire_bars=None):
        """Erweiterte Order (P1b): Market / Limit / Stop / Stop-Limit, optional
        strategy.entry-Semantik (entry=True: Pyramiding-Grenze + Reversal),
        OCA-Gruppe und Verfall nach ``expire_bars`` Bars. Gleiche id ersetzt.

        Die Art steht in order.extra['kind'] ('market'|'limit'|'stop'|'stoplimit');
        limit_price = Limit, sonst Stop, sonst NaN (Market)."""
        if limit is not None and stop is not None:
            kind = 'stoplimit'
        elif stop is not None:
            kind = 'stop'
        elif limit is not None:
            kind = 'limit'
        else:
            kind = 'market'
        lp = limit if limit is not None else (stop if stop is not None else float('nan'))
        o = LimitOrder(order_id=order_id, side=side, qty=qty,
                       limit_price=lp, comment=comment)
        o.extra['kind'] = kind
        if stop is not None:
            o.extra['stop'] = stop
        if entry:
            o.extra['entry'] = True
            o.extra['pyramiding'] = int(pyramiding or 0)
        if oca_name:
            if oca_type not in (None, 'none', 'cancel'):
                raise NotImplementedError(
                    f'oca_type={oca_type!r} not supported (only strategy.oca.cancel / none)')
            o.extra['oca_name'] = oca_name
            o.extra['oca_type'] = oca_type or 'none'
        if expire_bars is not None:
            o.extra['expire_bars'] = int(expire_bars)
            o.extra['_age'] = 0
        self.pending_orders[order_id] = o
        return o

    def cancel_order(self, order_id: str):
        self.pending_orders.pop(order_id, None)

    def register_exit(self, exit_id: str, from_entry: str, qty: int,
                      limit: float, stop: float,
                      comment_profit: str = "", comment_loss: str = "",
                      **ext):
        """Register or replace an exit order (strategy.exit semantics).

        Once an exit has fired for the current open trade, further
        strategy.exit() calls with the same id are no-ops (TV behavior).
        The exit re-arms only when a new entry fills for the same
        from_entry id.

        from_entry == "" -> gilt fuer ALLE offenen Positionen (Pine-Semantik);
        die Spec bleibt stehen und feuert je Position hoechstens einmal.

        ``ext`` (nur gesetzte Werte, Default-Spec bleibt unveraendert):
          qty_percent, profit, loss (Ticks), trail_price, trail_points,
          trail_offset (Ticks), comment, comment_trailing, mintick.
        """
        trade = self.open_trades.get(from_entry) if from_entry else None
        if trade is not None and exit_id in trade.fired_exit_ids:
            return
        spec = {
            "from_entry": from_entry, "qty": qty,
            "limit": limit, "stop": stop,
            "comment_profit": comment_profit, "comment_loss": comment_loss}
        for k, v in ext.items():
            if v is not None:
                spec[k] = v
        self.exit_orders[exit_id] = spec

    def cancel_exit(self, exit_id: str):
        self.exit_orders.pop(exit_id, None)

    def process_entries(self, bar: Bar) -> List[str]:
        """Fill pending entry orders against this bar's OHLC.

        Legacy-Limit-Orders (place_limit_order, kein extra['kind']) laufen exakt
        wie bisher. Erweiterte Orders (place_order) siehe _entry_fill_price /
        _open_entry."""
        self._current_bar_time = bar.timestamp
        self._current_bar_close = bar.close
        self._current_bar_open = bar.open
        if self.hooks:
            self._call_hooks('on_bar_start', bar)
        done_oids = []
        filled_ids = []
        for oid, order in list(self.pending_orders.items()):
            if not order.active:
                continue
            ex = order.extra
            if 'expire_bars' in ex and ex.get('_age', 0) >= ex['expire_bars']:
                order.active = False          # verfallen (expire_bars)
                done_oids.append(oid)
                continue
            if self.hooks and not self._allow_entry(order, bar):
                if 'expire_bars' in ex:
                    ex['_age'] = ex.get('_age', 0) + 1
                continue
            fill_px = self._entry_fill_price(order, bar)
            if fill_px is None:
                if 'expire_bars' in ex:
                    ex['_age'] = ex.get('_age', 0) + 1
                continue
            if self.hooks:
                fill_px = self._adjust_fill(order, fill_px, bar)
            order.active = False
            done_oids.append(oid)
            key = self._open_entry(order, fill_px, bar)
            if key is None:
                continue
            filled_ids.append(key)
            if self.hooks:
                self._call_hooks('on_fill', self.open_trades[key], bar)
            if ex.get('oca_name') and ex.get('oca_type') == 'cancel':
                for oid2, o2 in list(self.pending_orders.items()):
                    if (o2 is not order and o2.active
                            and o2.extra.get('oca_name') == ex['oca_name']):
                        o2.active = False
                        done_oids.append(oid2)
        for oid in done_oids:
            self.pending_orders.pop(oid, None)
        self.last_filled_entry_ids = list(filled_ids)
        return filled_ids

    @staticmethod
    def _entry_fill_price(order, bar):
        """Fuellpreis dieser Bar oder None. Nur Daten der aktuellen Bar."""
        kind = order.extra.get('kind', 'limit')
        long_ = order.side == 'long'
        if kind == 'limit':
            L = order.limit_price
            if long_ and bar.low <= L:
                return min(bar.open, L) if bar.open <= L else L
            if not long_ and bar.high >= L:
                return max(bar.open, L) if bar.open >= L else L
            return None
        if kind == 'market':
            return bar.open
        S = order.extra['stop']
        if kind == 'stop':
            if long_ and bar.high >= S:
                return max(bar.open, S)
            if not long_ and bar.low <= S:
                return min(bar.open, S)
            return None
        # stoplimit
        L = order.limit_price
        ex = order.extra
        if ex.get('_triggered'):          # ab der Folgebar: reine Limit-Order
            if long_ and bar.low <= L:
                return min(bar.open, L)
            if not long_ and bar.high >= L:
                return max(bar.open, L)
            return None
        if long_:
            if bar.high < S:
                return None
            gap = bar.open >= S
            p = bar.open if gap else S
            if p <= L:
                return p
            if gap and bar.low <= L:      # ganze Bar liegt nach dem Trigger
                return L
        else:
            if bar.low > S:
                return None
            gap = bar.open <= S
            p = bar.open if gap else S
            if p >= L:
                return p
            if gap and bar.high >= L:
                return L
        ex['_triggered'] = True           # Reihenfolge in der Bar unbekannt -> ab Folgebar
        return None

    def _close_trade_qty(self, trade, qty, px, comment, kind, when=None):
        """(Teil-)Schliessung einer offenen Position zum Preis ``px``.
        ClosedTrade.extra['exit_kind'] = kind. Vollstaendig geschlossen ->
        Position und ihre Exit-Specs werden entfernt."""
        qty = min(qty, trade.remaining_qty)
        if qty <= 0:
            return None
        ct = ClosedTrade(
            entry_id=trade.entry_id, side=trade.side, qty=qty,
            entry_price=trade.entry_price, exit_price=px,
            entry_comment=trade.entry_comment, exit_comment=comment,
            entry_time=trade.entry_time,
            exit_time=when if when is not None else self._current_bar_time)
        ct.extra['exit_kind'] = kind
        self.record_close(ct)
        trade.remaining_qty -= qty
        if trade.remaining_qty <= 0:
            self.open_trades.pop(trade.entry_id, None)
            for eid in [e for e, sp in self.exit_orders.items()
                        if sp.get('from_entry') == trade.entry_id]:
                self.exit_orders.pop(eid, None)
        return ct

    def _open_entry(self, order, fill_px, bar):
        """Position fuer eine gefuellte Order anlegen; Rueckgabe = Trade-Key
        oder None (abgelehnt: Richtungsfilter / Pyramiding)."""
        ex = order.extra
        side = order.side
        is_entry = ex.get('entry', False)
        allowed = getattr(self, 'allow_entry_dir', 'all')
        opp = [t for t in self.open_trades.values()
               if t.side != side and t.remaining_qty > 0]
        if allowed != 'all' and side != allowed:
            if is_entry:     # Pine: gesperrte Richtung schliesst nur die Gegenposition
                for t in opp:
                    self._close_trade_qty(t, t.remaining_qty, fill_px,
                                          order.comment or order.order_id,
                                          'direction_filter', bar.timestamp)
            return None
        if is_entry:
            if opp:          # Reversal: Gegenposition(en) zum selben Fuellpreis schliessen
                for t in opp:
                    self._close_trade_qty(t, t.remaining_qty, fill_px,
                                          order.comment or order.order_id,
                                          'reverse', bar.timestamp)
            else:
                same = [t for t in self.open_trades.values() if t.side == side]
                if len(same) >= max(1, ex.get('pyramiding', 0)):
                    return None
        key = order.order_id
        if is_entry and key in self.open_trades:
            n = 2
            while f'{key}#{n}' in self.open_trades:
                n += 1
            key = f'{key}#{n}'
        self.open_trades[key] = OpenTrade(
            entry_id=key, side=side, qty=order.qty,
            entry_price=fill_px, entry_comment=order.comment,
            entry_time=bar.timestamp)
        if is_entry:
            self.open_trades[key].extra['entry_base'] = order.order_id
        return key

    # ── Exit-Kern ──

    @staticmethod
    def _level(v):
        """Preis-/Tick-Parameter: None, na und 0 bedeuten 'nicht gesetzt'."""
        if v is None or is_na(v):
            return None
        v = float(v)
        return None if v == 0 else v

    @staticmethod
    def _given(v):
        """Wie _level, aber 0 ist ein gueltiger Wert (trail_points/trail_offset)."""
        if v is None or is_na(v):
            return None
        return float(v)

    def _exit_qty(self, spec, trade):
        q = spec["qty"]
        qp = self._given(spec.get("qty_percent"))
        if q is None or is_na(q) or q <= 0:
            if qp is not None:
                q = math.floor(trade.qty * qp / 100.0 + 1e-9)
            else:
                q = trade.remaining_qty   # Pine-Default: 100 % der Position
        return min(q, trade.remaining_qty)

    def _exit_levels(self, exit_id, spec, trade):
        """-> (tp, sl, trail_stop) — None = nicht aktiv."""
        long = trade.side == 'long'
        sign = 1.0 if long else -1.0
        mt = spec.get("mintick", 0.25)
        tp = self._level(spec["limit"])
        sl = self._level(spec["stop"])
        prof = self._level(spec.get("profit"))
        if prof is not None:
            ptp = trade.entry_price + sign * prof * mt
            tp = ptp if tp is None else (min(tp, ptp) if long else max(tp, ptp))
        loss = self._level(spec.get("loss"))
        if loss is not None:
            psl = trade.entry_price - sign * loss * mt
            sl = psl if sl is None else (max(sl, psl) if long else min(sl, psl))
        trail_stop = None
        off = self._given(spec.get("trail_offset"))
        if off is not None:
            st = trade.extra.get("_trail", {}).get(exit_id)
            if st is not None and st["active"]:
                trail_stop = st["ext"] - sign * off * mt
        return tp, sl, trail_stop

    def _update_trail(self, exit_id, spec, trade, bar):
        """Trail-Zustand NACH der Pruefung dieser Bar fortschreiben — wirkt erst
        ab der naechsten Bar (kein Lookahead). Die Fuellungs-Bar zaehlt nicht."""
        off = self._given(spec.get("trail_offset"))
        if off is None:
            return
        tprice = self._level(spec.get("trail_price"))
        tpts = self._given(spec.get("trail_points"))
        if tprice is None and tpts is None:
            return
        if trade.entry_time is not None and trade.entry_time == bar.timestamp:
            return
        long = trade.side == 'long'
        mt = spec.get("mintick", 0.25)
        if tprice is not None:
            act = tprice
        else:
            act = trade.entry_price + (tpts * mt if long else -tpts * mt)
        st = trade.extra.setdefault("_trail", {}).setdefault(
            exit_id, {"active": False, "ext": None})
        if not st["active"]:
            if (long and bar.high >= act) or (not long and bar.low <= act):
                st["active"] = True
                st["ext"] = bar.high if long else bar.low
        else:
            st["ext"] = max(st["ext"], bar.high) if long else min(st["ext"], bar.low)

    @staticmethod
    def _match(side, bar, tp_level, sl_level, mode):
        """Same-Bar-Heuristik (unveraendert). -> (hit_tp, hit_sl, exit_px)."""
        hit_tp = hit_sl = False
        exit_px = None
        if side == 'long':
            can_tp = tp_level is not None and bar.high >= tp_level
            can_sl = sl_level is not None and bar.low <= sl_level
            if can_tp and can_sl:
                if bar.open <= sl_level:
                    hit_sl, exit_px = True, bar.open
                elif bar.open >= tp_level:
                    hit_tp, exit_px = True, bar.open
                elif mode == "worst":
                    hit_sl, exit_px = True, sl_level
                elif mode == "best":
                    hit_tp, exit_px = True, tp_level
                elif bar.close < bar.open:
                    hit_sl, exit_px = True, sl_level
                else:
                    hit_tp, exit_px = True, tp_level
            elif can_tp:
                hit_tp = True
                exit_px = (max(bar.open, tp_level)
                           if bar.open >= tp_level else tp_level)
            elif can_sl:
                hit_sl = True
                exit_px = (min(bar.open, sl_level)
                           if bar.open <= sl_level else sl_level)
        else:  # short
            can_tp = tp_level is not None and bar.low <= tp_level
            can_sl = sl_level is not None and bar.high >= sl_level
            if can_tp and can_sl:
                if bar.open >= sl_level:
                    hit_sl, exit_px = True, bar.open
                elif bar.open <= tp_level:
                    hit_tp, exit_px = True, bar.open
                elif mode == "worst":
                    hit_sl, exit_px = True, sl_level
                elif mode == "best":
                    hit_tp, exit_px = True, tp_level
                elif bar.close > bar.open:
                    hit_sl, exit_px = True, sl_level
                else:
                    hit_tp, exit_px = True, tp_level
            elif can_tp:
                hit_tp = True
                exit_px = (min(bar.open, tp_level)
                           if bar.open <= tp_level else tp_level)
            elif can_sl:
                hit_sl = True
                exit_px = (max(bar.open, sl_level)
                           if bar.open >= sl_level else sl_level)
        return hit_tp, hit_sl, exit_px

    def process_exits(self, bar: Bar,
                      only_entries: Optional[set] = None) -> List[str]:
        """Process SL/TP exits against this bar's OHLC.

        only_entries=None -> Regelfall, unveraendertes Verhalten.
        only_entries={...} -> zweiter Durchgang nach der Skriptausfuehrung,
        beschraenkt auf Positionen, die in GENAU DIESER Bar gefuellt wurden
        (PINE_ENTRYBAR_STOP). In diesem Modus werden keine fremden Exit-Orders
        angefasst und keine aufgeraeumt — die Heuristik selbst ist identisch.
        Bugfix: im zweiten Durchgang werden nur (exit_id, entry_id)-Paare
        geprueft, die der Regeldurchgang dieser Bar NICHT schon geprueft hat
        (sonst wuerde z. B. ein nach TP1 nachgezogener Stop dieselbe Bar-Spanne
        ein zweites Mal sehen).
        """
        fired = []
        remove = []
        regular = only_entries is None
        if regular:
            self._checked_exit_keys = set()
        checked = self._checked_exit_keys
        if self.hooks and regular:
            self._call_hooks('before_exits', bar)
        _mode = os.environ.get("PINE_INTRABAR", "tv")
        for exit_id, spec in list(self.exit_orders.items()):
            fe = spec["from_entry"]
            if fe:
                if not regular and fe not in only_entries:
                    continue
                trade = self.open_trades.get(fe)
                if trade is None or trade.remaining_qty <= 0:
                    if regular:
                        remove.append(exit_id)
                    continue
                targets = [trade]
            else:
                # strategy.exit ohne from_entry: alle offenen Positionen
                targets = [t for t in list(self.open_trades.values())
                           if t.remaining_qty > 0
                           and exit_id not in t.fired_exit_ids
                           and (regular or t.entry_id in only_entries)]
            for trade in targets:
                key = (exit_id, trade.entry_id)
                if regular:
                    checked.add(key)
                elif key in checked:
                    continue
                if exit_id not in self.exit_orders:
                    break
                qty_close = self._exit_qty(spec, trade)
                if qty_close <= 0:
                    continue
                tp_level, sl_level, trail_stop = self._exit_levels(exit_id, spec, trade)
                is_trail = False
                if trail_stop is not None and (
                        sl_level is None
                        or (trail_stop > sl_level if trade.side == 'long'
                            else trail_stop < sl_level)):
                    sl_level, is_trail = trail_stop, True
                hit_tp, hit_sl, exit_px = self._match(
                    trade.side, bar, tp_level, sl_level, _mode)

                if hit_tp or hit_sl:
                    base = spec.get("comment", "")
                    if hit_tp:
                        ec, kind = spec["comment_profit"] or base, 'tp'
                    elif is_trail:
                        ec, kind = spec.get("comment_trailing") or base, 'trail'
                    else:
                        ec, kind = spec["comment_loss"] or base, 'sl'
                    if self.hooks:
                        exit_px = self._adjust_exit(trade, spec, exit_px, hit_tp, bar)
                    ct = ClosedTrade(
                        entry_id=trade.entry_id, side=trade.side,
                        qty=qty_close, entry_price=trade.entry_price,
                        exit_price=exit_px, entry_comment=trade.entry_comment,
                        exit_comment=ec, entry_time=trade.entry_time,
                        exit_time=bar.timestamp)
                    self.record_close(ct)
                    # Exit-Grund erst NACH den on_close-Hooks: ein Plugin-Grund
                    # (z. B. 'be', 'trail' aus ext/mgmt_stops) hat Vorrang.
                    ct.extra.setdefault('exit_kind', kind)
                    ct.extra.setdefault('exit_id', exit_id)
                    trade.remaining_qty -= qty_close
                    trade.fired_exit_ids.add(exit_id)
                    if trade.remaining_qty <= 0:
                        del self.open_trades[trade.entry_id]
                    fired.append(ec)
                    if fe:
                        remove.append(exit_id)
                elif regular:
                    self._update_trail(exit_id, spec, trade, bar)

        for eid in remove:
            self.exit_orders.pop(eid, None)
        if self.hooks and regular:
            self._call_hooks('after_exits', bar)
        return fired

    def process_bar(self, bar: Bar) -> List[str]:
        """Process a complete bar: entries first, then exits."""
        self.process_entries(bar)
        return self.process_exits(bar)

    # ── Strategy API properties ──

    @property
    def opentrades_count(self) -> int:
        return len(self.open_trades)

    def get_open_trades(self) -> List[OpenTrade]:
        return list(self.open_trades.values())

    def opentrades_entry_comment(self, index: int) -> str:
        trades = list(self.open_trades.values())
        if 0 <= index < len(trades):
            return trades[index].entry_comment
        return ""

    def opentrades_entry_price(self, index: int) -> float:
        trades = list(self.open_trades.values())
        if 0 <= index < len(trades):
            return trades[index].entry_price
        return float('nan')

    @property
    def closedtrades_count(self) -> int:
        return len(self.closed_trades)

    def closedtrades_exit_comment(self, index: int) -> str:
        if 0 <= index < len(self.closed_trades):
            return self.closed_trades[index].exit_comment
        return ""

    def closedtrades_profit(self, index: int) -> float:
        """strategy.closedtrades.profit(k) — PnL in Punkten x qty (vorzeichenrichtig)."""
        if 0 <= index < len(self.closed_trades):
            t = self.closed_trades[index]
            d = (t.exit_price - t.entry_price) if t.side == "long" else (t.entry_price - t.exit_price)
            return d * t.qty
        return float('nan')

    def closedtrades_size(self, index: int) -> float:
        """strategy.closedtrades.size(k) — Menge, long positiv / short negativ (Pine-Konvention)."""
        if 0 <= index < len(self.closed_trades):
            t = self.closed_trades[index]
            return t.qty if t.side == "long" else -t.qty
        return float('nan')
