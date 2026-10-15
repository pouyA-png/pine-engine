"""P1b — Entries + Ordertypen: Stop/Stop-Limit/Market, strategy.entry
(Reversal, Pyramiding), strategy.close Teilschliessung, exit_kind, expire_bars,
Richtungsfilter, Limit-Fuellung erst ab Folgebar, OCA-Cancel."""
from datetime import datetime, timedelta
import pytest
from pine_engine.engine import compile_pine, run_backtest
from pine_engine.runtime.broker import Bar, BrokerEmulator

T0 = datetime(2026, 1, 5, 14, 30)


def bars(rows):
    return [Bar(T0 + timedelta(minutes=i), o, h, l, c, i)
            for i, (o, h, l, c) in enumerate(rows)]


def run(body, rows, header='strategy("t")'):
    src = '//@version=5\n' + header + '\n' + body
    return run_backtest(compile_pine(src), bars(rows))


FLAT = (100, 101, 99, 100)


def summary(trades):
    return [(t.entry_id, t.side, t.qty, t.entry_price, t.exit_price,
             t.exit_comment, t.extra.get('exit_kind')) for t in trades]


# ── 1. Stop-Entry ──
def test_stop_entry_long_intrabar_and_close():
    body = '''if bar_index == 0
    strategy.order("L", strategy.long, qty=2, stop=105)
if bar_index == 3
    strategy.close_all(comment="EOD")
'''
    rows = [FLAT, (101, 104, 100, 103), (103, 107, 102, 106), (106, 108, 105, 107)]
    tr = run(body, rows)
    # Bar1 high 104 < 105 -> nein; Bar2 high 107 >= 105, open 103 < 105 -> Fuellung 105
    assert summary(tr) == [('L', 'long', 2, 105, 107, 'EOD', 'close')]
    assert tr[0].entry_time == T0 + timedelta(minutes=2)


def test_stop_entry_long_gap_fills_at_open():
    body = 'if bar_index == 0\n    strategy.order("L", strategy.long, qty=1, stop=105)\nif bar_index == 1\n    strategy.close_all()\n'
    tr = run(body, [FLAT, (108, 110, 107, 109)])
    assert tr[0].entry_price == 108          # max(open 108, stop 105)
    assert tr[0].exit_price == 109


def test_stop_entry_short_mirrored():
    body = 'if bar_index == 0\n    strategy.order("S", strategy.short, qty=1, stop=95)\nif bar_index == 2\n    strategy.close_all()\n'
    tr = run(body, [FLAT, (99, 100, 96, 97), (97, 98, 93, 94)])
    assert summary(tr) == [('S', 'short', 1, 95, 94, 'close_all', 'close')]


def test_stop_limit_long_trigger_then_limit():
    # S=105 <= L=106: Trigger intrabar bei 105 -> sofort Fuellung zu 105
    body = 'if bar_index == 0\n    strategy.order("L", strategy.long, qty=1, stop=105, limit=106)\nif bar_index == 1\n    strategy.close_all()\n'
    tr = run(body, [FLAT, (103, 107, 102, 106)])
    assert tr[0].entry_price == 105
    # S=105 > L=103: Trigger in Bar1, Reihenfolge unbekannt -> Limit ab Bar2 (open 104, low 102 -> 103)
    body = 'if bar_index == 0\n    strategy.order("L", strategy.long, qty=1, stop=105, limit=103)\nif bar_index == 2\n    strategy.close_all()\n'
    tr = run(body, [FLAT, (103, 107, 102, 106), (104, 105, 102, 104)])
    assert (tr[0].entry_price, tr[0].entry_time) == (103, T0 + timedelta(minutes=2))


def test_stop_limit_gap_above_limit_waits():
    # Gap-Open 110 > S und > L=106, low 107 > L -> keine Fuellung; Bar2 low 105 -> 106
    body = 'if bar_index == 0\n    strategy.order("L", strategy.long, qty=1, stop=105, limit=106)\nif bar_index == 2\n    strategy.close_all()\n'
    tr = run(body, [FLAT, (110, 111, 107, 108), (108, 109, 105, 107)])
    assert tr[0].entry_price == 106 and tr[0].entry_time == T0 + timedelta(minutes=2)


