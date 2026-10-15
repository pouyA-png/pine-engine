"""Tests Paket P4: Pine-Standard math/str/syminfo/zeit (pine_engine/ext/pine_std.py).

Alle Bars in UTC (tz-aware). 2026-01-05 ist ein Montag; NY = UTC-5 (Winterzeit).
"""

import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from pine_engine.engine import compile_pine, run_backtest, RuntimeContext
from pine_engine.runtime import ext as _ext
from pine_engine.runtime.broker import Bar
from pine_engine.runtime.na import NA, is_na
from pine_engine.ext import pine_std as P

UTC = timezone.utc
T0 = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)          # Mo 09:30 NY


def _ms(dt):
    return int(dt.timestamp() * 1000)


def _bars(ohlc, t0=T0):
    return [Bar(t0 + timedelta(minutes=i), o, h, l, c, i)
            for i, (o, h, l, c) in enumerate(ohlc)]


def _run(body, decls, ohlc, t0=T0):
    """decls: {name: 'float'|'string'|'bool'|'int'} -> je Bar ctx.v_<name>."""
    init = {'float': 'na', 'int': 'na', 'string': '""', 'bool': 'false'}
    decl = '\n'.join(f'var {t} {n} = {init[t]}' for n, t in decls.items())
    src = f'//@version=5\nstrategy("t")\n{decl}\n{body}\n'
    c = compile_pine(src)
    ctx = RuntimeContext(params=c.get_default_params())
    c.initialize(ctx)
    out = {n: [] for n in decls}
    for bar in _bars(ohlc, t0):
        ctx.strategy.process_bar(bar)
        ctx.update_bar(bar)
        c.execute_bar(ctx)
        for n in decls:
            out[n].append(getattr(ctx, f'v_{n}'))
    return out


def _fake_ctx(ts_ms=0, idx=0):
    return SimpleNamespace(ext_states={}, bar_idx=idx, bar_ts_ms=ts_ms)


def _call(name, *a, ctx=None, site=1, **kw):
    return _ext.call(ctx or _fake_ctx(), name, site, *a, **kw)


FLAT = [(100, 101, 99, 100)] * 3


# ── 1. math ────────────────────────────────────────────────────────────────
def test_math_basic_via_pine():
    body = '''a := math.sqrt(16)
b := math.pow(2, 10)
c := math.log(math.exp(2))
d := math.log10(1000)
e := math.sign(-3.5)
f := math.avg(1, 2, 6)'''
    o = _run(body, {k: 'float' for k in 'abcdef'}, FLAT[:1])
    assert o['a'] == [4.0] and o['b'] == [1024.0]
    assert o['c'][0] == pytest.approx(2.0) and o['d'][0] == pytest.approx(3.0)
    assert o['e'] == [-1.0] and o['f'] == [3.0]


def test_math_na_domain():
    assert is_na(_call('math.sqrt', -1))
    assert is_na(_call('math.log', 0))
    assert is_na(_call('math.log10', -5))
    assert is_na(_call('math.avg', 1, NA))
    assert _call('math.sign', 0) == 0.0


def test_math_sum_rolling_over_close():
    # closes 1,2,3,4 -> sum(3): na, na, 6, 9
    ohlc = [(c, c, c, c) for c in (1, 2, 3, 4)]
    o = _run('s := math.sum(close, 3)', {'s': 'float'}, ohlc)
    assert is_na(o['s'][0]) and is_na(o['s'][1])
    assert o['s'][2:] == [6.0, 9.0]


def test_math_round_to_mintick():
    o = _run('r := math.round_to_mintick(close + 0.13)\nq := math.round_to_mintick(close - 0.125)',
             {'r': 'float', 'q': 'float'}, [(100, 100, 100, 100)])
    assert o['r'] == [100.25]          # 100.13 -> naechster Tick 100.25
    assert o['q'] == [100.0]           # 99.875 = Mitte -> weg von 0 -> 100.00
    assert _call('math.round_to_mintick', -0.125) == -0.25


