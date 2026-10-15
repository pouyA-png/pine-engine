"""Tests fuer Paket P6: nq.htf_* und request.security (HTF aus M1)."""

import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from datetime import datetime, timedelta, timezone

import pytest

from pine_engine.engine import compile_pine, run_backtest
from pine_engine.runtime.broker import Bar
from pine_engine.runtime.na import is_na

T0 = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)   # Mo, 09:30 NY


def mk_bars(n, t0=T0, step=1.0):
    """Deterministische M1-Bars: open = 100 + i*step, high = +2, low = -1, close = +0.5."""
    out = []
    for i in range(n):
        o = 100.0 + i * step
        out.append(Bar(t0 + timedelta(minutes=i), o, o + 2, o - 1, o + 0.5, i))
    return out


def run_vars(src, bars, names):
    c = compile_pine(src)
    from pine_engine.engine import RuntimeContext
    ctx = RuntimeContext(params=c.get_default_params())
    c.initialize(ctx)
    rec = []
    for b in bars:
        ctx.strategy.process_bar(b)
        ctx.update_bar(b)
        c.execute_bar(ctx)
        ctx.strategy.process_entrybar_exits()
        rec.append({n: getattr(ctx, 'v_' + n) for n in names})
    return rec, ctx


def pine(lines):
    return '//@version=5\nstrategy("t")\n' + '\n'.join(lines) + '\n'


# ── 1. 5-Minuten-Aggregation nachgerechnet ─────────────────────────────

def test_m5_ohlc_recomputed():
    bars = mk_bars(12)   # 14:30..14:41 UTC
    src = pine([
        'var float o1 = na', 'var float h1 = na', 'var float l1 = na', 'var float c1 = na',
        'var float c0 = na', 'var float rg = na',
        'o1 := nq.htf_open(5)', 'h1 := nq.htf_high(5)', 'l1 := nq.htf_low(5)',
        'c1 := nq.htf_close(5, 1)', 'c0 := nq.htf_close(5, 0)', 'rg := nq.htf_range(5, 1)',
    ])
    rec, _ = run_vars(src, bars, ['o1', 'h1', 'l1', 'c1', 'c0', 'rg'])
    # Kerze 14:30-14:34 = Bars 0..4: O=100, H=104+2=106, L=99, C=104.5
    for i in range(4):
        assert is_na(rec[i]['c1'])          # vor Schluss keine abgeschlossene Kerze
    r = rec[4]                              # letzte M1-Bar der Kerze -> abgeschlossen
    assert (r['o1'], r['h1'], r['l1'], r['c1']) == (100.0, 106.0, 99.0, 104.5)
    assert r['rg'] == 7.0
    # laufende Kerze (offset 0) auf Bar 6 (14:36): Close = 106.5
    assert rec[6]['c0'] == 106.5
    assert rec[6]['c1'] == 104.5
    # Kerze 14:35-14:39 = Bars 5..9: O=105 H=111 L=104 C=109.5
    r = rec[9]
    assert (r['o1'], r['h1'], r['l1'], r['c1']) == (105.0, 111.0, 104.0, 109.5)


def test_hour_boundary_and_new_bar_and_index():
    t0 = datetime(2026, 1, 5, 14, 55, tzinfo=timezone.utc)
    bars = mk_bars(12, t0=t0)    # 14:55..15:06
    src = pine([
        'var bool nb = false', 'var int bi = na', 'var float h60 = na', 'var float c60_0 = na',
        'var float o5 = na',
        'nb := nq.htf_new_bar(60)', 'bi := nq.htf_bar_index(5)',
        'h60 := nq.htf_high(60)', 'c60_0 := nq.htf_close(60, 0)', 'o5 := nq.htf_open(5, 0)',
    ])
    rec, _ = run_vars(src, bars, ['nb', 'bi', 'h60', 'c60_0', 'o5'])
    # erste Bar: neue 60er-Kerze (erste gesehene), Bar 5 (15:00) neue Stunde
    assert [r['nb'] for r in rec] == [True] + [False] * 4 + [True] + [False] * 6
    # Stunde 14:xx endet mit Bar 4 (14:59) -> ab dort abgeschlossen: H = 104+2
    assert is_na(rec[3]['h60'])
    assert rec[4]['h60'] == 106.0
    assert rec[5]['h60'] == 106.0
    assert rec[5]['c60_0'] == 105.5           # neue Stunde, laufend = nur Bar 5
    # 5er-Index: 14:55 = 0, 15:00 = 1, 15:05 = 2
    assert [r['bi'] for r in rec] == [0] * 5 + [1] * 5 + [2] * 2
    assert rec[7]['o5'] == 105.0


# ── Kein Lookahead ─────────────────────────────────────────────────────

