"""Tests fuer pine_engine/ext/strategy_vars.py (Paket P1c)."""

from datetime import datetime, timedelta

from pine_engine.engine import compile_pine, run_backtest, RuntimeContext
from pine_engine.runtime.broker import Bar, ClosedTrade
from pine_engine.runtime.na import is_na
from pine_engine.data.loader import bar_timestamp_ms

# 2026-01-06 04:55 UTC = 2026-01-05 23:55 New York (EST). NY-Mitternacht = Bar 5.
T0 = datetime(2026, 1, 6, 4, 55)

OHLC = [
    (100, 101, 99, 100),   # 0
    (100, 101, 99, 100),   # 1  Order L (2 Kontrakte, limit 100) + Exits
    (100, 102, 99, 101),   # 2  L fuellt bei 100
    (101, 106, 100, 104),  # 3  X  TP 105 (1 Kontrakt)  -> +5 Pkt = +100 $
    (104, 104, 94, 95),    # 4  X2 SL 95  (1 Kontrakt)  -> -5 Pkt = -100 $
    (95, 96, 94, 95),      # 5  NY 00:00 (neuer Tag), Order M (1, limit 95)
    (95, 96, 94, 95),      # 6  M fuellt bei 95
    (96, 98, 95, 97),      # 7  strategy.close("M") zum Close 97 -> +2 Pkt = +40 $
    (97, 98, 96, 97),      # 8
]

SRC = '''//@version=5
strategy("t")
var float ps = 0.0
var float avg = 0.0
var float op = 0.0
var float np = 0.0
var float gp = 0.0
var float gl = 0.0
var float wt = 0.0
var float lt = 0.0
var float et = 0.0
var float mdd = 0.0
var float mru = 0.0
var float ic = 0.0
var float day = 0.0
var float osz = 0.0
var float oet = 0.0
var float obi = 0.0
var float cep = 0.0
var float cxp = 0.0
var float cet = 0.0
var float cxt = 0.0
var float cfi = -1.0
var float crun = 0.0
if bar_index == 1
    strategy.order("L", strategy.long, qty=2, limit=100)
    strategy.exit("X", from_entry="L", qty=1, limit=105, stop=95)
    strategy.exit("X2", from_entry="L", qty=1, limit=110, stop=95)
if bar_index == 5
    strategy.order("M", strategy.long, qty=1, limit=95)
if bar_index == 7
    strategy.close("M")
ps := strategy.position_size
avg := strategy.position_avg_price
op := strategy.openprofit
np := strategy.netprofit
gp := strategy.grossprofit
gl := strategy.grossloss
wt := strategy.wintrades
lt := strategy.losstrades
et := strategy.eventrades
mdd := strategy.max_drawdown
mru := strategy.max_runup
ic := strategy.initial_capital
day := nq.day_netprofit
osz := strategy.opentrades.size(0)
oet := strategy.opentrades.entry_time(0)
obi := strategy.opentrades.entry_bar_index(0)
cep := strategy.closedtrades.entry_price(0)
cxp := strategy.closedtrades.exit_price(1)
cet := strategy.closedtrades.entry_time(0)
cxt := strategy.closedtrades.exit_time(1)
cfi := strategy.closedtrades.first_index
crun := strategy.closedtrades.max_runup(0)
'''

NAMES = ['ps', 'avg', 'op', 'np', 'gp', 'gl', 'wt', 'lt', 'et', 'mdd', 'mru', 'ic',
         'day', 'osz', 'oet', 'obi', 'cep', 'cxp', 'cet', 'cxt', 'cfi', 'crun']


def _bars(ohlc=OHLC, t0=T0):
    return [Bar(t0 + timedelta(minutes=i), o, h, l, c, i)
            for i, (o, h, l, c) in enumerate(ohlc)]


def _run_snap(src, bars):
    """Wie run_backtest, aber mit Momentaufnahme aller ctx.v_* nach jeder Bar."""
    c = compile_pine(src)
    ctx = RuntimeContext(params=c.get_default_params())
    c.initialize(ctx)
    snaps = []
    for bar in bars:
        ctx.strategy.process_bar(bar)
        ctx.update_bar(bar)
        c.execute_bar(ctx)
        ctx.strategy.process_entrybar_exits()
        snaps.append({n: getattr(ctx, 'v_' + n) for n in NAMES if hasattr(ctx, 'v_' + n)})
    return ctx, snaps


