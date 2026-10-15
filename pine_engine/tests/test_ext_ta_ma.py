"""Tests Paket P2: ta.* Durchschnitte + Volatilitaet (pine_engine/ext/ta_ma.py).

Alle Referenzwerte von Hand nachgerechnet (siehe Kommentare).
Bars (o, h, l, c):
  0: 10 12  9 11
  1: 11 13 10 12
  2: 12 15 11 14
  3: 14 14 12 13
  4: 13 16 13 15
  5: 15 17 14 16
True Range (Vorclose): bar0 na (handle_na: 3), 3, 4, 2, 3, 3
"""

import math
from datetime import datetime, timedelta

import pytest

from pine_engine.engine import compile_pine, run_backtest, RuntimeContext
from pine_engine.runtime.broker import Bar
from pine_engine.runtime.na import is_na

OHLC = [(10, 12, 9, 11), (11, 13, 10, 12), (12, 15, 11, 14),
        (14, 14, 12, 13), (13, 16, 13, 15), (15, 17, 14, 16)]


def _bars(ohlc):
    t0 = datetime(2026, 1, 5, 14, 30)
    return [Bar(t0 + timedelta(minutes=i), o, h, l, c, i)
            for i, (o, h, l, c) in enumerate(ohlc)]


def _run(body, names, ohlc=OHLC):
    """Fuehrt Pine aus und sammelt je Bar die var-Werte ctx.v_<name>."""
    decl = '\n'.join(f'var float {n} = na' for n in names)
    src = f'//@version=5\nstrategy("t")\n{decl}\n{body}\n'
    c = compile_pine(src)
    ctx = RuntimeContext(params=c.get_default_params())
    c.initialize(ctx)
    out = {n: [] for n in names}
    for bar in _bars(ohlc):
        ctx.strategy.process_bar(bar)
        ctx.update_bar(bar)
        c.execute_bar(ctx)
        for n in names:
            out[n].append(getattr(ctx, f'v_{n}'))
    return out


def _eq(got, exp):
    assert len(got) == len(exp)
    for g, e in zip(got, exp):
        if e is None:
            assert is_na(g), (got, exp)
        else:
            assert g == pytest.approx(e, abs=1e-9), (got, exp)


N2 = [None, None]


def test_sma():
    r = _run('x := ta.sma(close, 3)', ['x'])
    _eq(r['x'], N2 + [37 / 3, 13, 14, 44 / 3])


def test_ema_sma_seed():
    # alpha=0.5; Seed = SMA(11,12,14)=37/3; dann 0.5*src + 0.5*prev
    r = _run('x := ta.ema(close, 3)', ['x'])
    e2 = 37 / 3
    e3 = 0.5 * 13 + 0.5 * e2
    e4 = 0.5 * 15 + 0.5 * e3
    e5 = 0.5 * 16 + 0.5 * e4
    _eq(r['x'], N2 + [e2, e3, e4, e5])
    assert e5 == pytest.approx(14.916666666666666)


def test_rma():
    # alpha=1/3: 37/3, 113/9, 361/27, 1154/81
    r = _run('x := ta.rma(close, 3)', ['x'])
    _eq(r['x'], N2 + [37 / 3, 113 / 9, 361 / 27, 1154 / 81])


def test_wma():
    # Gewichte 1,2,3 (neuester 3), Summe 6
    r = _run('x := ta.wma(close, 3)', ['x'])
    _eq(r['x'], N2 + [77 / 6, 79 / 6, 85 / 6, 91 / 6])


def test_hma():
    # n=4: wma(2*wma(c,2)-wma(c,4), 2); diff bar3=413/30, bar4=443/30, bar5:
    # wma2=(15+32)/3=47/3, wma4=(14+26+45+64)/10=14.9 -> 94/3-14.9=(940-447)/30=493/30
    r = _run('x := ta.hma(close, 4)', ['x'])
    h4 = (413 / 30 + 2 * 443 / 30) / 3
    h5 = (443 / 30 + 2 * 493 / 30) / 3
    _eq(r['x'], [None] * 4 + [h4, h5])
    assert h4 == pytest.approx(1299 / 90)


def test_tr_variable_and_function():
    r = _run('a := ta.tr\nb := ta.tr(true)\nc := ta.tr(false)', ['a', 'b', 'c'])
    _eq(r['a'], [None, 3, 4, 2, 3, 3])
    _eq(r['b'], [3, 3, 4, 2, 3, 3])
    _eq(r['c'], [None, 3, 4, 2, 3, 3])


