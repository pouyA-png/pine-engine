"""Tests fuer P3 — ta.*-Hilfsfunktionen und Oszillatoren (pine_engine/ext/ta_util.py).

Erwartungswerte sind von Hand nachgerechnet (Kommentare zeigen die Rechnung).
"""

import math
import sys
import pathlib
from datetime import datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest

from pine_engine.runtime import ext as _ext
from pine_engine.runtime.na import NA, is_na
from pine_engine.engine import compile_pine, run_backtest
from pine_engine.runtime.broker import Bar

_ext.load_all()


def run(name, *arg_lists, **kw):
    """Ruft ein ext-Builtin Bar fuer Bar mit einer Aufrufstelle auf."""
    fn = _ext.REGISTRY[name].fn
    state = {}
    out = []
    for i, args in enumerate(zip(*arg_lists)):
        state['_bar_idx'] = i
        out.append(fn(None, state, *args, **kw))
    return out


def same(got, exp, tol=1e-9):
    assert len(got) == len(exp), (got, exp)
    for g, e in zip(got, exp):
        if is_na(e):
            assert is_na(g), (got, exp)
        elif isinstance(e, bool):
            assert g is e, (got, exp)
        else:
            assert not is_na(g) and abs(g - e) < tol, (got, exp)


def const(v, n):
    return [v] * n


# ── 1. barssince ──

def test_barssince():
    c = [False, True, False, False, True, False]
    same(run('ta.barssince', c), [NA, 0, 1, 2, 0, 1])


def test_barssince_na_cond_is_false_and_same_bar_recalc():
    fn = _ext.REGISTRY['ta.barssince'].fn
    st = {'_bar_idx': 0}
    assert fn(None, st, True) == 0
    st['_bar_idx'] = 1
    assert fn(None, st, NA) == 1
    assert fn(None, st, NA) == 1          # zweiter Aufruf in derselben Bar: kein Doppelzaehlen
    assert fn(None, st, True) == 0        # Neuberechnung in derselben Bar
    st['_bar_idx'] = 2
    assert fn(None, st, False) == 1


# ── 2. valuewhen ──

def test_valuewhen():
    c = [True, False, True, False, True]
    s = [10, 11, 12, 13, 14]
    same(run('ta.valuewhen', c, s, const(0, 5)), [10, 10, 12, 12, 14])
    same(run('ta.valuewhen', c, s, const(1, 5)), [NA, NA, 10, 10, 12])
    same(run('ta.valuewhen', [False, False], [1, 2], [0, 0]), [NA, NA])


# ── 3. cum ──

def test_cum():
    same(run('ta.cum', [1, 2, NA, 3]), [1, 3, 3, 6])


# ── 4. cross ──

def test_cross():
    # a: 1 -> 3 kreuzt 2 nach oben, 3 -> 1 nach unten, 1 -> 1 nichts
    same(run('ta.cross', [1, 3, 1, 1], const(2, 4)), [False, True, True, False])
    # Beruehren (2 == 2) ist noch kein Kreuzen, erst 2 -> 3
    same(run('ta.cross', [1, 2, 3], const(2, 3)), [False, False, True])


# ── 5. rising / falling ──

def test_rising_falling():
    s = [1, 2, 3, 3, 4, 5]
    same(run('ta.rising', s, const(2, 6)), [False, False, True, False, True, True])
    f = [5, 4, 3, 3, 2, 1]
    same(run('ta.falling', f, const(2, 6)), [False, False, True, False, True, True])


# ── 6. highestbars / lowestbars ──

def test_highest_lowest_bars():
    s = [1, 5, 2, 3, 1]
    same(run('ta.highestbars', s, const(3, 5)), [NA, NA, -1, -2, -1])
    same(run('ta.lowestbars', s, const(3, 5)), [NA, NA, -2, -1, 0])
    # Gleichstand: juengste Bar gewinnt -> 0
    same(run('ta.highestbars', [4, 4, 4], const(3, 3)), [NA, NA, 0])


# ── 7. range / median / percentrank ──