def test_generated_code_routes_to_registry():
    py = compile_pine(SRC).python_code
    assert "ctx.ext_call('strategy.closedtrades.entry_price'" in py
    assert "ctx.ext_call('strategy.opentrades.entry_bar_index'" in py
    assert "ctx.ext_var('strategy.netprofit'" in py
    assert "ctx.ext_var('nq.day_netprofit'" in py


def test_full_scenario_values():
    bars = _bars()
    ctx, s = _run_snap(SRC, bars)
    trades = ctx.strategy.broker.closed_trades
    assert [(t.entry_price, t.exit_price, t.qty) for t in trades] == \
        [(100, 105, 1), (100, 95, 1), (95, 97, 1)]

    # Bar 1: flat, nichts geschlossen
    assert s[1]['ps'] == 0 and is_na(s[1]['avg']) and s[1]['op'] == 0
    assert is_na(s[1]['osz']) and is_na(s[1]['cep'])
    assert s[1]['ic'] == 100000.0 and s[1]['cfi'] == 0

    # Bar 2: long 2 @100, Close 101 -> openprofit 1 Pkt x 2 x 20 $ = 40 $
    assert s[2]['ps'] == 2 and s[2]['avg'] == 100 and s[2]['op'] == 40.0
    assert s[2]['osz'] == 2
    assert s[2]['oet'] == bar_timestamp_ms(bars[2])
    assert s[2]['obi'] == 2

    # Bar 3: TP 105 fuer 1 Kontrakt -> +100 $; Rest 1 @100, Close 104 -> +80 $ offen
    assert s[3]['ps'] == 1 and s[3]['op'] == 80.0
    assert s[3]['np'] == 100.0 and s[3]['gp'] == 100.0 and s[3]['gl'] == 0.0
    assert s[3]['wt'] == 1 and s[3]['lt'] == 0
    assert s[3]['cep'] == 100 and s[3]['cet'] == bar_timestamp_ms(bars[2])
    assert s[3]['obi'] == 2   # entry_bar_index bleibt die Fuellbar
    assert s[3]['day'] == 100.0   # NY-Tag 2026-01-05
    assert is_na(s[3]['crun'])    # kein MFE-Plugin -> na

    # Bar 4: SL 95 -> -100 $; netto 0, Drawdown 100 $, Runup 100 $
    assert s[4]['ps'] == 0 and s[4]['op'] == 0
    assert s[4]['np'] == 0.0 and s[4]['gp'] == 100.0 and s[4]['gl'] == 100.0
    assert s[4]['wt'] == 1 and s[4]['lt'] == 1 and s[4]['et'] == 0
    assert s[4]['mdd'] == 100.0 and s[4]['mru'] == 100.0
    assert s[4]['cxp'] == 95 and s[4]['cxt'] == bar_timestamp_ms(bars[4])
    assert s[4]['day'] == 0.0

    # Bar 5: NY-Mitternacht -> neuer Handelstag, day_netprofit = 0
    assert s[5]['day'] == 0.0 and s[5]['np'] == 0.0

    # Bar 7: strategy.close("M") zum Close 97 -> +2 Pkt x 20 $ = +40 $
    assert s[7]['np'] == 40.0 and s[7]['day'] == 40.0 and s[7]['wt'] == 2
    assert s[7]['mru'] == 100.0 and s[7]['mdd'] == 100.0
    assert s[8]['day'] == 40.0


def test_short_position_size_and_openprofit():
    src = '''//@version=5
strategy("t")
var float ps = 0.0
var float op = 0.0
var float osz = 0.0
if bar_index == 0
    strategy.order("S", strategy.short, qty=3, limit=100)
ps := strategy.position_size
op := strategy.openprofit
osz := strategy.opentrades.size(0)
'''
    ohlc = [(99, 100, 98, 99), (99, 101, 98, 98), (98, 99, 96, 97)]
    ctx, s = _run_snap(src, _bars(ohlc))
    # Short 3 @100 (Bar 1, Open 99 < limit -> 100). Close 98 -> 2 Pkt x 3 x 20 = 120 $
    assert s[1]['ps'] == -3 and s[1]['osz'] == -3 and s[1]['op'] == 120.0
    assert s[2]['op'] == 180.0