def test_atr():
    # rma(tr(true),3): tr=3,3,4,2,3,3 -> 10/3, 26/9, 79/27, 239/81
    r = _run('x := ta.atr(3)', ['x'])
    _eq(r['x'], N2 + [10 / 3, 26 / 9, 79 / 27, 239 / 81])


def test_stdev_biased_and_unbiased():
    # Fenster 11,12,14: Summe Abw.^2 = 42/9 -> biased sqrt(14/9), unbiased sqrt(7/3)
    r = _run('a := ta.stdev(close, 3)\nb := ta.stdev(close, 3, false)', ['a', 'b'])
    assert r['a'][2] == pytest.approx(math.sqrt(14 / 9))
    assert r['b'][2] == pytest.approx(math.sqrt(7 / 3))
    # Fenster 12,14,13: m=13, Abw.^2 = 1+1+0=2 -> sqrt(2/3)
    assert r['a'][3] == pytest.approx(math.sqrt(2 / 3))
    assert is_na(r['a'][1])


def test_dev():
    # 11,12,14: m=37/3, |Abw.| 4/3+1/3+5/3=10/3 -> 10/9 ; 12,14,13: 2/3
    r = _run('x := ta.dev(close, 3)', ['x'])
    _eq(r["x"], N2 + [10 / 9, 2 / 3, 2 / 3, 10 / 9])  # 14,13,15: 2/3; 13,15,16: (5/3+1/3+4/3)/3


def test_change_mom_roc():
    r = _run('a := ta.change(close)\nb := ta.change(close, 2)\n'
             'c := ta.mom(close, 2)\nd := ta.roc(close, 2)', ['a', 'b', 'c', 'd'])
    _eq(r['a'], [None, 1, 2, -1, 2, 1])
    _eq(r['b'], N2 + [3, 1, 1, 3])
    _eq(r['c'], N2 + [3, 1, 1, 3])
    _eq(r['d'], N2 + [300 / 11, 100 / 12, 100 / 14, 300 / 13])


def test_expression_source():
    # high-low = 3,3,4,2,3,3 ; ema alpha 0.5: 10/3, 8/3, 17/6, 35/12
    r = _run('x := ta.ema(high - low, 3)', ['x'])
    _eq(r['x'], N2 + [10 / 3, 8 / 3, 17 / 6, 35 / 12])


def test_two_call_sites_independent():
    # a: jede Bar; b: identischer Aufruf, aber erst ab bar 2 -> eigener Seed
    # SMA(14,13,15)=14 in bar 4, dann 0.5*16+0.5*14=15
    body = ('a := ta.ema(close, 3)\n'
            'if bar_index >= 2\n'
            '    b := ta.ema(close, 3)\n'
            'c := ta.sma(close, 2)\n'
            'd := ta.sma(open, 2)')
    r = _run(body, ['a', 'b', 'c', 'd'])
    _eq(r['b'], [None] * 4 + [14, 15])
    assert r['a'][4] == pytest.approx(0.5 * 15 + 0.5 * (0.5 * 13 + 0.5 * 37 / 3))
    _eq(r['c'], [None, 11.5, 13, 13.5, 14, 15.5])
    _eq(r['d'], [None, 10.5, 11.5, 13, 13.5, 14])


def test_same_site_twice_per_bar_no_double_step():
    # Zustands-Funktion in einer Schleife -> gleiche Aufrufstelle, gleiche Bar:
    # darf nicht doppelt fortschreiten (Ergebnis == Einfachaufruf)
    body = ('for i = 0 to 1\n'
            '    x := ta.ema(close, 3)\n'
            'y := ta.ema(close, 3)')
    r = _run(body, ['x', 'y'])
    _eq(r['x'], [None if is_na(v) else v for v in r['y']])
    assert r['x'][5] == pytest.approx(r['y'][5])


def test_trade_with_atr_exit():
    # ATR(3) in bar 2 = 10/3. Limit-Long @14 (Fill bar 3, open 14),
    # TP = 14 + 10/3 = 17.3333 -> getroffen in bar 6 (high 18)
    src = '''//@version=5
strategy("t")
a = ta.atr(3)
if bar_index == 2
    strategy.order("L", strategy.long, qty=1, limit=close)
    strategy.exit("X", from_entry="L", qty=1, limit=close + a, stop=close - a)
'''
    trades = run_backtest(compile_pine(src), _bars(OHLC + [(16, 18, 15, 17)]))
    assert len(trades) == 1
    t = trades[0]
    assert t.entry_price == pytest.approx(14)
    assert t.exit_price == pytest.approx(14 + 10 / 3)


def test_invalid_length():
    with pytest.raises(Exception):
        _run('x := ta.sma(close, 0)', ['x'])
