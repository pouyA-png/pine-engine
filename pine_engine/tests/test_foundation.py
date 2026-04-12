"""Tests for Phase 0 foundation: NA, Series, Broker, Builtins."""

import math
import sys
sys.path.insert(0, '/home/pouya/pine-engine')

from pine_engine.runtime.na import (
    NA, is_na, pine_add, pine_sub, pine_mul, pine_div,
    pine_eq, pine_lt, pine_gt, pine_and, pine_or, pine_not,
    pine_abs, pine_min, pine_max, pine_round, pine_floor
)
from pine_engine.runtime.series import Series
from pine_engine.runtime.broker import BrokerEmulator, Bar
from pine_engine.runtime.builtins import (
    pine_hour, pine_minute, pine_dayofweek,
    pine_year, pine_month, pine_dayofmonth,
    ta_pivothigh, ta_pivotlow, ta_highest, ta_lowest,
    DAYOFWEEK_MONDAY
)
from pine_engine.runtime.strategy import StrategyAPI, STRATEGY_LONG, STRATEGY_SHORT
from datetime import datetime, timezone


def test_na_basics():
    assert is_na(NA)
    assert is_na(None)
    assert is_na(float('nan'))
    assert not is_na(0)
    assert not is_na(0.0)
    assert not is_na(False)
    assert not is_na("")
    print("  [PASS] NA basics")


def test_na_arithmetic():
    assert is_na(pine_add(NA, 5))
    assert is_na(pine_sub(3, NA))
    assert is_na(pine_mul(NA, NA))
    assert is_na(pine_div(NA, 2))
    assert is_na(pine_div(5, 0))  # div by zero = NA
    assert pine_add(3, 5) == 8
    assert pine_sub(10, 3) == 7
    assert pine_mul(4, 5) == 20
    assert pine_div(10, 2) == 5.0
    print("  [PASS] NA arithmetic")


def test_na_comparison():
    assert pine_eq(5, 5) == True
    assert pine_eq(NA, 5) == False
    assert pine_eq(NA, NA) == False
    assert pine_lt(3, 5) == True
    assert pine_lt(NA, 5) == False
    assert pine_gt(5, 3) == True
    assert pine_gt(NA, 3) == False
    print("  [PASS] NA comparison")


def test_na_boolean():
    assert pine_and(True, True) == True
    assert pine_and(NA, True) == False
    assert pine_and(True, NA) == False
    assert pine_and(False, True) == False
    assert pine_or(True, False) == True
    assert pine_or(NA, True) == True
    assert pine_or(NA, NA) == False
    assert pine_not(NA) == True
    assert pine_not(True) == False
    assert pine_not(False) == True
    print("  [PASS] NA boolean logic")


def test_na_math():
    assert is_na(pine_abs(NA))
    assert pine_abs(-5) == 5
    assert pine_min(3, 5) == 3
    assert pine_min(NA, 5) == 5
    assert pine_max(3, NA) == 3
    assert pine_round(3.456, 2) == 3.46
    assert pine_floor(3.9) == 3
    print("  [PASS] NA math wrappers")


def test_series_basic():
    s = Series()
    s.append(10)
    s.append(20)
    s.append(30)
    assert s[0] == 30  # current
    assert s[1] == 20  # previous
    assert s[2] == 10  # 2 bars ago
    assert is_na(s[3])  # out of bounds
    assert is_na(s[-1])  # negative
    assert s.current == 30
    assert len(s) == 3
    print("  [PASS] Series basic access")


def test_series_max_lookback():
    s = Series(max_lookback=3)
    for i in range(10):
        s.append(i)
    assert len(s) == 3
    assert s[0] == 9   # current (last appended)
    assert s[1] == 8
    assert s[2] == 7
    assert is_na(s[3])  # trimmed
    print("  [PASS] Series max lookback")


def test_series_highest_lowest():
    s = Series()
    for v in [10, 20, 5, 30, 15]:
        s.append(v)
    assert s.highest(5) == 30
    assert s.lowest(5) == 5
    assert s.highest(2) == 30  # last 2: [15, 30]... wait, [0]=15, [1]=30
    assert s.lowest(2) == 15
    print("  [PASS] Series highest/lowest")


