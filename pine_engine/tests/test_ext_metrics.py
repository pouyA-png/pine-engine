"""P10 — Auswertung (metrics_ext) + Excursion-Tracking (nq.track_excursion)."""

import csv
import math
import sys
from datetime import datetime, timedelta

import pytest

from pine_engine.engine import compile_pine, run_backtest
from pine_engine.runtime.broker import Bar, ClosedTrade
from pine_engine.reporting import metrics_ext as mx


def _bars(rows, t0=datetime(2026, 1, 5, 14, 30)):
    return [Bar(t0 + timedelta(minutes=i), o, h, l, c, i)
            for i, (o, h, l, c) in enumerate(rows)]


def _ct(side, et, xt, ep, xp, qty=1, eid='L', **extra):
    return ClosedTrade(entry_id=eid, side=side, qty=qty, entry_price=ep, exit_price=xp,
                       entry_comment='e', exit_comment='x', entry_time=et, exit_time=xt,
                       extra=dict(extra))


# Januar = EST (UTC-5): 15:00 UTC = 10:00 NY
T = [
    _ct('long', datetime(2026, 1, 5, 15, 0), datetime(2026, 1, 5, 15, 30), 100, 110,
        cost_usd=4.0, r0=5.0, exit_kind='TP'),
    _ct('short', datetime(2026, 1, 6, 16, 0), datetime(2026, 1, 6, 16, 10), 100, 105,
        cost_usd=4.0, r0=5.0, exit_kind='SL'),
    _ct('long', datetime(2026, 1, 6, 17, 0), datetime(2026, 1, 6, 17, 30), 100, 97, qty=2,
        cost_usd=8.0, r0=5.0, exit_kind='SL'),
    _ct('long', datetime(2026, 2, 2, 15, 0), datetime(2026, 2, 3, 15, 0), 100, 120,
        foo='bar'),
]


def test_summary_net_gross_pf_wr_expectancy():
    s = mx.summary(T, point_value=20)
    assert s['count'] == 4
    assert s['gross_usd'] == pytest.approx(380.0)     # 200 - 100 - 120 + 400
    assert s['cost_usd'] == pytest.approx(16.0)
    assert s['net_usd'] == pytest.approx(364.0)
    assert s['profit_factor'] == pytest.approx(596.0 / 232.0)
    assert s['profit_factor_gross'] == pytest.approx(600.0 / 220.0)
    assert s['win_rate'] == pytest.approx(50.0)
    assert s['expectancy_usd'] == pytest.approx(91.0)
    # R: 196/100, -104/100, -128/200 ; Trade 4 ohne r0 -> ausgelassen
    assert s['r_count'] == 3
    assert s['expectancy_r'] == pytest.approx((1.96 - 1.04 - 0.64) / 3)


def test_drawdown_and_duration():
    s = mx.summary(T, point_value=20, initial_capital=100000)
    assert s['max_drawdown_usd'] == pytest.approx(232.0)
    assert s['max_drawdown_pct'] == pytest.approx(0.232)
    # Hoch 05.01. 15:30 -> Erholung 03.02. 15:00
    exp_days = (datetime(2026, 2, 3, 15, 0) - datetime(2026, 1, 5, 15, 30)).total_seconds() / 86400
    assert s['max_drawdown_days'] == pytest.approx(exp_days)


def test_drawdown_unrecovered_until_end():
    tr = [_ct('long', datetime(2026, 1, 5, 15), datetime(2026, 1, 5, 16), 100, 110),
          _ct('long', datetime(2026, 1, 7, 15), datetime(2026, 1, 8, 16), 100, 95)]
    s = mx.summary(tr, point_value=20, initial_capital=1000)
    assert s['max_drawdown_usd'] == pytest.approx(100.0)
    assert s['max_drawdown_pct'] == pytest.approx(10.0)
    assert s['max_drawdown_days'] == pytest.approx(3.0)


def test_sharpe_sortino_daily_ny():
    s = mx.summary(T, point_value=20)
    d = [196.0, -232.0, 400.0]          # NY-Tage 05.01., 06.01., 03.02.
    assert s['trading_days'] == 3
    m = sum(d) / 3
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / 2)
    dn = math.sqrt(232.0 ** 2 / 3)
    assert s['sharpe_daily'] == pytest.approx(m / sd * math.sqrt(252))
    assert s['sortino_daily'] == pytest.approx(m / dn * math.sqrt(252))