def test_range_median():
    s = [1, 5, 2, 3, 1]
    same(run('ta.range', s, const(3, 5)), [NA, NA, 4, 3, 2])
    same(run('ta.median', s, const(3, 5)), [NA, NA, 2, 3, 2])
    # gerade Laenge: [1,5,2,3] sortiert 1,2,3,5 -> (2+3)/2
    same(run('ta.median', s[:4], const(4, 4)), [NA, NA, NA, 2.5])


def test_percentrank():
    s = [1, 5, 2, 3, 1, 4]
    # Bar3: vorherige [1,5,2] <= 3: 1,2 -> 2/3; Bar4: [5,2,3] <= 1: 0; Bar5: [2,3,1] <= 4: 3/3
    same(run('ta.percentrank', s, const(3, 6)), [NA, NA, NA, 200 / 3, 0, 100])


# ── 8. stoch ──

def test_stoch():
    h = [10, 12, 11, 13]
    l = [8, 9, 7, 10]
    c = [9, 11, 8, 12]
    # Bar2: hh 12, ll 7 -> 100*(8-7)/5 = 20; Bar3: hh 13, ll 7 -> 100*5/6
    same(run('ta.stoch', c, h, l, const(3, 4)), [NA, NA, 20, 500 / 6])
    # Spanne 0 -> na (Pine: Division durch 0)
    same(run('ta.stoch', [5, 5], [5, 5], [5, 5], [2, 2]), [NA, NA])


# ── 9. cci ──

def test_cci():
    # [1,2,3,10]: mean 4, MAD (3+2+1+6)/4 = 3 -> (10-4)/(0.015*3) = 133.33
    same(run('ta.cci', [1, 2, 3, 10], const(4, 4)), [NA, NA, NA, 6 / 0.045])
    same(run('ta.cci', [2, 2, 2], const(3, 3)), [NA, NA, NA])


# ── 10. linreg ──

def test_linreg():
    # [1,2,4]: slope 1.5, intercept 5/6 -> x=2: 23/6, offset 1 -> x=1: 14/6
    same(run('ta.linreg', [1, 2, 4], const(3, 3), const(0, 3)), [NA, NA, 23 / 6])
    same(run('ta.linreg', [1, 2, 4], const(3, 3), const(1, 3)), [NA, NA, 14 / 6])
    same(run('ta.linreg', [1, 2, 3], const(3, 3), const(0, 3)), [NA, NA, 3])


# ── 11. correlation ──

def test_correlation():
    same(run('ta.correlation', [1, 2, 3], [2, 4, 6], const(3, 3)), [NA, NA, 1])
    same(run('ta.correlation', [1, 2, 3], [3, 2, 1], const(3, 3)), [NA, NA, -1])
    same(run('ta.correlation', [1, 2, 3], [1, 1, 1], const(3, 3)), [NA, NA, NA])


def test_length_zero_raises():
    with pytest.raises(ValueError):
        run('ta.range', [1], [0])


# ── Pine-Ebene: compile_pine / run_backtest ──

T0 = datetime(2026, 1, 5, 14, 30)


def mk_bars(ohlc):
    return [Bar(T0 + timedelta(minutes=i), o, h, l, c, i) for i, (o, h, l, c) in enumerate(ohlc)]


BARS = mk_bars([
    (100.0, 101.0, 99.0, 100.5),   # 0: up   -> barssince 0
    (100.5, 101.0, 99.5, 100.0),   # 1: down -> 1
    (100.0, 100.5, 99.0, 99.5),    # 2: down -> 2  => Order limit 99.5, TP 104.5, SL 94.5
    (99.6, 100.0, 99.2, 99.4),     # 3: Low 99.2 <= 99.5 -> Fill 99.5 (Open 99.6 > Limit)
    (100.0, 105.0, 99.9, 104.0),   # 4: High 105 >= 104.5 -> TP 104.5
    (104.0, 104.5, 103.0, 104.2),  # 5: up -> barssince 0, kein neuer Einstieg
])


def _src(n):
    return f'''//@version=5
strategy("bs")
bs = ta.barssince(close > open)
if bs == {n} and strategy.position_size == 0
    strategy.order("L", strategy.long, qty=1, limit=close)
    strategy.exit("X", from_entry="L", qty=1, limit=close+5, stop=close-5)
'''


