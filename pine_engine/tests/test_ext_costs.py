"""Tests Paket P9 — nq.cost_* / nq.fill_* (pine_engine/ext/costs.py).

Alle Handels-Tests laufen ueber compile_pine + Bar-Schleife (identisch zu
run_backtest, zusaetzlich wird ctx zurueckgegeben) mit nachgerechneten Preisen.
Grundszenario: Long-Limit 100 (qty 2), TP 110, SL 95; Punktwert 20 $/Punkt.
"""

import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from datetime import datetime, timedelta

import pytest

from pine_engine.engine import compile_pine, run_backtest, RuntimeContext
from pine_engine.runtime.broker import Bar

T0 = datetime(2026, 1, 5, 14, 30)


def _src(cfg: str = '', extra: str = '') -> str:
    return f'''//@version=5
strategy("t")
var float net = 0.0
{cfg}
if bar_index == 0
    strategy.order("L", strategy.long, qty=2, limit=100)
strategy.exit("X", from_entry="L", qty=2, limit=110, stop=95)
{extra}
net := nq.cost_net_pnl
'''


def _bars(rows):
    return [Bar(T0 + timedelta(minutes=i), o, h, l, c, i)
            for i, (o, h, l, c) in enumerate(rows)]


def _run(src, rows):
    """Wie run_backtest, liefert zusaetzlich ctx."""
    c = compile_pine(src)
    ctx = RuntimeContext(params=c.get_default_params())
    c.initialize(ctx)
    for bar in _bars(rows):
        ctx.strategy.process_bar(bar)
        ctx.update_bar(bar)
        c.execute_bar(ctx)
        ctx.strategy.process_entrybar_exits()
    return ctx.strategy.get_results(), ctx


# b0 Order; b1 Fuellung 100 (kein Gap); b2 TP 110
TP_ROWS = [(105, 106, 104, 105), (104, 104, 99, 101), (102, 111, 101, 109),
           (109, 109, 108, 108)]
# b2 SL 95 (kein Gap)
SL_ROWS = [(105, 106, 104, 105), (104, 104, 99, 101), (100, 101, 94, 95),
           (95, 96, 94, 95)]
# b1 Gap-Open 99 unter dem Limit -> Broker fuellt zum Open 99
GAP_ROWS = [(105, 106, 104, 105), (99, 102, 98, 101), (102, 111, 101, 109)]


def _one(trades):
    assert len(trades) == 1
    return trades[0]


# ── Standard bleibt unveraendert ─────────────────────────────────────────

def test_default_unchanged_and_no_hook():
    trades, ctx = _run(_src(), TP_ROWS)
    t = _one(trades)
    assert (t.entry_price, t.exit_price, t.qty) == (100, 110, 2)
    assert not {'cost_points', 'cost_usd', 'fill_adj_points'} & set(t.extra)
    assert ctx.strategy.broker.get_hook('nq.costs') is None
    assert ctx.v_net == pytest.approx(10 * 2 * 20)      # 400 $ brutto = netto
    # identisch ueber run_backtest
    t2 = _one(run_backtest(compile_pine(_src()), _bars(TP_ROWS)))
    assert (t2.entry_price, t2.exit_price) == (100, 110)


# ── 1. nq.cost_points ────────────────────────────────────────────────────

def test_cost_points_booked_not_in_price():
    trades = run_backtest(compile_pine(_src('nq.cost_points(2)')), _bars(TP_ROWS))
    t = _one(trades)
    assert (t.entry_price, t.exit_price) == (100, 110)
    assert t.extra['cost_points'] == pytest.approx(2.0)
    assert t.extra['cost_usd'] == pytest.approx(2 * 2 * 20)   # 80 $
    assert t.extra['fill_adj_points'] == pytest.approx(0.0)


def test_cost_net_pnl():
    _, ctx = _run(_src('nq.cost_points(2)'), TP_ROWS)
    assert ctx.v_net == pytest.approx(400 - 80)          # 320 $


def test_idempotent_single_hook():
    _, ctx = _run(_src('nq.cost_points(2)\nnq.cost_points(2)'), TP_ROWS)
    assert sum(getattr(h, 'key', '') == 'nq.costs' for h in ctx.strategy.broker.hooks) == 1


