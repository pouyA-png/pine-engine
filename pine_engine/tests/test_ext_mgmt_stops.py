"""P7 Positionsmanagement: BE, Trailing, Zeit-Exits — jeder Exitpreis nachgerechnet."""
from datetime import datetime, timedelta

from pine_engine.engine import compile_pine, run_backtest, RuntimeContext
from pine_engine.runtime.broker import Bar

T0 = datetime(2026, 1, 5, 14, 30)  # UTC


def bars(rows, t0=T0):
    return [Bar(t0 + timedelta(minutes=i), o, h, l, c, i) for i, (o, h, l, c) in enumerate(rows)]


def long_src(mgmt, qty=1, tp=1000, stop=90, tp2=None):
    s = '//@version=5\nstrategy("t")\n' + mgmt + '\n'
    s += 'if bar_index == 0\n    strategy.order("L", strategy.long, qty=%d, limit=100)\n' % (qty if tp2 is None else 2)
    if tp2 is None:
        s += 'strategy.exit("X", from_entry="L", qty=%d, limit=%s, stop=%s)\n' % (qty, tp, stop)
    else:
        s += 'strategy.exit("X1", from_entry="L", qty=1, limit=%s, stop=%s)\n' % (tp, stop)
        s += 'strategy.exit("X2", from_entry="L", qty=1, limit=%s, stop=%s)\n' % (tp2, stop)
    return s


def run(src, rows, t0=T0):
    return run_backtest(compile_pine(src), bars(rows, t0))


def run_ctx(src, rows, t0=T0):
    c = compile_pine(src)
    ctx = RuntimeContext(params=c.get_default_params())
    c.initialize(ctx)
    for b in bars(rows, t0):
        ctx.strategy.process_bar(b)
        ctx.update_bar(b)
        c.execute_bar(ctx)
        ctx.strategy.process_entrybar_exits()
    return ctx


FILL = [(105, 106, 104, 105), (101, 102, 99, 101)]   # b0 Order, b1 Fuellung @100, r0 = 10


def test_be_after_tp1_moves_rest_to_entry():
    # b2: TP1 @110 (qty 1). b3: Stop des Rests = Entry 100 -> Tief 99.5 trifft, Exit 100.
    rows = FILL + [(105, 111, 104, 110), (108, 109, 99.5, 100)]
    tr = run(long_src('nq.be_after_partial(0)', tp=110, tp2=130), rows)
    assert [(t.exit_price, t.qty) for t in tr] == [(110, 1), (100, 1)]
    assert tr[1].extra['exit_kind'] == 'be' and tr[1].exit_time == T0 + timedelta(minutes=3)
    # Gegenprobe ohne Aufruf: Stop 90 bleibt, Rest offen.
    tr0 = run(long_src('', tp=110, tp2=130), rows)
    assert [t.exit_price for t in tr0] == [110]


def test_be_after_partial_offset_points():
    rows = FILL + [(105, 111, 104, 110), (108, 109, 101.5, 102)]
    tr = run(long_src('nq.be_after_partial(2)', tp=110, tp2=130), rows)
    assert [t.exit_price for t in tr] == [110, 102]   # 100 + 2 Punkte


def test_trail4_1_no_lookahead():
    # r0 = 10. b2 Hoch 141 (4,1 R) und Tief 125 in DERSELBEN Bar -> kein Exit in b2 (kein Lookahead).
    # b3: Stop = 141 - 1 R = 131, Tief 128 -> Exit 131 = +3,1 R.
    rows = FILL + [(101, 141, 125, 135), (135, 138, 128, 130)]
    tr = run(long_src('nq.trail_r(4, 1)'), rows)
    assert len(tr) == 1 and tr[0].exit_price == 131 and tr[0].exit_time == T0 + timedelta(minutes=3)
    assert tr[0].extra['exit_kind'] == 'trail'
    # Unter 4 R (Hoch 139) kein Trailing -> kein Exit.
    rows2 = FILL + [(101, 139, 125, 135), (135, 138, 128, 130)]
    assert run(long_src('nq.trail_r(4, 1)'), rows2) == []