def test_no_lookahead_value_changes_only_after_close():
    bars = mk_bars(15)
    # Bar 7 (in Kerze 14:35) bekommt einen Ausreisser nach oben
    b = bars[7]
    bars[7] = Bar(b.timestamp, b.open, 500.0, b.low, b.close, b.bar_index)
    src = pine(['var float h1 = na', 'h1 := nq.htf_high(5)'])
    rec, _ = run_vars(src, bars, ['h1'])
    # Waehrend der Kerze 14:35-14:39 (Bars 5..8) darf der Ausreisser nicht sichtbar sein
    for i in range(5, 9):
        assert rec[i]['h1'] == 106.0
    assert rec[9]['h1'] == 500.0              # erst nach Kerzenschluss
    # Zukunft darf nie in der Vergangenheit auftauchen: Werte identisch mit abgeschnittenen Daten
    rec_cut, _ = run_vars(src, bars[:8], ['h1'])
    assert [r['h1'] for r in rec_cut] == [r['h1'] for r in rec[:8]]


# ── EMA / ATR / highest / lowest / body_dir ────────────────────────────

def test_ema_atr_highest_lowest_bodydir():
    bars = mk_bars(20)    # 4 volle 5er-Kerzen
    src = pine([
        'var float e = na', 'var float a = na', 'var float hh = na', 'var float ll = na',
        'var int bd = na',
        'e := nq.htf_ema(5, 2)', 'a := nq.htf_atr(5, 2)',
        'hh := nq.htf_highest(5, 2)', 'll := nq.htf_lowest(5, 2)', 'bd := nq.htf_body_dir(5, 1)',
    ])
    rec, _ = run_vars(src, bars, ['e', 'a', 'hh', 'll', 'bd'])
    # Kerzen: k0 O100 H106 L99 C104.5 ; k1 O105 H111 L104 C109.5 ; k2 C114.5 H116 L109 ; k3 C119.5 H121 L114
    assert is_na(rec[4]['e'])                         # erst 1 Kerze
    assert rec[9]['e'] == pytest.approx((104.5 + 109.5) / 2)   # Seed SMA
    e2 = 2 / 3 * 114.5 + 1 / 3 * 107.0
    assert rec[14]['e'] == pytest.approx(e2)
    assert rec[13]['e'] == pytest.approx(107.0)       # aendert sich erst nach Schluss
    # ATR: TR0 = 7, TR1 = max(7, |111-104.5|, |104-104.5|) = 7 -> 7 ; TR2 = 7 -> 7
    assert rec[9]['a'] == pytest.approx(7.0)
    assert rec[14]['a'] == pytest.approx(7.0)
    assert rec[14]['hh'] == 116.0 and rec[14]['ll'] == 104.0
    assert is_na(rec[4]['hh'])
    assert rec[19]['bd'] == 1


def test_atr_true_range_gap():
    # Kerze 2 mit Gap: TR aus Vorclose
    bars = mk_bars(10)
    for i in range(5, 10):
        b = bars[i]
        bars[i] = Bar(b.timestamp, b.open + 50, b.high + 50, b.low + 50, b.close + 50, i)
    src = pine(['var float a = na', 'a := nq.htf_atr(5, 1)'])
    rec, _ = run_vars(src, bars, ['a'])
    # k0 C=104.5 ; k1 H=161 L=154 -> TR = 161-104.5 = 56.5
    assert rec[4]['a'] == pytest.approx(7.0)
    assert rec[9]['a'] == pytest.approx(56.5)


# ── Tag / Woche (NY 18:00) ─────────────────────────────────────────────

def test_day_and_week_ny_session():
    # Mi 07.01.2026: 22:58..23:02 UTC = 17:58..18:02 NY (Winterzeit, UTC-5)
    t0 = datetime(2026, 1, 7, 22, 58, tzinfo=timezone.utc)
    bars = mk_bars(5, t0=t0, step=10.0)
    src = pine([
        'var float dh = na', 'var float do0 = na', 'var float dc = na', 'var float dl = na',
        'var float do1 = na', 'var float wh = na', 'var float wl0 = na',
        'dh := nq.htf_day_high(1)', 'do0 := nq.htf_day_open(0)', 'dc := nq.htf_day_close()',
        'dl := nq.htf_day_low(1)', 'do1 := nq.htf_day_open(1)',
        'wh := nq.htf_week_high(0)', 'wl0 := nq.htf_week_low(0)',
    ])
    rec, _ = run_vars(src, bars, ['dh', 'do0', 'dc', 'dl', 'do1', 'wh', 'wl0'])
    # Bars 0,1 (17:58, 17:59) gehoeren zum Handelstag 07.01. -> schliesst mit 17:59
    assert is_na(rec[0]['dh'])
    assert rec[1]['dh'] == 112.0 and rec[1]['dc'] == 110.5 and rec[1]['do1'] == 100.0
    assert rec[1]['dl'] == 99.0
    # Bar 2 = 18:00 NY -> neuer Tag
    assert rec[2]['do0'] == 120.0
    assert rec[2]['dh'] == 112.0
    # Woche laeuft ueber den Tageswechsel weiter
    assert rec[4]['wh'] == 142.0 and rec[4]['wl0'] == 99.0