def test_pine_barssince_trade():
    trades = run_backtest(compile_pine(_src(2)), BARS)
    assert len(trades) == 1
    t = trades[0]
    assert t.side == 'long'
    assert t.entry_price == pytest.approx(99.5)
    assert t.exit_price == pytest.approx(104.5)
    assert t.entry_time == T0 + timedelta(minutes=3)
    assert t.exit_time == T0 + timedelta(minutes=4)
    assert (t.exit_price - t.entry_price) * t.qty == pytest.approx(5.0)   # +5 Punkte


def test_pine_barssince_control_no_trade():
    # barssince erreicht nie 5 -> kein Trade (Bedingung wirkt wirklich)
    assert run_backtest(compile_pine(_src(5)), BARS) == []


def test_pine_all_functions_compile_and_gate():
    # Alle Funktionen in Pine aufrufbar; Einstieg nur, wenn die nachgerechneten Werte stimmen.
    src = '''//@version=5
strategy("all")
up = close > open
bs = ta.barssince(up)
vw = ta.valuewhen(up, close, 0)
cm = ta.cum(1)
cr = ta.cross(close, 100)
ri = ta.rising(close, 2)
fa = ta.falling(close, 2)
hb = ta.highestbars(high, 3)
lb = ta.lowestbars(low, 3)
rg = ta.range(close, 3)
md = ta.median(close, 3)
pr = ta.percentrank(close, 3)
st = ta.stoch(close, high, low, 3)
cc = ta.cci(close, 3)
lr = ta.linreg(close, 3, 0)
co = ta.correlation(close, open, 3)
ok = bar_index == 2 and bs == 2 and vw == 100.5 and cm == 3 and cr and fa and not ri and hb == -1 and lb == 0 and rg == 1 and md == 100 and st == 25
if ok
    strategy.order("L", strategy.long, qty=1, limit=close)
    strategy.exit("X", from_entry="L", qty=1, limit=close+5, stop=close-5)
'''
    # Bar2 nachgerechnet: letzte up-Bar = Bar0 (close 100.5); cum(1) = 3; close 100.0 -> 99.5
    # kreuzt 100 nach unten; 99.5 < 100.0 und < 100.5 -> falling; High [101,101,100.5]:
    # Gleichstand -> juengere Bar1 = -1; Low [99,99.5,99] -> Bar2 = 0; range 100.5-99.5 = 1;
    # median 100; stoch 100*(99.5-99)/(101-99) = 25.
    trades = run_backtest(compile_pine(src), BARS)
    assert len(trades) == 1
    assert trades[0].entry_price == pytest.approx(99.5)


def test_crossover_crossunder_with_scalars_in_pine():
    """Regression: vorher bekam ta.crossover nur Einzelwerte und war immer false."""
    from datetime import datetime, timedelta
    from pine_engine.engine import compile_pine, run_backtest
    from pine_engine.runtime.broker import Bar
    src = '''//@version=5
strategy("t")
lvl = 102.0
up = ta.crossover(close, lvl)
dn = ta.crossunder(close, lvl)
if up
    strategy.order("L", strategy.long, qty=1, limit=close)
    strategy.exit("XL", from_entry="L", qty=1, limit=close + 1, stop=close - 50)
if dn
    strategy.order("S", strategy.short, qty=1, limit=close)
    strategy.exit("XS", from_entry="S", qty=1, limit=close - 1, stop=close + 50)
'''
    closes = [100, 101, 103, 104, 105, 101, 100, 99]
    t0 = datetime(2026, 1, 5, 14, 30)
    bars = [Bar(t0 + timedelta(minutes=i), c, c + 1.5, c - 1.5, c, i) for i, c in enumerate(closes)]
    trades = run_backtest(compile_pine(src), bars)
    # Kreuzung nach oben in Bar 2 (101 -> 103), nach unten in Bar 5 (104/105 -> 101)
    assert [(t.entry_id, t.entry_price, t.exit_price) for t in trades] == [("L", 103, 104), ("S", 101, 100)]