def test_day_netprofit_gates_trading():
    """Handelbar: Tagesverlust-Sperre ueber nq.day_netprofit.

    Jede Bar (wenn flat) Long 1 @ Close, Stop 2 Pkt tiefer. Fallende Bars
    stoppen jeden Trade mit -2 Pkt x 20 $ = -40 $. Sperre ab <= -80 $ ->
    genau 2 Trades, danach keine neuen Orders mehr.
    """
    src = '''//@version=5
strategy("t")
if strategy.position_size == 0 and nq.day_netprofit > -80
    strategy.order("L", strategy.long, qty=1, limit=close)
    strategy.exit("X", from_entry="L", qty=1, limit=close+50, stop=close-2)
'''
    ohlc = []
    px = 100.0
    for i in range(12):
        ohlc.append((px, px + 0.5, px - 3, px - 3))
        px -= 3
    # Zeitraum mitten im NY-Tag: 15:00 UTC
    trades = run_backtest(compile_pine(src), _bars(ohlc, datetime(2026, 1, 5, 15, 0)))
    assert len(trades) == 2
    assert all((t.exit_price - t.entry_price) * t.qty * 20 == -40 for t in trades)

    # Kontrolle ohne Sperre: mehr Trades
    src_free = src.replace(' and nq.day_netprofit > -80', '')
    trades_free = run_backtest(compile_pine(src_free), _bars(ohlc, datetime(2026, 1, 5, 15, 0)))
    assert len(trades_free) > 2


def test_eventrades_and_closed_mfe_direct():
    """Direkter Aufruf: Break-even-Trade zaehlt als eventrade; MFE/MAE aus extra."""
    from pine_engine.runtime import ext
    ext.load_all()
    ctx = RuntimeContext()
    b = ctx.strategy.broker
    t = datetime(2026, 1, 5, 15, 0)
    b.closed_trades.append(ClosedTrade('A', 'long', 2, 100, 100, '', 'be', t, t))
    b.closed_trades.append(ClosedTrade('B', 'short', 1, 100, 103, '', 'sl', t, t,
                                       extra={'mfe': 4.0, 'mae': 3.0}))
    b._current_bar_time = t
    assert ext.VARIABLES['strategy.eventrades'](ctx, {}) == 1
    assert ext.VARIABLES['strategy.losstrades'](ctx, {}) == 1
    assert ext.VARIABLES['strategy.netprofit'](ctx, {}) == -60.0
    assert ext.VARIABLES['strategy.max_drawdown'](ctx, {}) == 60.0
    assert ext.VARIABLES['strategy.max_runup'](ctx, {}) == 0.0
    assert ext.VARIABLES['nq.day_netprofit'](ctx, {}) == -60.0
    run = ext.REGISTRY['strategy.closedtrades.max_runup'].fn
    dd = ext.REGISTRY['strategy.closedtrades.max_drawdown'].fn
    assert is_na(run(ctx, {}, 0))
    assert run(ctx, {}, 1) == 80.0      # 4 Pkt x 1 x 20 $
    assert dd(ctx, {}, 1) == 60.0       # 3 Pkt x 1 x 20 $
    assert is_na(dd(ctx, {}, 5))


def test_no_call_no_change():
    """Ohne neue Namen: identische Trades wie Skript ohne jede Kennzahl."""
    base = '''//@version=5
strategy("t")
if bar_index == 1
    strategy.order("L", strategy.long, qty=2, limit=100)
    strategy.exit("X", from_entry="L", qty=1, limit=105, stop=95)
    strategy.exit("X2", from_entry="L", qty=1, limit=110, stop=95)
'''
    a = run_backtest(compile_pine(base), _bars())
    b = run_backtest(compile_pine(SRC), _bars())
    key = lambda ts: [(t.entry_id, t.entry_price, t.exit_price, t.qty, t.exit_time) for t in ts]
    assert key(a) == key(b)[:2]