def test_week_boundary_sunday_18ny():
    # Fr 09.01. 21:59 UTC (16:59 NY) und So 11.01. 23:00 UTC (18:00 NY)
    b0 = Bar(datetime(2026, 1, 9, 21, 59, tzinfo=timezone.utc), 10, 20, 5, 15, 0)
    b1 = Bar(datetime(2026, 1, 11, 23, 0, tzinfo=timezone.utc), 30, 40, 25, 35, 1)
    src = pine(['var float wh1 = na', 'var float wh0 = na',
                'wh1 := nq.htf_week_high(1)', 'wh0 := nq.htf_week_high(0)'])
    rec, _ = run_vars(src, [b0, b1], ['wh1', 'wh0'])
    assert is_na(rec[0]['wh1']) and rec[0]['wh0'] == 20
    assert rec[1]['wh1'] == 20 and rec[1]['wh0'] == 40


# ── request.security ───────────────────────────────────────────────────

def test_request_security_close_lookahead_off():
    bars = mk_bars(12)
    src = pine(['var float s = na', 'var float n = na',
                's := request.security("NQ", "5", close)', 'n := nq.htf_close(5)'])
    rec, _ = run_vars(src, bars, ['s', 'n'])
    assert [r['s'] for r in rec][4:10] == [104.5] * 5 + [109.5]
    for r in rec:
        assert (is_na(r['s']) and is_na(r['n'])) or r['s'] == r['n']


def test_request_security_rejects_expression():
    src = pine(['s = request.security("NQ", "5", close + 1)'])
    with pytest.raises(ValueError):
        run_vars(src, mk_bars(3), [])


def test_bad_timeframe_raises():
    src = pine(['x = nq.htf_close(0)'])
    with pytest.raises(ValueError):
        run_vars(src, mk_bars(2), [])


# ── Handels-Test: Einstieg auf M5-Close-Bedingung ──────────────────────

def test_trade_on_m5_close_condition():
    # Aufwaerts-Bars: erste abgeschlossene M5-Kerze ist gruen (body_dir 1).
    # Bedingung erfuellt ab Bar 4 (14:34, Kerzenschluss) -> Market-Order,
    # Fuellung Bar 5 zum Open 105; Exit TP bei +3 -> 108 (Bar 5 High 107, Bar 6 High 108).
    bars = mk_bars(12)
    src = pine([
        'var bool done = false',
        'c5 = nq.htf_close(5)',
        'o5 = nq.htf_open(5)',
        'if not done and not na(c5) and c5 > o5',
        '    strategy.order("L", strategy.long, qty=1)',
        '    strategy.exit("X", from_entry="L", qty=1, limit=c5 + 3.5, stop=c5 - 20)',
        '    done := true',
    ])
    c = compile_pine(src)
    trades = run_backtest(c, bars)
    assert len(trades) == 1
    t = trades[0]
    assert t.entry_price == 105.0
    assert t.exit_price == 108.0                      # c5 = 104.5 -> TP 108.0
    # Einstieg erst nach Kerzenschluss 14:34 -> Fuellung in Bar 14:35
    assert t.entry_time == T0 + timedelta(minutes=5)
    assert t.exit_time == T0 + timedelta(minutes=6)
    assert t.exit_price - t.entry_price == 3.0        # Punkte


def test_conditional_call_backfill_and_hook():
    # Erster Aufruf erst in Bar 6: History aus den Series nachgefuellt;
    # danach nur jede 2. Bar aufgerufen -> Hook fuettert die uebrigen Bars.
    bars = mk_bars(15)
    src = pine(['var float h = na',
                'if bar_index == 6 or (bar_index > 6 and bar_index % 2 == 0)',
                '    h := nq.htf_high(5)'])
    rec, _ = run_vars(src, bars, ['h'])
    assert rec[6]['h'] == 106.0                       # Kerze 14:30 aus Nachfuellung
    assert rec[10]['h'] == 111.0                      # Kerze 14:35 (Bars 5..9)
    assert rec[14]['h'] == 116.0                      # Kerze 14:40, Bar 13 nicht aufgerufen


def test_no_calls_no_hook():
    src = pine(['x = close'])
    _, ctx = run_vars(src, mk_bars(3), [])
    assert ctx.strategy.broker.get_hook('nq_htf') is None