def test_trail_r_short():
    src = ('//@version=5\nstrategy("t")\nnq.trail_r(2, 1)\n'
           'if bar_index == 0\n    strategy.order("S", strategy.short, qty=1, limit=100)\n'
           'strategy.exit("X", from_entry="S", qty=1, limit=1, stop=110)\n')
    rows = [(95, 96, 94, 95), (99, 101, 98, 99), (99, 100, 79, 85), (85, 91, 84, 90)]
    # Fuellung 100, r0 10, Tief 79 = 2,1 R -> Stop 79 + 10 = 89; b3 Hoch 91 -> Exit 89.
    tr = run(src, rows)
    assert [t.exit_price for t in tr] == [89]


def test_be_at_r():
    rows = FILL + [(101, 111, 104, 110), (108, 109, 100, 100.5)]
    tr = run(long_src('nq.be_at_r(1, 0.1)'), rows)
    assert [t.exit_price for t in tr] == [101]   # 100 + 0,1 * 10


def test_be_at_points():
    rows = FILL + [(101, 106, 104, 105), (104, 105, 100, 100.5)]
    tr = run(long_src('nq.be_at_points(5, 1)'), rows)
    assert [t.exit_price for t in tr] == [101]


def test_trail_points_and_gap():
    # Start 20 Punkte, Abstand 5: Hoch 125 -> Stop 120; b3 oeffnet 118 (Gap) -> Exit 118 = Open.
    rows = FILL + [(101, 125, 110, 124), (118, 119, 117, 118)]
    tr = run(long_src('nq.trail_points(20, 5)'), rows)
    assert [t.exit_price for t in tr] == [118]


def test_trail_step():
    # step 1 R = 10: Hoch 131 = 3,1 R -> Stop Entry + 2 R = 120.
    rows = FILL + [(101, 131, 121, 125), (125, 126, 119, 120)]
    tr = run(long_src('nq.trail_step(1)'), rows)
    assert [t.exit_price for t in tr] == [120]
    # 1,9 R -> noch kein Lock-in
    rows2 = FILL + [(101, 119, 101, 110), (110, 111, 95, 100)]
    assert run(long_src('nq.trail_step(1)'), rows2) == []


def test_trail_bars():
    # n = 2: nach b1 (Tief 99) und b2 (Tief 104) -> Stop in b3 = min(99, 104) = 99, nicht getroffen.
    # nach b2, b3 (Tief 106) -> Stop in b4 = 104; b4 Tief 103 -> Exit 104.
    rows = FILL + [(101, 108, 104, 107), (107, 110, 106, 109), (108, 109, 103, 104)]
    tr = run(long_src('nq.trail_bars(2)'), rows)
    assert [t.exit_price for t in tr] == [104]
    assert tr[0].exit_time == T0 + timedelta(minutes=4)


def test_stops_only_tighten():
    # Skript-Stop 99 ist enger als trail_points-Stop (Hoch 121 - 25 = 96) -> 99 bleibt.
    rows = [(105, 106, 104, 105), (101, 102, 99.8, 101), (101, 121, 110, 115), (110, 111, 98, 100)]
    tr = run(long_src('nq.trail_points(20, 25)', stop=99), rows)
    assert [t.exit_price for t in tr] == [99]
    assert tr[0].extra['exit_kind'] == 'sl'


def test_time_stop():
    # Fuellung b1 (14:31), 3 Minuten -> Schliessung zum Open der Bar 14:34 (b4) = 103.
    rows = FILL + [(101, 102, 100, 101), (101, 102, 100, 102), (103, 104, 102, 103)]
    tr = run(long_src('nq.time_stop(3)'), rows)
    assert [(t.exit_price, t.exit_comment, t.extra['exit_kind']) for t in tr] == [(103, 'TIME_STOP', 'time')]
    assert tr[0].exit_time == T0 + timedelta(minutes=4)


def test_time_stop_skipped_after_tp():
    rows = FILL + [(105, 111, 104, 110), (110, 112, 109, 111), (111, 112, 110, 111)]
    tr = run(long_src('nq.time_stop(2)', tp=110, tp2=130), rows)
    assert [t.exit_price for t in tr] == [110]


def test_time_max_bars():
    # Fuellbar zaehlt als 1: n = 2 -> Schliessung zum Open von b3 = 102.5.
    rows = FILL + [(101, 102, 100, 101), (102.5, 104, 102, 103)]
    tr = run(long_src('nq.time_max_bars(2)'), rows)
    assert [(t.exit_price, t.exit_comment) for t in tr] == [(102.5, 'TIME_MAX_BARS')]


