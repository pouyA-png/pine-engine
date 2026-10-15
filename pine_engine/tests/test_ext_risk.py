"""Tests fuer pine_engine/ext/risk.py (nq.risk_*, Paket P8).

Grundmuster: flach 100er-Bars; das Skript legt, wenn flach, eine Long-Limit-Order
zum Close mit SL close-5 / TP close+10. Eine "Verlust-Bar" (Open = Limit, Low
unter SL) fuellt zum Open und stoppt in derselben Bar: -5 Punkte x 1 x 20 $ = -100 $.
Eine "Gewinn-Bar" (Open = Limit, High ueber TP) bringt +10 x 20 = +200 $.
"""

from datetime import datetime, timedelta, date

import pytest

from pine_engine.engine import compile_pine, run_backtest, RuntimeContext
from pine_engine.runtime.broker import Bar, BrokerEmulator, ClosedTrade
from pine_engine.ext import risk as R

T0 = datetime(2026, 1, 5, 14, 30)   # UTC, Montag = 15:30 Prag

BODY = '''
if strategy.opentrades == 0
    strategy.order("L", strategy.long, qty=1, limit=close)
    strategy.exit("X", from_entry="L", qty=1, limit=close+10, stop=close-5)
'''


def src(rules=''):
    return '//@version=5\nstrategy("t")\n' + rules + BODY


def mk_bars(kinds, t0=T0, times=None):
    """kinds: 'F' flach, 'L' Verlust-Bar, 'W' Gewinn-Bar (relativ zum Vor-Close)."""
    bars, c = [], 100.0
    for i, k in enumerate(kinds):
        ts = times[i] if times else t0 + timedelta(minutes=i)
        if k == 'F':
            o = h = l = cl = c
        elif k == 'L':
            o, h, l, cl = c, c, c - 6, c - 5
        elif k == 'W':
            o, h, l, cl = c, c + 11, c, c + 10
        else:
            raise ValueError(k)
        bars.append(Bar(ts, o, h, l, cl, i))
        c = cl
    return bars


def usd(t):
    d = (t.exit_price - t.entry_price) if t.side == 'long' else (t.entry_price - t.exit_price)
    return d * t.qty * 20.0


def run(rules, bars):
    return run_backtest(compile_pine(src(rules)), bars)


# ── Grundmuster ohne Regeln ──────────────────────────────────────────────

def test_baseline_no_rules_no_hook():
    bars = mk_bars('FLLLL')
    trades = run('', bars)
    assert [usd(t) for t in trades] == [-100.0] * 4
    ctx = RuntimeContext()
    assert ctx.strategy.broker.hooks == []


# 1. Tagesverlust (weich)
def test_daily_loss_blocks_after_limit():
    bars = mk_bars('FLLLL')
    assert len(run('nq.risk_daily_loss(200)\n', bars)) == 2      # -200 erreicht
    assert len(run('nq.risk_daily_loss(250)\n', bars)) == 3      # -300 < -250 nach 3


def test_daily_loss_resets_next_day():
    # Bars 0-3 am 05.01. (Prag), ab Bar 4 am 06.01. 00:00 Prag (= 23:00 UTC)
    d1 = [datetime(2026, 1, 5, 20, 0) + timedelta(minutes=i) for i in range(4)]
    d2 = [datetime(2026, 1, 5, 23, 0) + timedelta(minutes=i) for i in range(3)]
    bars = mk_bars('FLLLLLL', times=d1 + d2)
    trades = run('nq.risk_daily_loss(200)\n', bars)
    # Tag 1: 2 Verluste, Bar 3 gesperrt. Tag 2: wieder 2 Verluste (Bar 4, 5), Bar 6 gesperrt.
    assert [t.entry_time for t in trades] == [d1[1], d1[2], d2[0], d2[1]]


# 2. Tagesverlust hart (realisiert + offen, Schliessung zum naechsten Open)
HARD_SRC = '''//@version=5
strategy("t")
RULES
if strategy.opentrades == 0 and bar_index == 0
    strategy.order("L", strategy.long, qty=1, limit=close)
    strategy.exit("X", from_entry="L", qty=1, limit=close+100, stop=close-50)
if strategy.opentrades == 0 and bar_index >= 3
    strategy.order("L2", strategy.long, qty=1, limit=close)
'''