# ── 2. Market ──
def test_market_order_fills_next_open():
    body = 'if bar_index == 0\n    strategy.order("L", strategy.long, qty=3)\nif bar_index == 2\n    strategy.close_all()\n'
    tr = run(body, [FLAT, (102, 104, 101, 103), (103, 106, 102, 105)])
    assert summary(tr) == [('L', 'long', 3, 102, 105, 'close_all', 'close')]
    # PnL: (105-102)*3 = 9 Punkte
    assert (tr[0].exit_price - tr[0].entry_price) * tr[0].qty == 9


# ── 3. strategy.entry: Reversal + gleiche Richtung ignoriert ──
def test_entry_reversal_same_fill_price():
    body = '''if bar_index == 0
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 2
    strategy.entry("S", strategy.short, qty=2)
if bar_index == 4
    strategy.close_all(comment="END")
'''
    rows = [FLAT, (101, 102, 100, 101), (101, 103, 100, 102), (104, 105, 103, 104), (104, 104, 98, 99)]
    tr = run(body, rows)
    # L: Fuellung Bar1 open 101; Reversal Bar3 open 104 -> L schliesst 104, S eroeffnet 104
    assert summary(tr) == [('L', 'long', 1, 101, 104, 'S', 'reverse'),
                           ('S', 'short', 2, 104, 99, 'END', 'close')]


def test_entry_same_direction_ignored_default_pyramiding():
    body = '''if bar_index == 0
    strategy.entry("A", strategy.long, qty=1)
if bar_index == 1
    strategy.entry("B", strategy.long, qty=1)
if bar_index == 3
    strategy.close_all()
'''
    tr = run(body, [FLAT] * 4)
    assert [t.entry_id for t in tr] == ['A']


# ── 4. pyramiding=N ──
def test_pyramiding_from_strategy_declaration():
    body = '''if bar_index <= 2
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 4
    strategy.close("L", comment="X")
'''
    rows = [FLAT, (100, 101, 99, 100), (102, 103, 101, 102), (104, 105, 103, 104), (106, 107, 105, 106)]
    tr = run(body, rows, header='strategy("t", pyramiding=2)')
    # max 2 Entries: Bar1 (100) und Bar2 (102); die dritte (Bar3) wird verworfen
    assert summary(tr) == [('L', 'long', 1, 100, 106, 'X', 'close'),
                           ('L#2', 'long', 1, 102, 106, 'X', 'close')]
    code = compile_pine('//@version=5\nstrategy("t", pyramiding=2)\nstrategy.entry("L", strategy.long)\n').python_code
    assert 'pyramiding=2' in code


# ── 5./6. strategy.close Teilschliessung + exit_kind ──
def test_close_partial_qty_and_percent():
    body = '''if bar_index == 0
    strategy.order("L", strategy.long, qty=10)
if bar_index == 2
    strategy.close("L", qty=3, comment="P1")
if bar_index == 3
    strategy.close("L", qty_percent=50, comment="P2")
if bar_index == 4
    strategy.close("L")
'''
    rows = [FLAT, (100, 101, 99, 100), (100, 103, 99, 102), (102, 105, 101, 104), (104, 107, 103, 106)]
    tr = run(body, rows)
    # 10 -> 3 zu 102, 50 % von 7 = 3 (abgerundet) zu 104, Rest 4 zu 106
    assert summary(tr) == [('L', 'long', 3, 100, 102, 'P1', 'close'),
                           ('L', 'long', 3, 100, 104, 'P2', 'close'),
                           ('L', 'long', 4, 100, 106, 'close', 'close')]
    assert sum((t.exit_price - t.entry_price) * t.qty for t in tr) == 3*2 + 3*4 + 4*6


def test_close_positional_comment():
    code = compile_pine('strategy.close("L", "why")').python_code
    assert 'ctx.strategy.close("L", comment="why")' in code
    code = compile_pine('strategy.close("L", comment="c")').python_code
    assert 'ctx.strategy.close("L", comment="c")' in code      # Altform unveraendert


# ── 7. expire_bars ──
@pytest.mark.parametrize('n,filled', [(2, False), (3, True)])
def test_expire_bars(n, filled):
    body = f'''if bar_index == 0
    strategy.order("L", strategy.long, qty=1, limit=95, expire_bars={n})
if bar_index == 4
    strategy.close_all()
'''
    rows = [FLAT, FLAT, FLAT, (99, 100, 94, 96), (96, 97, 95, 96)]
    tr = run(body, rows)
    # Chancen: Bar1..BarN; Level 95 erst in Bar3 erreicht
    assert (len(tr) == 1) is filled
    if filled:
        assert tr[0].entry_price == 95


