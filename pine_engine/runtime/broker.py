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
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from datetime import datetime


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


@dataclass
class OpenTrade:
    entry_id: str
    side: str
    qty: int
    entry_price: float
    entry_comment: str
    entry_time: Optional[datetime] = None
    remaining_qty: int = field(init=False)

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


class BrokerEmulator:
    """Replicates TradingView's strategy order matching exactly."""

    def __init__(self):
        self.pending_orders: Dict[str, LimitOrder] = {}
        self.open_trades: Dict[str, OpenTrade] = {}
        self.closed_trades: List[ClosedTrade] = []
        self.exit_orders: Dict[str, dict] = {}
        self._current_bar_time: Optional[datetime] = None

    def place_limit_order(self, order_id: str, side: str, qty: int,
                          limit_price: float, comment: str):
        self.pending_orders[order_id] = LimitOrder(
            order_id=order_id, side=side, qty=qty,
            limit_price=limit_price, comment=comment)

    def cancel_order(self, order_id: str):
        self.pending_orders.pop(order_id, None)

    def register_exit(self, exit_id: str, from_entry: str, qty: int,
                      limit: float, stop: float,
                      comment_profit: str = "", comment_loss: str = ""):
        """Register or replace an exit order (strategy.exit semantics)."""
        self.exit_orders[exit_id] = {
            "from_entry": from_entry, "qty": qty,
            "limit": limit, "stop": stop,
            "comment_profit": comment_profit, "comment_loss": comment_loss}

    def cancel_exit(self, exit_id: str):
        self.exit_orders.pop(exit_id, None)

    def process_entries(self, bar: Bar) -> List[str]:
        """Fill pending limit orders against this bar's OHLC."""
        self._current_bar_time = bar.timestamp
        filled_ids = []
        for oid, order in self.pending_orders.items():
            if not order.active:
                continue
            if order.side == 'long' and bar.low <= order.limit_price:
                fill_px = (min(bar.open, order.limit_price)
                           if bar.open <= order.limit_price
                           else order.limit_price)
                order.active = False
                self.open_trades[order.order_id] = OpenTrade(
                    entry_id=order.order_id, side=order.side, qty=order.qty,
                    entry_price=fill_px, entry_comment=order.comment,
                    entry_time=bar.timestamp)
                filled_ids.append(oid)
            elif order.side == 'short' and bar.high >= order.limit_price:
                fill_px = (max(bar.open, order.limit_price)
                           if bar.open >= order.limit_price
                           else order.limit_price)
                order.active = False
                self.open_trades[order.order_id] = OpenTrade(
                    entry_id=order.order_id, side=order.side, qty=order.qty,
                    entry_price=fill_px, entry_comment=order.comment,
                    entry_time=bar.timestamp)
                filled_ids.append(oid)
        for oid in filled_ids:
            del self.pending_orders[oid]
        return filled_ids

    def process_exits(self, bar: Bar) -> List[str]:
        """Process SL/TP exits against this bar's OHLC."""
        fired = []
        remove = []
        for exit_id, spec in list(self.exit_orders.items()):
            trade = self.open_trades.get(spec["from_entry"])
            if trade is None or trade.remaining_qty <= 0:
                remove.append(exit_id)
                continue
            qty_close = min(spec["qty"], trade.remaining_qty)
            hit_tp = hit_sl = False
            exit_px = None
            tp_level = spec["limit"]
            sl_level = spec["stop"]

            if trade.side == 'long':
                can_tp = bar.high >= tp_level
                can_sl = bar.low <= sl_level
                if can_tp and can_sl:
                    if bar.open <= sl_level:
                        hit_sl, exit_px = True, bar.open
                    elif bar.open >= tp_level:
                        hit_tp, exit_px = True, bar.open
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
                can_tp = bar.low <= tp_level
                can_sl = bar.high >= sl_level
                if can_tp and can_sl:
                    if bar.open >= sl_level:
                        hit_sl, exit_px = True, bar.open
                    elif bar.open <= tp_level:
                        hit_tp, exit_px = True, bar.open
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

            if hit_tp or hit_sl:
                ec = spec["comment_profit"] if hit_tp else spec["comment_loss"]
                self.closed_trades.append(ClosedTrade(
                    entry_id=spec["from_entry"], side=trade.side,
                    qty=qty_close, entry_price=trade.entry_price,
                    exit_price=exit_px, entry_comment=trade.entry_comment,
                    exit_comment=ec, entry_time=trade.entry_time,
                    exit_time=bar.timestamp))
                trade.remaining_qty -= qty_close
                if trade.remaining_qty <= 0:
                    del self.open_trades[spec["from_entry"]]
                fired.append(ec)
                remove.append(exit_id)

        for eid in remove:
            self.exit_orders.pop(eid, None)
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