def test_broker_long_fill():
    broker = BrokerEmulator()
    broker.place_limit_order("L1", "long", 50, 100.0, "Long_078")
    bar = Bar(datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),
              open=101.0, high=102.0, low=99.0, close=100.5, bar_index=0)
    filled = broker.process_entries(bar)
    assert "L1" in filled
    assert broker.opentrades_count == 1
    trade = broker.get_open_trades()[0]
    assert trade.entry_price == 100.0  # limit price (open was above)
    print("  [PASS] Broker long limit fill")


def test_broker_short_fill():
    broker = BrokerEmulator()
    broker.place_limit_order("S1", "short", 50, 200.0, "Short_178")
    bar = Bar(datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),
              open=199.0, high=201.0, low=198.0, close=199.5, bar_index=0)
    filled = broker.process_entries(bar)
    assert "S1" in filled
    trade = broker.get_open_trades()[0]
    assert trade.entry_price == 200.0  # limit price
    print("  [PASS] Broker short limit fill")


def test_broker_gap_fill():
    broker = BrokerEmulator()
    broker.place_limit_order("L1", "long", 50, 100.0, "Long")
    # Bar opens below limit — gap fill at open
    bar = Bar(datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),
              open=98.0, high=102.0, low=97.0, close=101.0, bar_index=0)
    broker.process_entries(bar)
    trade = broker.get_open_trades()[0]
    assert trade.entry_price == 98.0  # filled at open (gap through limit)
    print("  [PASS] Broker gap fill at open")


def test_broker_exit_tp():
    broker = BrokerEmulator()
    broker.place_limit_order("L1", "long", 50, 100.0, "Long")
    fill_bar = Bar(datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),
                   open=101.0, high=102.0, low=99.0, close=100.5, bar_index=0)
    broker.process_entries(fill_bar)

    # Register TP at 110, SL at 95
    broker.register_exit("Ex1", "L1", 50, limit=110.0, stop=95.0,
                         comment_profit="TP1", comment_loss="SL1")

    # Bar hits TP
    tp_bar = Bar(datetime(2024, 1, 2, 14, 31, tzinfo=timezone.utc),
                 open=108.0, high=111.0, low=107.0, close=109.0, bar_index=1)
    fired = broker.process_exits(tp_bar)
    assert "TP1" in fired
    assert broker.closedtrades_count == 1
    assert broker.closed_trades[0].exit_price == 110.0
    print("  [PASS] Broker exit TP hit")


def test_broker_exit_sl():
    broker = BrokerEmulator()
    broker.place_limit_order("L1", "long", 50, 100.0, "Long")
    fill_bar = Bar(datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),
                   open=101.0, high=102.0, low=99.0, close=100.5, bar_index=0)
    broker.process_entries(fill_bar)

    broker.register_exit("Ex1", "L1", 50, limit=110.0, stop=95.0,
                         comment_profit="TP1", comment_loss="SL1")

    # Bar hits SL
    sl_bar = Bar(datetime(2024, 1, 2, 14, 31, tzinfo=timezone.utc),
                 open=98.0, high=99.0, low=94.0, close=95.0, bar_index=1)
    fired = broker.process_exits(sl_bar)
    assert "SL1" in fired
    assert broker.closed_trades[0].exit_price == 95.0
    print("  [PASS] Broker exit SL hit")


def test_broker_partial_close():
    broker = BrokerEmulator()
    broker.place_limit_order("L1", "long", 50, 100.0, "Long")
    fill_bar = Bar(datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),
                   open=101.0, high=102.0, low=99.0, close=100.5, bar_index=0)
    broker.process_entries(fill_bar)

    # TP1 for 25 contracts
    broker.register_exit("Ex_tp1", "L1", 25, limit=110.0, stop=95.0,
                         comment_profit="TP1", comment_loss="SL")
    tp_bar = Bar(datetime(2024, 1, 2, 14, 31, tzinfo=timezone.utc),
                 open=109.0, high=111.0, low=108.0, close=110.0, bar_index=1)
    broker.process_exits(tp_bar)

    assert broker.closedtrades_count == 1
    assert broker.opentrades_count == 1
    trade = broker.get_open_trades()[0]
    assert trade.remaining_qty == 25  # 50 - 25
    print("  [PASS] Broker partial close (25/50)")