# ── 8. Richtungsfilter + Konstanten ──
def test_allow_entry_in_long_only():
    body = '''strategy.risk.allow_entry_in(strategy.direction.long)
if bar_index == 0
    strategy.entry("S", strategy.short, qty=1)
if bar_index == 1
    strategy.entry("L", strategy.long, qty=1)
if bar_index == 3
    strategy.entry("S2", strategy.short, qty=1)
if bar_index == 5
    strategy.close_all()
'''
    rows = [FLAT, FLAT, (101, 102, 100, 101), (101, 102, 100, 101), (103, 104, 102, 103), FLAT]
    tr = run(body, rows)
    # S verworfen; L Bar2 open 101; S2 schliesst nur L zu Bar4 open 103, kein Short
    assert summary(tr) == [('L', 'long', 1, 101, 103, 'S2', 'direction_filter')]


def test_direction_and_oca_constants():
    code = compile_pine('x = strategy.direction.all\ny = strategy.oca.cancel\nz = strategy.direction.short').python_code
    assert 'x = "all"' in code and 'y = "cancel"' in code and 'z = "short"' in code


# ── 9. Limit fuellt erst ab der Bar NACH der Platzierung ──
def test_limit_not_filled_in_placement_bar():
    body = '''if bar_index == 1
    strategy.order("L", strategy.long, qty=1, limit=99)
if bar_index == 3
    strategy.close_all()
'''
    # Bar1 selbst hat low 98 <= 99 (darf NICHT fuellen); Bar2 low 99 -> Fuellung 99
    rows = [FLAT, (100, 101, 98, 100), (100, 101, 99, 100), (100, 102, 99, 101)]
    tr = run(body, rows)
    assert tr[0].entry_time == T0 + timedelta(minutes=2) and tr[0].entry_price == 99


# ── 10. OCA cancel ──
def test_oca_cancel_bracket():
    body = '''if bar_index == 0
    strategy.order("BL", strategy.long, qty=1, stop=105, oca_name="br", oca_type=strategy.oca.cancel)
    strategy.order("BS", strategy.short, qty=1, stop=95, oca_name="br", oca_type=strategy.oca.cancel)
if bar_index == 3
    strategy.close_all()
'''
    rows = [FLAT, (101, 106, 100, 104), (104, 104, 90, 92), (92, 93, 91, 92)]
    tr = run(body, rows)
    # BL fuellt in Bar1 zu 105 -> BS storniert, obwohl Bar2 unter 95 faellt
    assert summary(tr) == [('BL', 'long', 1, 105, 92, 'close_all', 'close')]


def test_without_oca_both_fill():
    body = '''if bar_index == 0
    strategy.order("BL", strategy.long, qty=1, stop=105)
    strategy.order("BS", strategy.short, qty=1, stop=95)
if bar_index == 3
    strategy.close_all()
'''
    rows = [FLAT, (101, 106, 100, 104), (104, 104, 90, 92), (92, 93, 91, 92)]
    assert len(run(body, rows)) == 2


def test_oca_reduce_rejected():
    b = BrokerEmulator()
    with pytest.raises(NotImplementedError):
        b.place_order('x', 'long', 1, stop=1.0, oca_name='g', oca_type='reduce')


# ── Byte-Identitaet Altpfad ──
def test_legacy_order_codegen_and_path_unchanged():
    code = compile_pine('strategy.order("L", strategy.long, qty=1, limit=100, comment="c")').python_code
    assert 'ctx.strategy.order(id="L", direction=STRATEGY_LONG, qty=1, limit=100, comment="c")' in code
    body = 'if bar_index == 0\n    strategy.order("L", strategy.long, qty=1, limit=99)\n'
    from pine_engine.engine import RuntimeContext  # noqa: F401  (nur Import-Check)
    c = compile_pine('//@version=5\nstrategy("t")\n' + body)
    tr = run_backtest(c, bars([FLAT, (100, 101, 98, 100)]))
    assert tr == []


def test_positional_order_args():
    code = compile_pine('strategy.order("L", strategy.long, 2, 100.0, 95.0)').python_code
    assert 'ctx.strategy.order(id="L", direction=STRATEGY_LONG, qty=2, limit=100.0, stop=95.0)' in code