# ── 2. nq.cost_commission ────────────────────────────────────────────────

def test_commission_plus_points():
    t = _one(_run(_src('nq.cost_points(1)\nnq.cost_commission(4.5)'), TP_ROWS)[0])
    assert t.extra['cost_points'] == pytest.approx(1 + 4.5 / 20)   # 1.225 Pkt
    assert t.extra['cost_usd'] == pytest.approx(1.225 * 2 * 20)    # 49 $


# ── 3./4. Slippage ──────────────────────────────────────────────────────

def test_slippage_not_on_pure_limits():
    t = _one(_run(_src('nq.fill_slippage(1, 1)'), TP_ROWS)[0])
    assert (t.entry_price, t.exit_price) == (100, 110)


def test_slippage_on_limits_flag():
    trades, ctx = _run(_src('nq.fill_slippage(1, 1, limits=true)'), TP_ROWS)
    t = _one(trades)
    assert (t.entry_price, t.exit_price) == (101, 109)
    assert t.extra['fill_adj_points'] == pytest.approx(2.0)
    assert ctx.v_net == pytest.approx(8 * 2 * 20)        # 320 $, Kosten im Preis


def test_slippage_on_stop():
    t = _one(_run(_src('nq.fill_slippage(1, 1)'), SL_ROWS)[0])
    assert (t.entry_price, t.exit_price) == (100, 94)


def test_stop_slippage_additive():
    t = _one(_run(_src('nq.fill_slippage(1, 1)\nnq.fill_stop_slippage(0.5)'), SL_ROWS)[0])
    assert t.exit_price == pytest.approx(93.5)
    t = _one(_run(_src('nq.fill_stop_slippage(0.75)'), SL_ROWS)[0])
    assert (t.entry_price, t.exit_price) == (100, 94.25)
    # TP bleibt von Stop-Slippage unberuehrt
    t = _one(_run(_src('nq.fill_stop_slippage(0.75)'), TP_ROWS)[0])
    assert t.exit_price == 110


def test_slippage_gap_entry_capped_at_limit():
    t = _one(_run(_src('nq.fill_slippage(0.5, 0)'), GAP_ROWS)[0])
    assert t.entry_price == pytest.approx(99.5)            # Open 99 + 0.5
    t = _one(_run(_src('nq.fill_slippage(3, 0)'), GAP_ROWS)[0])
    assert t.entry_price == pytest.approx(100)             # nie schlechter als Limit


def test_slippage_on_close_all():
    extra = 'if bar_index == 2\n    strategy.close_all(comment="EOD")'
    rows = [(105, 106, 104, 105), (104, 104, 99, 101), (102, 104, 101, 105)]
    t = _one(_run(_src('nq.fill_slippage(0, 2)', extra), rows)[0])
    assert t.exit_comment == 'EOD'
    assert t.exit_price == pytest.approx(103)              # Close 105 - 2
    assert t.extra['fill_adj_points'] == pytest.approx(2.0)


# ── 5. nq.fill_spread ────────────────────────────────────────────────────

def test_spread_half_each_side():
    t = _one(_run(_src('nq.fill_spread(1)'), TP_ROWS)[0])
    assert (t.entry_price, t.exit_price) == (100.5, 109.5)
    assert t.extra['fill_adj_points'] == pytest.approx(1.0)


# ── 6. nq.fill_trade_through ─────────────────────────────────────────────

TT_ROWS = [(105, 106, 104, 105),
           (104, 104, 99.75, 101),   # nur 1 Tick durch -> keine Fuellung
           (101, 102, 99.5, 101),    # 2 Ticks durch -> Fuellung 100
           (102, 111, 101, 109)]


def test_trade_through_entry():
    base = _one(_run(_src(), TT_ROWS)[0])
    assert base.entry_time == T0 + timedelta(minutes=1)
    t = _one(_run(_src('nq.fill_trade_through(2)'), TT_ROWS)[0])
    assert t.entry_time == T0 + timedelta(minutes=2)
    assert (t.entry_price, t.exit_price) == (100, 110)


def test_trade_through_gap_open_fills_at_open():
    t = _one(_run(_src('nq.fill_trade_through(8)'), GAP_ROWS)[0])
    assert t.entry_price == 99