def hard_bars():
    ohlc = [(100, 100, 100, 100),   # 0: Order
            (100, 100, 96, 97),     # 1: Fuellung 100, offen -60 $
            (97, 97, 91, 92),       # 2: Close 92 -> offen -160 $
            (93, 94, 92, 93),       # 3: Zwangsschliessung zum Open 93
            (93, 93, 90, 93),       # 4: L2 wuerde fuellen -> gesperrt
            (93, 93, 90, 93)]
    return [Bar(T0 + timedelta(minutes=i), *x, i) for i, x in enumerate(ohlc)]


def test_daily_loss_hard_flattens_at_next_open():
    trades = run_backtest(compile_pine(HARD_SRC.replace('RULES', 'nq.risk_daily_loss_hard(150)')),
                          hard_bars())
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_comment == 'RISK_DAILY_HARD'
    assert t.exit_price == 93 and t.exit_time == T0 + timedelta(minutes=3)
    assert usd(t) == -140.0


def test_daily_loss_soft_does_not_flatten():
    trades = run_backtest(compile_pine(HARD_SRC.replace('RULES', 'nq.risk_daily_loss(150)')),
                          hard_bars())
    assert trades == []          # nur offen, nichts realisiert -> keine Sperre
    assert run_backtest(compile_pine(HARD_SRC.replace('RULES', '')), hard_bars()) == []


# 3. Tagesziel
def test_daily_target_stops_after_profit():
    bars = mk_bars('FWWW')
    assert len(run('', bars)) == 3
    trades = run('nq.risk_daily_target(150)\n', bars)
    assert [usd(t) for t in trades] == [200.0]


# 4. Max. Trades je Tag
def test_max_trades_day():
    d1 = [datetime(2026, 1, 5, 20, 0) + timedelta(minutes=i) for i in range(5)]
    d2 = [datetime(2026, 1, 5, 23, 0) + timedelta(minutes=i) for i in range(3)]
    bars = mk_bars('FWWWWWWW', times=d1 + d2)
    trades = run('nq.risk_max_trades_day(2)\n', bars)
    assert [t.entry_time for t in trades] == [d1[1], d1[2], d2[0], d2[1]]


# 5. Verluste in Folge
def test_max_losses_row():
    bars = mk_bars('FLLLL')
    assert len(run('nq.risk_max_losses_row(2)\n', bars)) == 2
    # Gewinn dazwischen setzt die Serie zurueck: L W L L | gesperrt
    bars = mk_bars('FLWLLL')
    trades = run('nq.risk_max_losses_row(2)\n', bars)
    assert [usd(t) for t in trades] == [-100.0, 200.0, -100.0, -100.0]


# 6. Cooldown nach Verlust
def test_cooldown_minutes():
    bars = mk_bars('FL' + 'L' * 8)
    trades = run('nq.risk_cooldown(5)\n', bars)
    # Verlust in Bar 1 (Exit 14:31) -> Sperre bis 14:36 -> naechste Fuellung Bar 6
    assert [t.entry_time for t in trades][:2] == [T0 + timedelta(minutes=1),
                                                  T0 + timedelta(minutes=6)]
    assert len(trades) == 2      # Verlust in Bar 6 -> gesperrt bis Bar 11 (Ende)


# 7. Max. offene Positionen
MAXOPEN_SRC = '''//@version=5
strategy("t")
RULES
if bar_index == 0
    strategy.order("A", strategy.long, qty=1, limit=close)
    strategy.order("B", strategy.long, qty=1, limit=close)
if bar_index == 3
    strategy.close_all()
'''


def test_max_open():
    bars = mk_bars('FFFF')
    assert len(run_backtest(compile_pine(MAXOPEN_SRC.replace('RULES', '')), bars)) == 2
    trades = run_backtest(compile_pine(MAXOPEN_SRC.replace('RULES', 'nq.risk_max_open(1)')), bars)
    assert [t.entry_id for t in trades] == ['A']


# 8. Gesamtverlust (FTMO max loss) -> dauerhaft aus
def test_total_loss_permanent():
    d1 = [datetime(2026, 1, 5, 20, 0) + timedelta(minutes=i) for i in range(4)]
    d2 = [datetime(2026, 1, 6, 20, 0) + timedelta(minutes=i) for i in range(4)]
    bars = mk_bars('FLLLLLLL', times=d1 + d2)
    trades = run('nq.risk_total_loss(250)\n', bars)
    # 3 Verluste (Tag 1: 3, dann -300 <= -250) -> nie wieder, auch nicht am Folgetag
    assert len(trades) == 3
    assert len(run('', bars)) == 7


