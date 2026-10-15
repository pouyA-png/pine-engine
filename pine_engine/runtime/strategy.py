"""Strategy API — wraps BrokerEmulator to match Pine Script's strategy.* interface.

This provides the exact same API surface that the transpiled Pine code will call:
  strategy.order(), strategy.exit(), strategy.cancel()
  strategy.opentrades, strategy.closedtrades
  strategy.opentrades.entry_comment(j), strategy.opentrades.entry_price(j)
  strategy.closedtrades.exit_comment(k)
"""

from __future__ import annotations
import math
import os
from pine_engine.runtime.broker import BrokerEmulator, Bar
from pine_engine.runtime.na import is_na

# Pine constants
STRATEGY_LONG = 'long'
STRATEGY_SHORT = 'short'


class OpenTradesAccessor:
    """Provides strategy.opentrades.entry_comment(j) / entry_price(j) syntax."""

    def __init__(self, broker: BrokerEmulator):
        self._broker = broker

    def __len__(self):
        return self._broker.opentrades_count

    def __int__(self):
        return self._broker.opentrades_count

    def __gt__(self, other):
        return self._broker.opentrades_count > other

    def __ge__(self, other):
        return self._broker.opentrades_count >= other

    def __eq__(self, other):
        return self._broker.opentrades_count == other

    def __lt__(self, other):
        return self._broker.opentrades_count < other

    def __le__(self, other):
        return self._broker.opentrades_count <= other

    def __sub__(self, other):
        return self._broker.opentrades_count - other

    def __bool__(self):
        return self._broker.opentrades_count > 0

    def entry_comment(self, index: int) -> str:
        return self._broker.opentrades_entry_comment(index)

    def entry_price(self, index: int) -> float:
        return self._broker.opentrades_entry_price(index)


class ClosedTradesAccessor:
    """Provides strategy.closedtrades.exit_comment(k) syntax."""

    def __init__(self, broker: BrokerEmulator):
        self._broker = broker

    def __len__(self):
        return self._broker.closedtrades_count

    def __int__(self):
        return self._broker.closedtrades_count

    def __gt__(self, other):
        return self._broker.closedtrades_count > other

    def __ge__(self, other):
        return self._broker.closedtrades_count >= other

    def __eq__(self, other):
        return self._broker.closedtrades_count == other

    def __lt__(self, other):
        return self._broker.closedtrades_count < other

    def __le__(self, other):
        return self._broker.closedtrades_count <= other

    def __sub__(self, other):
        return self._broker.closedtrades_count - other

    def __bool__(self):
        return self._broker.closedtrades_count > 0

    def exit_comment(self, index: int) -> str:
        return self._broker.closedtrades_exit_comment(index)

    def profit(self, index: int) -> float:
        return self._broker.closedtrades_profit(index)

    def size(self, index: int) -> float:
        return self._broker.closedtrades_size(index)


