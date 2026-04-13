"""Strategy API — wraps BrokerEmulator to match Pine Script's strategy.* interface.

This provides the exact same API surface that the transpiled Pine code will call:
  strategy.order(), strategy.exit(), strategy.cancel()
  strategy.opentrades, strategy.closedtrades
  strategy.opentrades.entry_comment(j), strategy.opentrades.entry_price(j)
  strategy.closedtrades.exit_comment(k)
"""

from __future__ import annotations
from pine_engine.runtime.broker import BrokerEmulator, Bar

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
                 point_value: float = 20.0):
        self.broker = BrokerEmulator()
        self.opentrades = OpenTradesAccessor(self.broker)
        self.closedtrades = ClosedTradesAccessor(self.broker)
        self._initial_capital = initial_capital
        self._point_value = point_value

    @property
    def opentrades_count(self):
        return self.broker.opentrades_count

    @property
    def closedtrades_count(self):
        return self.broker.closedtrades_count

    def order(self, id: str, direction: str, qty: int = 1,
              limit: float = None, comment: str = ""):
        """strategy.order() — place a pending limit order."""
        side = 'long' if direction == STRATEGY_LONG else 'short'
        self.broker.place_limit_order(id, side, qty, limit, comment)

    def exit(self, id: str, from_entry: str = "", qty: int = 0,
             limit: float = 0.0, stop: float = 0.0,
             comment_profit: str = "", comment_loss: str = ""):
        """strategy.exit() — register SL/TP exit (replaces existing with same id)."""
        self.broker.register_exit(
            exit_id=id, from_entry=from_entry, qty=qty,
            limit=limit, stop=stop,
            comment_profit=comment_profit, comment_loss=comment_loss)

    def cancel(self, id: str):
        """strategy.cancel() — cancel a pending entry order by id."""
        self.broker.cancel_order(id)

    def cancel_all(self):
        """strategy.cancel_all() — cancel all pending entry orders."""
        ids = list(self.broker.pending_orders.keys())
        for oid in ids:
            self.broker.cancel_order(oid)

    def close_all(self, comment: str = "close_all"):
        """strategy.close_all() — close all open positions at market."""
        # In backtesting, this closes at the current bar's close price
        # We'll mark them as closed with the given comment
        for trade_id in list(self.broker.open_trades.keys()):
            trade = self.broker.open_trades[trade_id]
            if trade.remaining_qty > 0:
                from pine_engine.runtime.broker import ClosedTrade
                self.broker.closed_trades.append(ClosedTrade(
                    entry_id=trade.entry_id, side=trade.side,
                    qty=trade.remaining_qty, entry_price=trade.entry_price,
                    exit_price=trade.entry_price,  # Close at entry (placeholder)
                    entry_comment=trade.entry_comment, exit_comment=comment,
                    entry_time=trade.entry_time, exit_time=self.broker._current_bar_time))
                trade.remaining_qty = 0
        self.broker.open_trades.clear()
        # Also clear exit orders
        self.broker.exit_orders.clear()

    def close(self, entry_id: str, comment: str = "close"):
        """strategy.close() — close a specific open position by entry ID."""
        trade = self.broker.open_trades.get(entry_id)
        if trade and trade.remaining_qty > 0:
            from pine_engine.runtime.broker import ClosedTrade
            self.broker.closed_trades.append(ClosedTrade(
                entry_id=trade.entry_id, side=trade.side,
                qty=trade.remaining_qty, entry_price=trade.entry_price,
                exit_price=trade.entry_price,
                entry_comment=trade.entry_comment, exit_comment=comment,
                entry_time=trade.entry_time, exit_time=self.broker._current_bar_time))
            trade.remaining_qty = 0
            del self.broker.open_trades[entry_id]
            # Clean up exit orders for this entry
            remove = [eid for eid, spec in self.broker.exit_orders.items()
                      if spec['from_entry'] == entry_id]
            for eid in remove:
                self.broker.exit_orders.pop(eid, None)

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
        self.broker.process_entries(bar)
        self.broker.process_exits(bar)

    def get_results(self):
        """Return all closed trades for reporting."""
        return self.broker.closed_trades