def test_math_round_builtin_map_not_overridden():
    # math.round bleibt pine_round (BUILTIN_MAP), inkl. Praezision
    assert 'math.round' not in _ext.REGISTRY
    o = _run('r := math.round(close, 1)', {'r': 'float'}, [(1.25, 1.25, 1.25, 1.25)])
    assert o['r'] == [1.3]


# ── 2. nz / fixnan ─────────────────────────────────────────────────────────
def test_nz_and_fixnan():
    body = '''a := nz(close[1])
b := nz(close[1], -1)
x = bar_index == 1 ? na : close
f := fixnan(x)'''
    ohlc = [(c, c, c, c) for c in (10, 11, 12)]
    o = _run(body, {'a': 'float', 'b': 'float', 'f': 'float'}, ohlc)
    assert o['a'] == [0, 10, 11]
    assert o['b'] == [-1, 10, 11]
    assert o['f'] == [10, 10, 12]      # Bar 1 na -> letzter Nicht-na-Wert 10


def test_fixnan_state_per_call_site():
    ctx = _fake_ctx()
    assert _call('fixnan', 5.0, ctx=ctx, site=1) == 5.0
    assert is_na(_call('fixnan', NA, ctx=ctx, site=2))    # eigene Stelle, noch nichts
    assert _call('fixnan', NA, ctx=ctx, site=1) == 5.0


# ── 3./4. syminfo, timeframe ───────────────────────────────────────────────
def test_syminfo_timeframe_constants():
    body = '''m := syminfo.mintick
p := syminfo.pointvalue
t := syminfo.ticker
tf := timeframe.period
mu := timeframe.multiplier
i := timeframe.isintraday'''
    o = _run(body, {'m': 'float', 'p': 'float', 't': 'string', 'tf': 'string',
                    'mu': 'int', 'i': 'bool'}, FLAT[:1])
    assert o['m'] == [0.25] and o['p'] == [20.0] and o['t'] == ['NQ']
    assert o['tf'] == ['1'] and o['mu'] == [1] and o['i'] == [True]


# ── 5. time_close, weekofyear, second ──────────────────────────────────────
def test_time_close_weekofyear_second():
    body = '''tc := time_close
w := weekofyear
s := second
w2 := weekofyear(time)'''
    o = _run(body, {'tc': 'float', 'w': 'int', 's': 'int', 'w2': 'int'}, FLAT[:2])
    assert o['tc'] == [_ms(T0) + 60_000, _ms(T0) + 120_000]
    assert o['w'] == [2, 2] and o['w2'] == [2, 2]      # 05.01.2026 = ISO-KW 2
    assert o['s'] == [0, 0]
    ts = _ms(datetime(2026, 1, 5, 14, 30, 42, tzinfo=UTC))
    assert _call('second', ts) == 42


# ── 6. timestamp ───────────────────────────────────────────────────────────
def test_timestamp_variants():
    # 2026-01-05 09:30 NY = 14:30 UTC (EST); 2026-07-06 09:30 NY = 13:30 UTC (EDT)
    assert _call('timestamp', 'America/New_York', 2026, 1, 5, 9, 30) == _ms(T0)
    assert _call('timestamp', 2026, 1, 5, 9, 30) == _ms(T0)
    assert _call('timestamp', 2026, 7, 6, 9, 30) == _ms(datetime(2026, 7, 6, 13, 30, tzinfo=UTC))
    assert _call('timestamp', 'UTC', 2026, 1, 5, 14, 30) == _ms(T0)
    assert _call('timestamp', 'GMT+2', 2026, 1, 5, 16, 30) == _ms(T0)
    assert _call('timestamp', '2026-01-05T09:30:00-05:00') == _ms(T0)
    o = _run('ts := timestamp("America/New_York", 2026, 1, 5, 9, 30)\nok := time == ts',
             {'ts': 'float', 'ok': 'bool'}, FLAT[:1])
    assert o['ts'] == [_ms(T0)] and o['ok'] == [True]


