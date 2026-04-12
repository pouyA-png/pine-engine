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

    def __init__(self):
        self.broker = BrokerEmulator()
        self.opentrades = OpenTradesAccessor(self.broker)
        self.closedtrades = ClosedTradesAccessor(self.broker)

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

    def process_bar(self, bar: Bar):
        """Process entries + exits for this bar. Call BEFORE script execution."""
        self.broker.process_entries(bar)
        self.broker.process_exits(bar)

    def get_results(self):
        """Return all closed trades for reporting."""
        return self.broker.closed_trades
