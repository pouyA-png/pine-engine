"""Tests fuer pine_engine/ext/nq_session.py (Paket P5: NQ-Session + Tageslevel)."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from pine_engine.engine import compile_pine, run_backtest, RuntimeContext
from pine_engine.runtime.broker import Bar
from pine_engine.runtime.na import is_na

UTC = timezone.utc
NY = ZoneInfo('America/New_York')


def _run(src, bars, names):
    """Fuehrt Pine aus und liest nach jeder Bar die var-Variablen ``names``."""
    c = compile_pine(src)
    ctx = RuntimeContext(params=c.get_default_params())
    c.initialize(ctx)
    out = {}
    for b in bars:
        ctx.strategy.process_bar(b)
        ctx.update_bar(b)
        c.execute_bar(ctx)
        ctx.strategy.process_entrybar_exits()
        out[b.timestamp] = {n: getattr(ctx, 'v_' + n) for n in names}
    return out


def _m1(start, end, price=None):
    """M1-Bars [start, end) (UTC). price(i, ts) -> (o, h, l, c)."""
    bars, ts, i = [], start, 0
    while ts < end:
        if price is None:
            c = 20000 + (i % 37) - (i % 11) * 0.5
            o, h, l = c, c + 1, c - 1
        else:
            o, h, l, c = price(i, ts)
        bars.append(Bar(ts, o, h, l, c, i))
        ts += timedelta(minutes=1)
        i += 1
    return bars


def _u(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


VARS = ['rth', 'eth', 'rho', 'rhh', 'rhl', 'pdh', 'pdl', 'pdc', 'ethh', 'ethl',
        'orh', 'orl', 'fb', 'nr', 'di', 'wd', 'dst', 'bso', 'ms930', 'ms1800',
        'inr', 'ion']

SRC_ALL = '''//@version=5
strategy("t")
var bool rth = false
var bool eth = false
var float rho = na
var float rhh = na
var float rhl = na
var float pdh = na
var float pdl = na
var float pdc = na
var float ethh = na
var float ethl = na
var float orh = na
var float orl = na
var bool fb = false
var bool nr = false
var int di = 0
var int wd = 0
var bool dst = false
var int bso = 0
var float ms930 = na
var float ms1800 = na
var bool inr = false
var bool ion = false
rth := nq.rth
eth := nq.eth
rho := nq.rth_open
rhh := nq.rth_high
rhl := nq.rth_low
pdh := nq.pd_high
pdl := nq.pd_low
pdc := nq.pd_close
ethh := nq.eth_high
ethl := nq.eth_low
orh := nq.or_high(15)
orl := nq.or_low(15)
fb := nq.sess_first_bar
nr := nq.sess_new_rth
di := nq.sess_day_index
wd := nq.sess_weekday
dst := nq.sess_is_dst
bso := nq.sess_bars_since_open
ms930 := nq.sess_minutes_since(930)
ms1800 := nq.sess_minutes_since("1800")
inr := nq.sess_in(930, 1600)
ion := nq.sess_in("1800-0930")
'''


# ── Datensatz Januar 2026 (EST, UTC-5) ─────────────────────────────────────
# Mo 05.01. 12:00 UTC (07:00 NY) bis Di 06.01. 16:00 UTC (11:00 NY), M1.
SPIKES = {
    _u(2026, 1, 5, 15, 0): ('h', 20500.0),    # 10:00 NY, RTH-Hoch Tag Mo
    _u(2026, 1, 5, 20, 30): ('l', 19800.0),   # 15:30 NY, RTH-Tief Tag Mo
    _u(2026, 1, 5, 21, 30): ('h', 21000.0),   # 16:30 NY, weder RTH noch Overnight
    _u(2026, 1, 5, 23, 0): ('l', 19000.0),    # 18:00 NY, Overnight Tag Di
}


@pytest.fixture(scope='module')
def jan():
    bars = _m1(_u(2026, 1, 5, 12, 0), _u(2026, 1, 6, 16, 0))
    for b in bars:
        s = SPIKES.get(b.timestamp)
        if s:
            if s[0] == 'h':
                b.high = s[1]
            else:
                b.low = s[1]
    return bars, _run(SRC_ALL, bars, VARS)


def _ny_min(b):
    t = b.timestamp.astimezone(NY)
    return t.hour * 60 + t.minute


def _ref(bars, pred):
    sel = [b for b in bars if pred(b)]
    return max(b.high for b in sel), min(b.low for b in sel)


def test_rth_eth_flags_and_sess_in(jan):
    bars, out = jan
    for b in bars:
        m = _ny_min(b)
        v = out[b.timestamp]
        exp = 570 <= m < 960
        assert v['rth'] is exp and v['eth'] is (not exp)
        assert v['inr'] is exp
        assert v['ion'] is (m >= 1080 or m < 570)


def test_rth_levels_running_no_lookahead(jan):
    bars, out = jan
    # vor 09:30 NY: na
    assert is_na(out[_u(2026, 1, 5, 14, 29)]['rhh'])
    first = next(b for b in bars if b.timestamp == _u(2026, 1, 5, 14, 30))
    assert out[first.timestamp]['rho'] == first.open
    assert out[first.timestamp]['nr'] is True
    assert out[_u(2026, 1, 5, 14, 31)]['nr'] is False
    # Spike 20500 um 15:00 UTC: Bar davor sieht ihn nicht, ab der Bar selbst ja
    assert out[_u(2026, 1, 5, 14, 59)]['rhh'] < 20500
    assert out[_u(2026, 1, 5, 15, 0)]['rhh'] == 20500
    # laufendes Tief = Referenz aus den Bars bis inkl. jetzt
    now = _u(2026, 1, 5, 18, 0)
    h, l = _ref(bars, lambda b: _u(2026, 1, 5, 14, 30) <= b.timestamp <= now)
    assert (out[now]['rhh'], out[now]['rhl']) == (h, l)
    # 16:30 NY Spike (21000) zaehlt nicht zu RTH
    assert out[_u(2026, 1, 5, 21, 45)]['rhh'] == 20500
    assert out[_u(2026, 1, 5, 21, 45)]['rhl'] == 19800


def test_previous_day_levels(jan):
    bars, out = jan
    assert is_na(out[_u(2026, 1, 5, 22, 59)]['pdh'])        # noch kein Vortag
    v = out[_u(2026, 1, 6, 14, 0)]                           # Di 09:00 NY
    assert v['pdh'] == 20500 and v['pdl'] == 19800
    last_rth = next(b for b in bars if b.timestamp == _u(2026, 1, 5, 20, 59))
    assert v['pdc'] == last_rth.close
    assert is_na(v['rhh'])                                   # heute noch keine RTH


def test_overnight_levels(jan):
    bars, out = jan
    # Tag Mo: Overnight = 07:00-09:29 NY (Daten ab 12:00 UTC)
    v = out[_u(2026, 1, 5, 14, 29)]
    assert (v['ethh'], v['ethl']) == _ref(bars, lambda b: b.timestamp < _u(2026, 1, 5, 14, 30))
    # nach 09:30 eingefroren
    assert out[_u(2026, 1, 5, 18, 0)]['ethh'] == v['ethh']
    # Tag Di: 18:00-09:30, 16:30-Spike (21000) ausgeschlossen
    v = out[_u(2026, 1, 6, 14, 29)]
    ref = _ref(bars, lambda b: _u(2026, 1, 5, 23, 0) <= b.timestamp < _u(2026, 1, 6, 14, 30))
    assert (v['ethh'], v['ethl']) == ref
    assert v['ethl'] == 19000 and v['ethh'] < 21000
    # laufend: um 18:05 NY nur 18:00-18:05
    v = out[_u(2026, 1, 5, 23, 5)]
    assert (v['ethh'], v['ethl']) == _ref(
        bars, lambda b: _u(2026, 1, 5, 23, 0) <= b.timestamp <= _u(2026, 1, 5, 23, 5))


def test_opening_range(jan):
    bars, out = jan
    assert is_na(out[_u(2026, 1, 5, 14, 43)]['orh'])         # Range noch offen
    v = out[_u(2026, 1, 5, 14, 44)]                          # 09:44-Bar schliesst 09:45
    ref = _ref(bars, lambda b: _u(2026, 1, 5, 14, 30) <= b.timestamp <= _u(2026, 1, 5, 14, 44))
    assert (v['orh'], v['orl']) == ref
    assert out[_u(2026, 1, 5, 18, 0)]['orh'] == ref[0]       # bleibt stehen
    assert is_na(out[_u(2026, 1, 5, 23, 0)]['orh'])          # neuer Handelstag


def test_day_structure_and_minutes(jan):
    bars, out = jan
    v0 = out[_u(2026, 1, 5, 12, 0)]
    assert v0['fb'] is True and v0['di'] == 0 and v0['bso'] == 0 and v0['wd'] == 1
    assert out[_u(2026, 1, 5, 22, 59)]['fb'] is False
    v = out[_u(2026, 1, 5, 23, 0)]                            # 18:00 NY -> Handelstag Di
    assert v['fb'] is True and v['di'] == 1 and v['bso'] == 0 and v['wd'] == 2
    assert out[_u(2026, 1, 5, 23, 5)]['bso'] == 5
    assert out[_u(2026, 1, 5, 15, 0)]['ms930'] == 30
    assert is_na(out[_u(2026, 1, 5, 14, 0)]['ms930'])
    assert is_na(out[_u(2026, 1, 5, 23, 30)]['ms930'])        # neuer Tag, vor 09:30
    assert out[_u(2026, 1, 5, 23, 30)]['ms1800'] == 30
    assert out[_u(2026, 1, 6, 14, 30)]['ms930'] == 0
    assert out[_u(2026, 1, 5, 15, 0)]['dst'] is False


# ── DST-Wechsel Maerz 2026 (So 08.03.: EST -> EDT) ─────────────────────────

def test_dst_switch_march_2026():
    # Fr 06.03. 14:00-15:00 UTC (EST: 09:00-10:00) und So 08.03. 21:00 UTC bis Mo 09.03. 14:00 UTC
    bars = _m1(_u(2026, 3, 6, 14, 0), _u(2026, 3, 6, 15, 0)) + \
        _m1(_u(2026, 3, 8, 21, 0), _u(2026, 3, 9, 14, 0))
    for i, b in enumerate(bars):
        b.bar_index = i
    out = _run(SRC_ALL, bars, VARS)
    # Freitag (EST): RTH-Start 14:30 UTC
    assert out[_u(2026, 3, 6, 14, 29)]['rth'] is False
    assert out[_u(2026, 3, 6, 14, 30)]['nr'] is True
    assert out[_u(2026, 3, 6, 14, 30)]['dst'] is False
    assert out[_u(2026, 3, 6, 14, 30)]['wd'] == 5
    # Sonntag 17:00 NY (21:00 UTC, EDT) gehoert noch zum Handelstag "Sonntag"
    v = out[_u(2026, 3, 8, 21, 0)]
    assert v['fb'] is True and v['wd'] == 7 and v['dst'] is True
    # 18:00 EDT = 22:00 UTC -> neuer Handelstag Montag
    v = out[_u(2026, 3, 8, 22, 0)]
    assert v['fb'] is True and v['wd'] == 1 and v['ms1800'] == 0
    assert v['di'] == out[_u(2026, 3, 8, 21, 0)]['di'] + 1
    # Vortag = Freitag-RTH (nur 14:30-14:59 UTC vorhanden)
    fri = [b for b in bars if _u(2026, 3, 6, 14, 30) <= b.timestamp < _u(2026, 3, 6, 15, 0)]
    assert v['pdh'] == max(b.high for b in fri) and v['pdl'] == min(b.low for b in fri)
    assert v['pdc'] == fri[-1].close
    # Montag (EDT): RTH-Start 13:30 UTC
    assert out[_u(2026, 3, 9, 13, 29)]['rth'] is False
    assert out[_u(2026, 3, 9, 13, 30)]['nr'] is True
    assert out[_u(2026, 3, 9, 13, 30)]['ms930'] == 0
    assert out[_u(2026, 3, 9, 13, 44)]['orh'] == max(
        b.high for b in bars if _u(2026, 3, 9, 13, 30) <= b.timestamp <= _u(2026, 3, 9, 13, 44))
    # Overnight Montag: 22:00 UTC So bis 13:29 UTC Mo
    on = [b for b in bars if _u(2026, 3, 8, 22, 0) <= b.timestamp < _u(2026, 3, 9, 13, 30)]
    v = out[_u(2026, 3, 9, 13, 29)]
    assert (v['ethh'], v['ethl']) == (max(b.high for b in on), min(b.low for b in on))


def test_naive_timestamp_is_utc_and_sess_in_overnight():
    bars = [Bar(datetime(2026, 1, 6, 3, 0) + timedelta(minutes=i), 1, 2, 0, 1, i) for i in range(3)]
    out = _run(SRC_ALL, bars, VARS)
    v = out[bars[0].timestamp]                                # 22:00 NY Mo
    assert v['ion'] is True and v['inr'] is False and v['wd'] == 2


def test_no_call_no_hook():
    """Ohne nq.*-Aufruf wird kein Hook registriert (Standardverhalten unveraendert)."""
    c = compile_pine('//@version=5\nstrategy("t")\nx = close\n')
    ctx = RuntimeContext(params={})
    c.initialize(ctx)
    for b in _m1(_u(2026, 1, 5, 14, 30), _u(2026, 1, 5, 14, 35)):
        ctx.strategy.process_bar(b)
        ctx.update_bar(b)
        c.execute_bar(ctx)
    assert ctx.strategy.broker.hooks == []


def test_hook_sees_bars_when_call_is_conditional():
    """Aufruf nur in manchen Bars: der Tracker sieht trotzdem jede Bar (Hook)."""
    src = '''//@version=5
strategy("t")
var float h = na
if bar_index == 0 or bar_index == 10
    h := nq.rth_high
'''
    def px(i, ts):
        return (100, 500 if i == 5 else 101, 99, 100)
    bars = _m1(_u(2026, 1, 5, 14, 30), _u(2026, 1, 5, 14, 41), px)
    out = _run(src, bars, ['h'])
    assert out[bars[10].timestamp]['h'] == 500


# ── Handels-Test: Entry nur, wenn close > nq.or_high(15) ────────────────────

SRC_TRADE = '''//@version=5
strategy("orb")
var bool done = false
orh = nq.or_high(15)
if not done and nq.rth and not na(orh) and close > orh
    strategy.order("L", strategy.long, qty=1, limit=close)
    strategy.exit("X", from_entry="L", qty=1, limit=close + 5, stop=close - 5)
    done := true
'''


def test_trade_entry_only_above_opening_range():
    t0 = _u(2026, 1, 5, 14, 0)                                # 09:00 NY
    rows = {}
    for k in range(30):                                       # Vormarkt: close 200 > alles -> kein Signal (OR na)
        rows[k] = (150, 205, 145, 200)
    for k in range(30, 35):                                   # 09:30-09:34: Hoch 98
        rows[k] = (95, 98, 90, 95)
    rows[35] = (95, 100, 94, 99)                              # 09:35: close 99 > bisheriges Hoch 98, Range offen
    for k in range(36, 45):                                   # bis 09:44: Range-Hoch 100, Tief 90
        rows[k] = (95, 99, 91, 95)
    for k in range(45, 50):                                   # 09:45-09:49: unter 100
        rows[k] = (97, 99.5, 96, 98)
    rows[50] = (98, 101.5, 97, 101)                           # 09:50: close 101 > 100 -> Signal
    rows[51] = (101, 102, 100.5, 101.5)                       # Fuellung limit 101 (low 100.5)
    rows[52] = (102, 107, 101.5, 106.5)                       # TP 106
    for k in range(53, 60):
        rows[k] = (106, 110, 104, 108)
    bars = [Bar(t0 + timedelta(minutes=k), *rows[k], k) for k in range(60)]
    trades = run_backtest(compile_pine(SRC_TRADE), bars)
    assert len(trades) == 1
    tr = trades[0]
    assert tr.side == 'long' and tr.qty == 1
    assert tr.entry_price == 101 and tr.exit_price == 106
    assert tr.entry_time == t0 + timedelta(minutes=51)
    assert tr.exit_time == t0 + timedelta(minutes=52)
    # Kontrolle: ohne OR-Filter haette schon der Vormarkt (Bar 0) ein Signal gegeben
    src_nofilter = SRC_TRADE.replace('nq.rth and not na(orh) and close > orh', 'close > 0')
    t2 = run_backtest(compile_pine(src_nofilter), bars)
    assert t2[0].entry_time == t0 + timedelta(minutes=1)