# ── 7. time(timeframe, session) ────────────────────────────────────────────
def _ny_ms(y, mo, d, h, mi):
    return _call('timestamp', y, mo, d, h, mi)


@pytest.mark.parametrize('when,sess,inside', [
    ((2026, 1, 5, 9, 29), '0930-1600', False),
    ((2026, 1, 5, 9, 30), '0930-1600', True),
    ((2026, 1, 5, 15, 59), '0930-1600', True),
    ((2026, 1, 5, 16, 0), '0930-1600', False),          # Ende exklusiv
    ((2026, 1, 10, 10, 0), '0930-1600:23456', False),   # Samstag
    ((2026, 1, 10, 10, 0), '0930-1600', True),          # ohne Tagesfilter alle Tage
    ((2026, 1, 4, 19, 0), '1800-0930:23456', True),     # So-Abend -> Handelstag Mo
    ((2026, 1, 9, 19, 0), '1800-0930:23456', False),    # Fr-Abend -> Handelstag Sa
    ((2026, 1, 9, 9, 0), '1800-0930:23456', True),      # Fr-Morgen
    ((2026, 1, 5, 12, 0), '1800-0930', False),
    ((2026, 1, 5, 12, 30), '0930-1200,1300-1600', False),
    ((2026, 1, 5, 13, 0), '0930-1200,1300-1600', True),
    ((2026, 7, 6, 9, 30), '0930-1600', True),           # Sommerzeit
])
def test_time_session(when, sess, inside):
    ts = _ny_ms(*when)
    r = _call('time', '1', sess, ctx=_fake_ctx(ts))
    assert (r == ts) if inside else is_na(r)


def test_time_session_other_tz_and_timeframe():
    ts = _ms(T0)                                         # 14:30 UTC
    assert _call('time', '1', '1400-1500', 'UTC', ctx=_fake_ctx(ts)) == ts
    assert is_na(_call('time', '1', '1400-1500', ctx=_fake_ctx(ts)))  # NY 09:30
    ts7 = ts + 7 * 60_000
    assert _call('time', '5', ctx=_fake_ctx(ts7)) == ts + 5 * 60_000
    with pytest.raises(NotImplementedError):
        _call('time', '240', ctx=_fake_ctx(ts))


def test_time_call_and_time_series_coexist_in_pine():
    # Bars ab 09:28 NY: 09:28, 09:29 draussen, 09:30 drin
    t0 = datetime(2026, 1, 5, 14, 28, tzinfo=UTC)
    body = '''t := time
s := time("1", "0930-1600")
inS := not na(time(timeframe.period, "0930-1600:23456"))'''
    o = _run(body, {'t': 'float', 's': 'float', 'inS': 'bool'}, FLAT, t0=t0)
    assert o['t'] == [_ms(t0) + i * 60_000 for i in range(3)]
    assert is_na(o['s'][0]) and is_na(o['s'][1]) and o['s'][2] == o['t'][2]
    assert o['inS'] == [False, False, True]


def test_session_filter_backtest_trade():
    """Handelstest: Entry nur in der Session, Limit auf Tick gerundet.
    Bars (UTC, NY=UTC-5):
      0 14:28 (09:28) c=90   -> ausserhalb, kein Order
      1 14:29 (09:29) c=90   -> ausserhalb
      2 14:30 (09:30) c=100.1 -> Order: Limit round_to_mintick(99.8)=99.75,
                                 TP = 100.1 + 8*mintick = 102.1, SL = 95.1
      3 14:31 o=100 l=99.5    -> Fill 99.75 (h 100.5 < TP, l > SL)
      4 14:32 h=103           -> TP 102.1 -> +2.35 Punkte = 47 $ (20 $/Punkt)
    """
    src = '''//@version=5
strategy("t")
var bool done = false
inS = not na(time(timeframe.period, "0930-1600:23456"))
if inS and not done
    done := true
    strategy.order("L", strategy.long, qty=1, limit=math.round_to_mintick(close - 0.3))
    strategy.exit("X", from_entry="L", qty=1, limit=close + 8 * syminfo.mintick, stop=close - 5)
'''
    t0 = datetime(2026, 1, 5, 14, 28, tzinfo=UTC)
    ohlc = [(90, 90.5, 89.5, 90), (90, 90.5, 89.5, 90), (100, 100.2, 99.9, 100.1),
            (100, 100.5, 99.5, 100.2), (100.5, 103, 100, 102.5), (102, 102, 101, 101)]
    trades = run_backtest(compile_pine(src), _bars(ohlc, t0))
    assert len(trades) == 1
    t = trades[0]
    assert t.entry_price == 99.75
    assert t.exit_price == pytest.approx(102.1)
    assert (t.exit_price - t.entry_price) * P.POINTVALUE == pytest.approx(47.0)