def test_ny_day_boundary():
    # 03:00 UTC am 06.01. = 22:00 NY am 05.01. -> gleicher NY-Tag wie 15:30 UTC am 05.01.
    tr = [_ct('long', datetime(2026, 1, 5, 15), datetime(2026, 1, 5, 15, 30), 100, 101),
          _ct('long', datetime(2026, 1, 6, 2), datetime(2026, 1, 6, 3), 100, 101)]
    s = mx.summary(tr)
    assert s['trading_days'] == 1
    assert s['sharpe_daily'] is None


def test_streaks_weekday_hour_month_year():
    s = mx.summary(T, point_value=20)
    assert s['max_consec_wins'] == 1 and s['max_consec_losses'] == 2
    assert set(s['by_weekday']) == {0, 1}
    assert s['by_weekday'][0]['n'] == 2 and s['by_weekday'][0]['net'] == pytest.approx(596.0)
    assert s['by_weekday'][1]['net'] == pytest.approx(-232.0)
    assert s['by_weekday'][1]['win_rate'] == 0.0
    assert {k: v['net'] for k, v in s['by_hour'].items()} == pytest.approx(
        {10: 596.0, 11: -104.0, 12: -128.0})
    assert s['by_month'] == pytest.approx({'2026-01': -36.0, '2026-02': 400.0})
    assert s['by_year'] == pytest.approx({2026: 364.0})


def test_r_histogram():
    s = mx.summary(T, point_value=20)
    h = {b['bucket']: b['n'] for b in s['r_hist']}
    assert h['[1,2)'] == 1 and h['[-2,-1)'] == 1 and h['[-1,-0.5)'] == 1
    assert sum(h.values()) == 3
    # ohne r0 -> keine R-Kennzahlen
    s2 = mx.summary([T[3]])
    assert s2['r_hist'] is None and s2['expectancy_r'] is None


def test_group_by_entry_partial_exits():
    et = datetime(2026, 1, 5, 15)
    tr = [_ct('long', et, et + timedelta(minutes=5), 100, 110, eid='L', cost_usd=2.0, r0=10.0),
          _ct('long', et, et + timedelta(minutes=9), 100, 130, eid='L', cost_usd=2.0, r0=10.0),
          # gleiche entry_id, andere Position (spaeter)
          _ct('long', et + timedelta(days=1), et + timedelta(days=1, minutes=3), 100, 90,
              eid='L', r0=10.0)]
    assert mx.summary(tr)['count'] == 3
    s = mx.summary(tr, group_by_entry=True)
    assert s['count'] == 2
    assert s['net_usd'] == pytest.approx(796.0 - 200.0)
    recs = mx.records(tr, 20.0, group_by_entry=True)
    assert recs[0]['qty'] == 2 and recs[0]['n_parts'] == 2
    assert recs[0]['r'] == pytest.approx(796.0 / (10 * 2 * 20))
    assert recs[0]['exit_price'] == pytest.approx(120.0)
    assert recs[1]['r'] == pytest.approx(-1.0)


def test_empty_and_format():
    assert mx.summary([])['count'] == 0
    assert mx.format_summary(mx.summary([])) == 'Keine Trades.'
    txt = mx.format_summary(mx.summary(T))
    assert 'Profit Factor' in txt and 'R-Verteilung' in txt and '2026' in txt


def test_export_csv(tmp_path):
    p = tmp_path / 'tr.csv'
    n = mx.export_trades(T, str(p), point_value=20)
    assert n == 4
    rows = list(csv.DictReader(open(p)))
    for col in ('exit_kind', 'cost_usd', 'mfe', 'mae', 'r0', 'net_usd', 'r_mult', 'foo'):
        assert col in rows[0]
    assert rows[0]['exit_kind'] == 'TP'
    assert float(rows[0]['net_usd']) == pytest.approx(196.0)
    assert float(rows[0]['r_mult']) == pytest.approx(1.96)
    assert rows[3]['cost_usd'] == '' and rows[3]['foo'] == 'bar'


# ── Excursion-Tracking ueber compile_pine/run_backtest ─────────────────────

LONG_SRC = '''//@version=5
strategy("t")
nq.track_excursion()
if bar_index == 1
    strategy.order("L", strategy.long, qty=1, limit=close)
    strategy.exit("X", from_entry="L", qty=1, limit=close+20, stop=close-10)
'''