class StrategyAPI:
    """Pine Script strategy.* function interface.

    Usage in transpiled code:
        ctx.strategy.order("Long_078", STRATEGY_LONG, qty=50, limit=price)
        ctx.strategy.exit("ExL078_tp1", from_entry="Long_078", qty=25, limit=tp, stop=sl)
        ctx.strategy.cancel("Long_078")
        if ctx.strategy.opentrades > 0: ...
        ec = ctx.strategy.closedtrades.exit_comment(k)
    """

    def __init__(self, initial_capital: float = 100000.0,
                 point_value: float = 20.0, mintick: float = 0.25):
        self.broker = BrokerEmulator()
        self.mintick = mintick   # syminfo.mintick — Tickgroesse fuer profit/loss/trail_*
        self.opentrades = OpenTradesAccessor(self.broker)
        self.closedtrades = ClosedTradesAccessor(self.broker)
        self._initial_capital = initial_capital
        self._point_value = point_value
        # PINE_ENTRYBAR_STOP — zweiter Ausstiegs-Durchgang nach der Skriptausfuehrung.
        self._entrybar_bar: Bar = None      # Bar, deren Fuellungen noch offen sind
        self._entrybar_ids: set = set()     # Entry-Ids, in dieser Bar gefuellt
        self.entrybar_fired_bars: int = 0   # Bars, in denen der Pfad gegriffen hat
        self.entrybar_fired_exits: int = 0  # dort ausgeloeste Exits

    @property
    def opentrades_count(self):
        return self.broker.opentrades_count

    @property
    def closedtrades_count(self):
        return self.broker.closedtrades_count

    def order(self, id: str, direction: str, qty: int = 1,
              limit: float = None, comment: str = "", stop: float = None,
              oca_name: str = None, oca_type: str = None, expire_bars: int = None):
        """strategy.order() — Limit (limit=), Stop (stop=), Stop-Limit (beide)
        oder Market (keins; fuellt zum Open der naechsten Bar).

        Nur limit= gesetzt -> exakt der bisherige Pfad (place_limit_order), auch
        bei limit=na (fuellt dann nie — Altverhalten, bewusst beibehalten).
        oca_name/oca_type (strategy.oca.cancel), expire_bars (Erweiterung:
        Verfall nach N Bars) nur wenn angegeben."""
        side = 'long' if direction == STRATEGY_LONG else 'short'
        stop = None if (stop is None or is_na(stop)) else stop
        if (limit is not None and stop is None and not oca_name
                and expire_bars is None):
            self.broker.place_limit_order(id, side, qty, limit, comment)
            return
        if limit is not None and is_na(limit):
            limit = None
        self.broker.place_order(id, side, qty, limit=limit, stop=stop,
                                comment=comment, oca_name=oca_name,
                                oca_type=oca_type, expire_bars=expire_bars)

    def entry(self, id: str, direction: str, qty: int = 1,
              limit: float = None, stop: float = None, comment: str = "",
              oca_name: str = None, oca_type: str = None,
              expire_bars: int = None, pyramiding: int = 0):
        """strategy.entry() — wie order(), plus Pine-Semantik bei Fuellung:
        Gegenposition(en) werden zum selben Fuellpreis geschlossen (Reversal),
        gleiche Richtung nur bis max(1, pyramiding) offene Entries.
        limit/stop = na -> nicht gesetzt (Market)."""
        side = 'long' if direction == STRATEGY_LONG else 'short'
        limit = None if (limit is None or is_na(limit)) else limit
        stop = None if (stop is None or is_na(stop)) else stop
        self.broker.place_order(id, side, qty, limit=limit, stop=stop,
                                comment=comment, entry=True,
                                pyramiding=pyramiding, oca_name=oca_name,
                                oca_type=oca_type, expire_bars=expire_bars)

    def risk_allow_entry_in(self, direction: str):
        """strategy.risk.allow_entry_in() — Richtungsfilter ('long'|'short'|'all').
        Gesperrte Richtung: Orders oeffnen keine Position; strategy.entry in der
        gesperrten Richtung schliesst nur eine bestehende Gegenposition."""
        self.broker.allow_entry_dir = direction if direction in ('long', 'short') else 'all'

    def exit(self, id: str, from_entry: str = "", qty: int = 0,
             limit: float = 0.0, stop: float = 0.0,
             comment_profit: str = "", comment_loss: str = "",
             qty_percent: float = None, profit: float = None, loss: float = None,
             trail_price: float = None, trail_points: float = None,
             trail_offset: float = None, comment: str = None,
             comment_trailing: str = None,
             alert_message=None, alert_profit=None, alert_loss=None,
             alert_trailing=None, disable_alert=None):
        """strategy.exit() — register SL/TP exit (replaces existing with same id).

        limit/stop: Preise; profit/loss/trail_points/trail_offset: Ticks
        (self.mintick, Standard 0.25). Fehlt/0/na = nicht gesetzt.
        from_entry leer -> gilt fuer alle offenen Positionen.
        alert_*/disable_alert: ohne Wirkung im Backtest (nur Alarmtexte).
        """
        if from_entry is None or (isinstance(from_entry, float) and from_entry != from_entry):
            from_entry = ""
        ext = dict(qty_percent=qty_percent, profit=profit, loss=loss,
                   trail_price=trail_price, trail_points=trail_points,
                   trail_offset=trail_offset, comment=comment,
                   comment_trailing=comment_trailing)
        ext = {k: v for k, v in ext.items() if v is not None}
        if ext:
            ext["mintick"] = self.mintick
        self.broker.register_exit(
            exit_id=id, from_entry=from_entry, qty=qty,
            limit=limit, stop=stop,
            comment_profit=comment_profit, comment_loss=comment_loss, **ext)

    def cancel(self, id: str):
        """strategy.cancel() — storniert die wartende Entry-Order UND eine
        Exit-Order (strategy.exit) mit dieser id."""
        self.broker.cancel_order(id)
        self.broker.cancel_exit(id)

    def cancel_all(self):
        """strategy.cancel_all() — cancel all pending entry orders."""
        ids = list(self.broker.pending_orders.keys())
        for oid in ids:
            self.broker.cancel_order(oid)

    def close_all(self, comment: str = "close_all"):
        """strategy.close_all() — close all open positions at market (current bar's close price).
        ClosedTrade.extra['exit_kind'] = 'close'."""
        # Fix 2026-05-28 (pine-engine-Zweig), nach nq-lab uebernommen 2026-08-23: vorher
        # exit_price=entry_price ("placeholder") -> jeder close_all()-Exit (EOD_CLOSE) war PnL 0.
        close_px = self.broker._current_bar_close or 0.0
        for trade_id in list(self.broker.open_trades.keys()):
            trade = self.broker.open_trades[trade_id]
            if trade.remaining_qty > 0:
                from pine_engine.runtime.broker import ClosedTrade
                exit_px = close_px if close_px else trade.entry_price
                ct = ClosedTrade(
                    entry_id=trade.entry_id, side=trade.side,
                    qty=trade.remaining_qty, entry_price=trade.entry_price,
                    exit_price=exit_px,
                    entry_comment=trade.entry_comment, exit_comment=comment,
                    entry_time=trade.entry_time, exit_time=self.broker._current_bar_time)
                ct.extra['exit_kind'] = 'close'
                self.broker.record_close(ct)
                trade.remaining_qty = 0
        self.broker.open_trades.clear()
        # Also clear exit orders
        self.broker.exit_orders.clear()

    def close(self, entry_id: str, comment: str = "close",
              qty: float = None, qty_percent: float = None):
        """strategy.close() — schliesst die Position(en) mit dieser Entry-id zum
        Close der aktuellen Bar. qty= / qty_percent= -> Teilschliessung (FIFO ueber
        gepyramidete Entries gleicher id); Prozent wird bei ganzzahliger Menge
        abgerundet. ClosedTrade.extra['exit_kind'] = 'close'."""
        b = self.broker
        trades = [t for k, t in b.open_trades.items()
                  if k == entry_id or t.extra.get('entry_base') == entry_id]
        trades = [t for t in trades if t.remaining_qty > 0]
        if not trades:
            return
        total = sum(t.remaining_qty for t in trades)
        if qty is not None and not is_na(qty):
            want = min(qty, total)
        elif qty_percent is not None and not is_na(qty_percent):
            want = total * qty_percent / 100.0
            if all(isinstance(t.remaining_qty, int) for t in trades):
                want = int(math.floor(want + 1e-9))
        else:
            want = total
        close_px = b._current_bar_close or 0.0
        for t in trades:
            if want <= 0:
                break
            q = min(want, t.remaining_qty)
            b._close_trade_qty(t, q, close_px if close_px else t.entry_price,
                               comment, 'close')
            want -= q

    @property
    def equity(self) -> float:
        """strategy.equity — current account equity in dollars."""
        pnl = sum(
            ((t.exit_price - t.entry_price) * t.qty if t.side == 'long'
             else (t.entry_price - t.exit_price) * t.qty)
            for t in self.broker.closed_trades
        )
        return self._initial_capital + pnl * self._point_value

    def process_bar(self, bar: Bar):
        """Process entries + exits for this bar. Call BEFORE script execution."""
        # Auffangnetz fuer Aufrufer, die die Bar-Schleife selbst schreiben und
        # process_entrybar_exits() nicht aufrufen: der ausstehende Durchgang der
        # VORIGEN Bar wird hier nachgeholt (er benutzt die Daten jener Bar, ist
        # also zeitlich identisch). Wer ihn direkt nach execute_bar() aufruft,
        # laeuft hier ins Leere — der Aufruf ist idempotent.
        self.process_entrybar_exits()
        self.broker.process_entries(bar)
        self.broker.process_exits(bar)
        # Merken, was in DIESER Bar gefuellt wurde — Basis des zweiten Durchgangs.
        self._entrybar_bar = bar
        self._entrybar_ids = set(self.broker.last_filled_entry_ids)

    def process_entrybar_exits(self):
        """Zweiter Ausstiegs-Durchgang, NACH der Skriptausfuehrung derselben Bar.

        Bildet ab, was live ueber PineConnector passiert: der sl_price geht mit der
        Einstiegsorder raus, der Stop liegt ab der Fuellung serverseitig im Markt und
        kann schon in der Einstiegs-Minute ausloesen. Der Backtest registriert den
        strategy.exit-Auftrag dagegen erst, wenn das Skript spaeter in derselben Bar
        laeuft — process_exits() ist da schon durch.

        PINE_ENTRYBAR_STOP:
          off  (Default) — heutiges Verhalten, TradingView-Paritaet. Kein Durchgang.
          on             — Stop UND Ziel gegen die volle Bar-Spanne. Obergrenze des Effekts.
          gap            — nur Positionen mit Fuellpreis == Bar-Open; dort liegt die
                           ganze Bar-Spanne nachweislich nach der Fuellung. Untergrenze.

        Stop und Ziel werden gleich behandelt: der Durchgang ruft dieselbe
        process_exits()-Heuristik auf (inkl. PINE_INTRABAR), nur auf die in dieser
        Bar gefuellten Positionen beschraenkt.

        Bugfix: ausgewertet werden nur Exit-Orders, die der erste Durchgang dieser
        Bar NICHT schon geprueft hat (vom Skript in dieser Bar neu angelegt). Ein
        bereits geprueftes, vom Skript nur verschobenes Exit (z. B. Stop nach TP1
        auf Einstand) sieht dieselbe Bar-Spanne nicht ein zweites Mal
        (Filter in BrokerEmulator.process_exits, only_entries-Modus).
        """
        bar = self._entrybar_bar
        ids = self._entrybar_ids
        self._entrybar_bar = None
        self._entrybar_ids = set()
        if bar is None or not ids:
            return []
        mode = os.environ.get("PINE_ENTRYBAR_STOP", "off").strip().lower()
        if mode not in ("on", "gap"):
            return []
        if mode == "gap":
            ids = {eid for eid in ids
                   if (self.broker.open_trades.get(eid) is not None
                       and self.broker.open_trades[eid].entry_price == bar.open)}
        if not ids:
            return []
        fired = self.broker.process_exits(bar, only_entries=ids)
        if fired:
            self.entrybar_fired_bars += 1
            self.entrybar_fired_exits += len(fired)
        return fired

    def get_results(self):
        """Return all closed trades for reporting."""
        return self.broker.closed_trades