# ── 8. str.* ───────────────────────────────────────────────────────────────
def test_str_functions_via_pine():
    body = '''s := str.format("{0} {1}", "NQ", 1.5)
g := str.format("{0}|{0,number,#.##}|{1,number,0.00}", 12345.6789, 2)
c := str.contains("TRAIL4", "AIL")
sw := str.startswith("TP1 hit", "TP1")
ew := str.endswith("TP1 hit", "miss")
n := str.length("abcd")
u := str.upper("nq")
lo := str.lower("NQ")
r := str.replace_all("a-b-c", "-", "+")
x := str.tonumber("21345.25")
y := str.tonumber("abc")'''
    decls = {'s': 'string', 'g': 'string', 'c': 'bool', 'sw': 'bool', 'ew': 'bool',
             'n': 'int', 'u': 'string', 'lo': 'string', 'r': 'string', 'x': 'float', 'y': 'float'}
    o = {k: v[0] for k, v in _run(body, decls, FLAT[:1]).items()}
    assert o['s'] == 'NQ 1.5'
    assert o['g'] == '12,345.679|12345.68|2.00'
    assert o['c'] is True and o['sw'] is True and o['ew'] is False
    assert o['n'] == 4 and o['u'] == 'NQ' and o['lo'] == 'nq'
    assert o['r'] == 'a+b+c'
    assert o['x'] == 21345.25 and is_na(o['y'])


def test_str_format_edge_cases():
    assert _call('str.format', '{0}', 2.0) == '2'
    assert _call('str.format', '{0}', True) == 'true'
    assert _call('str.format', '{0}', NA) == 'NaN'
    assert _call('str.format', '{0} {5}', 1) == '1 {5}'


# ── 9. math.random ─────────────────────────────────────────────────────────
def test_math_random_deterministic():
    def seq(seed, n=5):
        ctx = _fake_ctx()
        return [_call('math.random', 0, 10, seed, ctx=ctx, site=1) for _ in range(n)]
    a, b, c = seq(42), seq(42), seq(7)
    assert a == b and a != c
    assert all(0 <= v < 10 for v in a)
    body = 'r := math.random(5, 6, 1)'
    o1 = _run(body, {'r': 'float'}, FLAT)['r']
    o2 = _run(body, {'r': 'float'}, FLAT)['r']
    assert o1 == o2 and all(5 <= v < 6 for v in o1) and len(set(o1)) == 3


# ── 10. last_bar_index bewusst nicht registriert ───────────────────────────
def test_no_lookahead_names_registered():
    for n in ('last_bar_index', 'last_bar_time', 'barstate.islast'):
        assert n not in _ext.REGISTRY and n not in _ext.VARIABLES and n not in _ext.CONSTANTS


def test_default_backtest_unchanged_without_calls():
    src = '''//@version=5
strategy("t")
if bar_index == 1
    strategy.order("L", strategy.long, qty=1, limit=close)
    strategy.exit("X", from_entry="L", qty=1, limit=close+1, stop=close-5)
'''
    code = compile_pine(src).python_code
    assert 'ext_call' not in code and 'ext_var' not in code