def test_excursion_long_tp():
    rows = [(100, 101, 99, 100), (100, 101, 99, 100),
            (100.5, 110, 95, 105),     # Fuellung @100; Hoch/Tief der Fuellbar ausgeschlossen
            (104, 112, 97, 108),       # volle Bar: Hoch 112, Tief 97
            (108, 125, 106, 122)]      # TP @120; Hoch 125 der Ausstiegsbar ausgeschlossen
    tr = run_backtest(compile_pine(LONG_SRC), _bars(rows))
    assert len(tr) == 1
    t = tr[0]
    assert (t.entry_price, t.exit_price) == (100, 120)
    assert t.extra['mfe'] == pytest.approx(20.0)   # bis Ausstieg 120 (nicht 125)
    assert t.extra['mae'] == pytest.approx(3.0)    # Tief 97 (nicht 95 der Fuellbar)


def test_excursion_absent_without_call():
    src = LONG_SRC.replace('nq.track_excursion()\n', '')
    rows = [(100, 101, 99, 100), (100, 101, 99, 100), (100.5, 110, 95, 105),
            (104, 112, 97, 108), (108, 125, 106, 122)]
    tr = run_backtest(compile_pine(src), _bars(rows))
    assert len(tr) == 1 and 'mfe' not in tr[0].extra and tr[0].exit_price == 120


SHORT_SRC = '''//@version=5
strategy("t")
nq.track_excursion()
if bar_index == 1
    strategy.order("S", strategy.short, qty=2, limit=close)
    strategy.exit("T1", from_entry="S", qty=1, limit=close-10, stop=close+10)
if bar_index == 5
    strategy.close("S")
'''


def test_excursion_short_partial_and_close():
    rows = [(100, 101, 99, 100), (100, 101, 99, 100),
            (99.5, 103, 96, 98),       # Fuellung @100 (Fuellbar ausgeschlossen)
            (97, 99, 92, 93),          # voll: 99 / 92
            (93, 102, 89, 95),         # TP1 @90 -> Teil 1; Rest erlebt danach 102/89
            (95, 97, 94, 96)]          # strategy.close @96
    tr = run_backtest(compile_pine(SHORT_SRC), _bars(rows))
    assert len(tr) == 2
    a, b = tr
    assert a.exit_price == 90 and a.qty == 1
    assert a.extra['mfe'] == pytest.approx(10.0) and a.extra['mae'] == pytest.approx(0.0)
    assert b.exit_price == 96 and b.qty == 1
    assert b.extra['mfe'] == pytest.approx(11.0)   # Tief 89
    assert b.extra['mae'] == pytest.approx(2.0)    # Hoch 102
    # Aggregation je Position: mfe/mae = Maximum der Teile
    g = mx.records(tr, 20.0, group_by_entry=True)
    assert len(g) == 1 and g[0]['mfe'] == pytest.approx(11.0) and g[0]['mae'] == pytest.approx(2.0)


# ── CLI ────────────────────────────────────────────────────────────────────

def _run_cli(monkeypatch, capsys, argv):
    from pine_engine import main as m
    monkeypatch.setattr(sys, 'argv', ['main'] + argv)
    m.main()
    out = capsys.readouterr().out
    return '\n'.join(l for l in out.splitlines() if not l.startswith('RESULTS ('))


def test_cli_flags(tmp_path, monkeypatch, capsys):
    pine = tmp_path / 's.pine'
    pine.write_text(LONG_SRC)
    data = tmp_path / 'b.csv'
    rows = [(100, 101, 99, 100), (100, 101, 99, 100), (100.5, 110, 95, 105),
            (104, 112, 97, 108), (108, 125, 106, 122)]
    with open(data, 'w') as f:
        f.write('datetime,open,high,low,close\n')
        for i, (o, h, l, c) in enumerate(rows):
            f.write(f'2026-01-05 14:{30 + i:02d}:00,{o},{h},{l},{c}\n')
    base = _run_cli(monkeypatch, capsys, ['run', str(pine), '--data', str(data)])
    assert 'ERWEITERTE' not in base and 'Total trades: 1' in base
    csvp = tmp_path / 'out.csv'
    ext = _run_cli(monkeypatch, capsys, ['run', str(pine), '--data', str(data),
                                         '--metrics', '--export-trades', str(csvp)])
    assert ext.startswith(base)                  # Default-Teil unveraendert
    assert 'ERWEITERTE KENNZAHLEN' in ext and 'Netto $:' in ext
    rows_out = list(csv.DictReader(open(csvp)))
    assert len(rows_out) == 1 and float(rows_out[0]['mfe']) == pytest.approx(20.0)
    assert float(rows_out[0]['net_usd']) == pytest.approx(400.0)