# 9. Positionsgroesse
def test_risk_qty_direct_and_pine():
    ctx = RuntimeContext()
    assert R.nq_risk_qty(ctx, {}, 1000, 100, 95) == 10          # 1000 / (5*20)
    assert R.nq_risk_qty(ctx, {}, 1000, 100, 97) == 16          # 1000/60 = 16.67
    assert R.nq_risk_qty(ctx, {}, 50, 100, 95) == 0
    assert R.nq_risk_qty(ctx, {}, 1000, 100, 100) == 0
    s = '''//@version=5
strategy("t")
q = nq.risk_qty(1000, close, close - 5)
if bar_index == 0
    strategy.order("L", strategy.long, qty=q, limit=close)
    strategy.exit("X", from_entry="L", qty=q, limit=close+10, stop=close-5)
'''
    trades = run_backtest(compile_pine(s), mk_bars('FL'))
    assert trades[0].qty == 10 and usd(trades[0]) == -1000.0


# 10. Variablen nq.risk_blocked / nq.risk_day_pnl
def test_variables_blocked_and_day_pnl():
    s = src('''nq.risk_daily_loss(200)
var float pnl = 0.0
var bool bl = false
pnl := nq.risk_day_pnl
bl := nq.risk_blocked
''')
    c = compile_pine(s)
    ctx = RuntimeContext()
    c.initialize(ctx)
    seen = []
    for bar in mk_bars('FLLF'):
        ctx.strategy.process_bar(bar)
        ctx.update_bar(bar)
        c.execute_bar(ctx)
        seen.append((ctx.v_pnl, ctx.v_bl))
    assert seen == [(0.0, False), (-100.0, False), (-200.0, True), (-200.0, True)]


# Zeitzone / Handelstag
def test_day_key_prague_and_new_york():
    h = R.RiskHook()
    assert h.day_key(datetime(2026, 1, 5, 22, 59)) == date(2026, 1, 5)   # 23:59 Prag
    assert h.day_key(datetime(2026, 1, 5, 23, 0)) == date(2026, 1, 6)    # 00:00 Prag
    assert h.day_key(datetime(2026, 7, 5, 21, 59)) == date(2026, 7, 5)   # Sommerzeit
    assert h.day_key(datetime(2026, 7, 5, 22, 0)) == date(2026, 7, 6)
    h.tz, h.rollover_hour = 'America/New_York', 18
    assert h.day_key(datetime(2026, 1, 5, 22, 59)) == date(2026, 1, 5)   # 17:59 NY
    assert h.day_key(datetime(2026, 1, 5, 23, 0)) == date(2026, 1, 6)    # 18:00 NY


def test_timezone_via_pine_changes_day_boundary():
    # Verluste 22:58/22:59 UTC, dritter Versuch 23:00 UTC (= 00:00 Prag, 23:00 London).
    times = [datetime(2026, 1, 5, 22, 57) + timedelta(minutes=i) for i in range(4)]
    bars = mk_bars('FLLL', times=times)
    # Prag (Default): 23:00 UTC = neuer Tag -> dritter Verlust erlaubt
    assert len(run('nq.risk_daily_loss(200)\n', bars)) == 3
    # London (Wechsel 00:00 London = 00:00 UTC) -> gleicher Tag -> gesperrt
    assert len(run('nq.risk_daily_loss(200)\nnq.risk_timezone("Europe/London")\n', bars)) == 2


# Kosten aus extra['cost_usd']
def test_cost_usd_counts_in_realized():
    b = BrokerEmulator()
    h = R.RiskHook(20.0)
    b.add_hook(h)
    ct = ClosedTrade('L', 'long', 1, 100.0, 105.0, '', 'tp',
                     entry_time=T0, exit_time=T0 + timedelta(minutes=1))
    ct.extra['cost_usd'] = 40.0
    b.record_close(ct)
    h.daily_target = 100.0
    h.sync(b)
    assert h.realized_day[h.day_key(T0)] == 60.0      # 5*20 - 40
    assert h.evaluate(b, h.day_key(T0), None) is False  # 60 < 100


def test_setter_idempotent_and_na_disables():
    s = src('nq.risk_daily_loss(200)\nnq.risk_daily_loss(na)\n')
    assert len(run_backtest(compile_pine(s), mk_bars('FLLLL'))) == 4