def test_time_functions():
    # 2024-01-02 09:30:00 NY = 2024-01-02 14:30:00 UTC
    ts_ms = int(datetime(2024, 1, 2, 14, 30, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert pine_hour(ts_ms) == 9
    assert pine_minute(ts_ms) == 30
    assert pine_year(ts_ms) == 2024
    assert pine_month(ts_ms) == 1
    assert pine_dayofmonth(ts_ms) == 2
    # Jan 2 2024 = Tuesday. Pine: Sunday=1, Monday=2, Tuesday=3
    assert pine_dayofweek(ts_ms) == 3
    assert DAYOFWEEK_MONDAY == 2
    print("  [PASS] Time functions (NY timezone)")


def test_ta_pivothigh():
    s = Series()
    # Build a clear pivot high: 1, 3, 5, 3, 1
    for v in [1, 3, 5, 3, 1]:
        s.append(v)
    # pivothigh with left=2, right=2
    # Current bar is index 4 (value=1), pivot candidate is s[2]=5
    result = ta_pivothigh(s, 2, 2)
    assert result == 5.0
    print("  [PASS] ta.pivothigh")


def test_ta_pivotlow():
    s = Series()
    for v in [5, 3, 1, 3, 5]:
        s.append(v)
    result = ta_pivotlow(s, 2, 2)
    assert result == 1.0
    print("  [PASS] ta.pivotlow")


def test_ta_no_pivot():
    s = Series()
    for v in [1, 2, 3, 4, 5]:  # monotonic up, no pivot
        s.append(v)
    assert is_na(ta_pivothigh(s, 2, 2))
    assert is_na(ta_pivotlow(s, 2, 2))
    print("  [PASS] ta.pivot no detection on monotonic")


def test_ta_highest_lowest():
    s = Series()
    for v in [10, 20, 5, 30, 15]:
        s.append(v)
    assert ta_highest(s, 5) == 30
    assert ta_lowest(s, 5) == 5
    assert ta_highest(s, 2) == 30  # [0]=15, [1]=30
    assert ta_lowest(s, 2) == 15
    print("  [PASS] ta.highest / ta.lowest")


def test_strategy_api():
    api = StrategyAPI()
    api.order("Long_078", STRATEGY_LONG, qty=50, limit=100.0, comment="Long_078")
    assert len(api.broker.pending_orders) == 1

    bar = Bar(datetime(2024, 1, 2, 14, 31, tzinfo=timezone.utc),
              open=101.0, high=102.0, low=99.0, close=100.5, bar_index=1)
    api.process_bar(bar)
    assert int(api.opentrades) == 1
    assert api.opentrades.entry_comment(0) == "Long_078"
    assert api.opentrades.entry_price(0) == 100.0

    api.exit("Ex1", from_entry="Long_078", qty=50,
             limit=110.0, stop=95.0,
             comment_profit="TP1", comment_loss="SL1")

    tp_bar = Bar(datetime(2024, 1, 2, 14, 32, tzinfo=timezone.utc),
                 open=109.0, high=111.0, low=108.0, close=110.0, bar_index=2)
    api.process_bar(tp_bar)
    assert int(api.closedtrades) == 1
    assert api.closedtrades.exit_comment(0) == "TP1"
    print("  [PASS] Strategy API full cycle")


def test_strategy_cancel():
    api = StrategyAPI()
    api.order("Long_078", STRATEGY_LONG, qty=50, limit=100.0, comment="Long")
    api.order("Short_178", STRATEGY_SHORT, qty=50, limit=200.0, comment="Short")
    assert len(api.broker.pending_orders) == 2
    api.cancel("Short_178")
    assert len(api.broker.pending_orders) == 1
    assert "Long_078" in api.broker.pending_orders
    print("  [PASS] Strategy cancel")


if __name__ == "__main__":
    print("Running Phase 0 Foundation Tests...")
    print()
    print("NA Module:")
    test_na_basics()
    test_na_arithmetic()
    test_na_comparison()
    test_na_boolean()
    test_na_math()
    print()
    print("Series Module:")
    test_series_basic()
    test_series_max_lookback()
    test_series_highest_lowest()
    print()
    print("Broker Module:")
    test_broker_long_fill()
    test_broker_short_fill()
    test_broker_gap_fill()
    test_broker_exit_tp()
    test_broker_exit_sl()
    test_broker_partial_close()
    print()
    print("Built-in Functions:")
    test_time_functions()
    test_ta_pivothigh()
    test_ta_pivotlow()
    test_ta_no_pivot()
    test_ta_highest_lowest()
    print()
    print("Strategy API:")
    test_strategy_api()
    test_strategy_cancel()
    print()
    print("═══ ALL PHASE 0 TESTS PASSED ═══")
