from datetime import datetime, timedelta

import pytest

from pine_engine.engine import compile_pine, run_backtest
from pine_engine.runtime.broker import Bar


def _bars(n=12):
    t0 = datetime(2026, 1, 5, 14, 30)
    return [Bar(t0 + timedelta(minutes=i), 100 + i, 101 + i, 99 + i, 100.5 + i, i) for i in range(n)]


def test_security_lookahead_off_constant():
    src = '''//@version=5
strategy("t")
c5 = request.security(syminfo.tickerid, "5", close, lookahead=barmerge.lookahead_off)
if bar_index == 6 and c5 == 104.5
    strategy.order("L", strategy.long, qty=1, limit=close)
    strategy.exit("X", from_entry="L", qty=1, limit=close + 2, stop=close - 50)
'''
    trades = run_backtest(compile_pine(src), _bars())
    assert len(trades) == 1


def test_security_lookahead_on_rejected():
    src = '''//@version=5
strategy("t")
c5 = request.security(syminfo.tickerid, "5", close, lookahead=barmerge.lookahead_on)
'''
    with pytest.raises(ValueError):
        run_backtest(compile_pine(src), _bars())