# ── 7. nq.fill_tp_trade_through ──────────────────────────────────────────

TPTT_ROWS = [(105, 106, 104, 105), (104, 104, 99, 101),
             (102, 110.25, 101, 109),   # TP nur 1 Tick durch -> kein TP
             (109, 110.5, 108, 110),    # 2 Ticks -> TP zum Limit 110
             (110, 110, 109, 109)]


def test_tp_trade_through():
    base = _one(_run(_src(), TPTT_ROWS)[0])
    assert base.exit_time == T0 + timedelta(minutes=2)
    trades, ctx = _run(_src('nq.fill_tp_trade_through(2)'), TPTT_ROWS)
    t = _one(trades)
    assert t.exit_time == T0 + timedelta(minutes=3)
    assert t.exit_price == 110
    # Spec wieder auf Original-Limit zurueckgestellt
    assert all(s['limit'] == 110 for s in ctx.strategy.broker.exit_orders.values())


# ── 8. nq.fill_round_tick ────────────────────────────────────────────────

def test_round_tick_adverse():
    t = _one(_run(_src('nq.fill_slippage(0.1, 0.1, limits=true)\nnq.fill_round_tick()'),
                  TP_ROWS)[0])
    assert (t.entry_price, t.exit_price) == (100.25, 109.75)
    t = _one(_run(_src('nq.fill_round_tick()'), TP_ROWS)[0])   # schon auf Tick
    assert (t.entry_price, t.exit_price) == (100, 110)


# ── 10. nq.cost_off ──────────────────────────────────────────────────────

def test_cost_off():
    cfg = 'if bar_index == 0\n    nq.cost_points(2)\nif bar_index == 1\n    nq.cost_off()'
    trades, ctx = _run(_src(cfg), TP_ROWS)
    t = _one(trades)
    assert 'cost_points' not in t.extra
    assert ctx.strategy.broker.get_hook('nq.costs') is None
    assert ctx.v_net == pytest.approx(400)


def test_negative_rejected():
    with pytest.raises(Exception):
        _run(_src('nq.cost_points(-1)'), TP_ROWS)


# ── Erweiterte Orderarten (strategy.entry Market, TP per profit-Ticks) ──

def _src_entry(cfg: str, exit_args: str) -> str:
    return f'''//@version=5
strategy("t")
{cfg}
if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
strategy.exit("X", from_entry="L", {exit_args})
'''


def test_market_entry_slippage():
    # Market-Order aus Bar 0 fuellt zum Open von Bar 1 (104) -> +1 Slippage = 105
    t = _one(_run(_src_entry('nq.fill_slippage(1, 0)', 'limit=110, stop=95'), TP_ROWS)[0])
    assert (t.entry_price, t.exit_price) == (105, 110)
    t = _one(_run(_src_entry('', 'limit=110, stop=95'), TP_ROWS)[0])
    assert t.entry_price == 104


def test_gap_tp_slippage_capped():
    rows = [(105, 106, 104, 105), (104, 104, 99, 101), (112, 113, 111, 112)]
    t = _one(_run(_src(), rows)[0])
    assert t.exit_price == 112                                    # Gap: TP zum Open
    t = _one(_run(_src('nq.fill_slippage(0, 1)'), rows)[0])
    assert t.exit_price == 111
    t = _one(_run(_src('nq.fill_slippage(0, 5)'), rows)[0])
    assert t.exit_price == 110                                    # nie schlechter als TP


def test_tp_trade_through_profit_ticks():
    # Market-Einstieg zum Open 104; profit=24 Ticks = 6 Pkt -> TP 110
    rows = [(105, 106, 104, 105), (104, 104, 99, 101),
            (102, 110.25, 101, 109), (109, 110.5, 108, 110), (110, 110, 109, 109)]
    base = _one(_run(_src_entry('', 'profit=24, loss=40'), rows)[0])
    assert (base.exit_price, base.exit_time) == (110, T0 + timedelta(minutes=2))
    trades, ctx = _run(_src_entry('nq.fill_tp_trade_through(2)', 'profit=24, loss=40'), rows)
    t = _one(trades)
    assert (t.exit_price, t.exit_time) == (110, T0 + timedelta(minutes=3))