def test_eod_flat_closes_and_cancels():
    # Januar: 16:00 NY = 21:00 UTC. Start 20:58 UTC.
    t0 = datetime(2026, 1, 5, 20, 58)
    src = ('//@version=5\nstrategy("t")\nnq.eod_flat(1600)\n'
           'if bar_index == 0\n    strategy.order("L", strategy.long, qty=1, limit=100)\n'
           '    strategy.order("L2", strategy.long, qty=1, limit=50)\n'
           'strategy.exit("X", from_entry="L", qty=1, limit=1000, stop=90)\n')
    rows = [(105, 106, 104, 105), (101, 102, 99, 101), (98, 99, 40, 45), (45, 46, 40, 45)]
    ctx = run_ctx(src, rows, t0)
    tr = ctx.strategy.get_results()
    # b2 (21:00 UTC = 16:00 NY): L schliesst zum Open 98, L2 (Limit 50, Tief 40) wird NICHT gefuellt.
    assert [(t.entry_id, t.exit_price, t.exit_comment, t.extra['exit_kind']) for t in tr] == [('L', 98, 'EOD_FLAT', 'eod')]
    assert ctx.strategy.broker.pending_orders == {} and ctx.strategy.broker.open_trades == {}


def test_off_switches_and_idempotent():
    src = long_src('nq.trail_r(4, 1)\nnq.trail_r(4, 1)\nif bar_index >= 1\n    nq.trail_off()')
    rows = FILL + [(101, 141, 125, 135), (135, 138, 128, 130)]
    ctx = run_ctx(src, rows)
    assert ctx.strategy.get_results() == []
    assert len(ctx.strategy.broker.hooks) == 1
    src2 = long_src('nq.be_at_r(1)\nif bar_index >= 1\n    nq.be_off()')
    rows2 = FILL + [(101, 111, 104, 110), (108, 109, 99.5, 100)]
    assert run(src2, rows2) == []


def test_default_unchanged_no_hook():
    rows = FILL + [(101, 141, 125, 135), (135, 138, 88, 90)]
    ctx = run_ctx(long_src(''), rows)
    assert ctx.strategy.broker.hooks == []
    assert [t.exit_price for t in ctx.strategy.get_results()] == [90]


def test_r0_recorded():
    rows = FILL + [(101, 102, 100, 101)]
    ctx = run_ctx(long_src('nq.trail_r(4, 1)'), rows)
    assert ctx.strategy.broker.open_trades['L'].extra['r0'] == 10


def test_position_without_exit_spec_gets_mgmt_stop():
    # Kein strategy.exit: Hook legt Stop-only-Spec an. Hoch 125 -> Stop 120; b3 Tief 119 -> Exit 120.
    src = ('//@version=5\nstrategy("t")\nnq.trail_points(20, 5)\n'
           'if bar_index == 0\n    strategy.order("L", strategy.long, qty=1, limit=100)\n')
    rows = FILL + [(101, 125, 110, 124), (122, 123, 119, 120)]
    tr = run(src, rows)
    assert [(t.exit_price, t.exit_comment, t.extra['exit_kind']) for t in tr] == [(120, 'MGMT_STOP', 'trail')]


def test_r0_reaches_closed_trade_for_metrics():
    """r0 (Anfangsrisiko, Punkte) landet im ClosedTrade, damit metrics_ext R rechnen kann."""
    from datetime import datetime, timedelta
    from pine_engine.engine import compile_pine, run_backtest
    from pine_engine.runtime.broker import Bar
    from pine_engine.reporting.metrics_ext import summary
    src = '''//@version=5
strategy("t")
nq.be_at_r(1)
if bar_index == 0
    strategy.order("L", strategy.long, qty=1, limit=100)
    strategy.exit("X", from_entry="L", qty=1, limit=120, stop=90)
'''
    ohlc = [(100, 101, 99, 100), (100, 101, 99.5, 100), (100, 105, 99, 104), (104, 121, 103, 120)]
    t0 = datetime(2026, 1, 5, 14, 30)
    bars = [Bar(t0 + timedelta(minutes=i), o, h, l, c, i) for i, (o, h, l, c) in enumerate(ohlc)]
    trades = run_backtest(compile_pine(src), bars)
    assert len(trades) == 1 and trades[0].exit_price == 120
    assert trades[0].extra['r0'] == 10
    s = summary(trades)
    assert abs(s['expectancy_r'] - 2.0) < 1e-9
