"""Tests P1a — Exit-Kern + Bugfixes (strategy.exit / strategy.cancel / Entrybar-Durchgang).

Jeder Handels-Test laeuft ueber compile_pine/run_backtest mit synthetischen M1-Bars;
die erwarteten Exitpreise sind im Kommentar nachgerechnet.
Reihenfolge je Bar: process_entries -> process_exits -> Skript -> Entrybar-Durchgang.
"""
from datetime import datetime, timedelta

import pytest

from pine_engine.engine import compile_pine, run_backtest
from pine_engine.runtime.broker import Bar
from pine_engine.runtime.strategy import StrategyAPI

T0 = datetime(2026, 1, 5, 14, 30)


def bars_of(rows):
    return [Bar(T0 + timedelta(minutes=i), o, h, l, c, i)
            for i, (o, h, l, c) in enumerate(rows)]


def run(src, rows):
    return run_backtest(compile_pine(src), bars_of(rows))


# Bar0 fuellt nicht (Tief 100.5 > Limit 100); Bar1 fuellt Long @100 (Open 100).
PRE = [(101, 101.5, 100.5, 101), (100, 101, 99.5, 100.5)]


# ── 2. Stop ohne Ziel / Ziel ohne Stop ──

@pytest.mark.parametrize("limit_arg", ["", ", limit=0", ", limit=na"])
def test_stop_only_exit_hits_stop_not_phantom_tp(limit_arg):
    src = f'''//@version=5
strategy("t")
if bar_index == 0
    strategy.order("L", strategy.long, qty=1, limit=100)
    strategy.exit("X", from_entry="L", qty=1, stop=90{limit_arg})
'''
    # Bar2 faellt bis 89 -> Stop 90 (Open 95 > 90 -> Fuellung genau 90).
    trades = run(src, PRE + [(95, 96, 89, 90)])
    assert len(trades) == 1
    t = trades[0]
    assert t.entry_price == 100 and t.exit_price == 90
    assert t.extra['exit_kind'] == 'sl'
    assert t.exit_time == T0 + timedelta(minutes=2)


def test_limit_only_short_has_no_phantom_stop():
    src = '''//@version=5
strategy("t")
if bar_index == 0
    strategy.order("S", strategy.short, qty=1, limit=100)
    strategy.exit("X", from_entry="S", qty=1, limit=95)
'''
    # Short fuellt in Bar1 @100 (Hoch 100.5 >= 100, Open 99 < 100 -> Limit 100).
    rows = [(99, 99.5, 98.5, 99), (99, 100.5, 98.8, 100),
            (100, 101, 97, 98), (98, 98.5, 94, 95)]
    trades = run(src, rows)
    assert len(trades) == 1
    assert trades[0].entry_price == 100 and trades[0].exit_price == 95
    assert trades[0].extra['exit_kind'] == 'tp'


# ── 1. Entrybar-Doppelpruefung ──

ENTRYBAR_SRC = '''//@version=5
strategy("t")
if bar_index == 0
    strategy.order("L", strategy.long, qty=2, limit=100)
    strategy.exit("TP1", from_entry="L", qty=1, limit=105, stop=95)
    strategy.exit("X2", from_entry="L", qty=1, limit=120, stop=95)
if strategy.closedtrades == 1 and strategy.opentrades > 0
    strategy.exit("X2", from_entry="L", qty=1, limit=120, stop=100)
'''
# Bar1: Einstieg 100 zum Open, Hoch 106, Tief 98. TP1 105 fuellt im 1. Durchgang,
# das Skript zieht X2 auf 100 -> darf in DIESER Bar nicht ausstoppen (Tief 98 lag
# nicht nachweislich nach dem Nachziehen). Bar3 (Tief 99) stoppt X2 bei 100.
ENTRYBAR_ROWS = [(101, 101.5, 100.5, 101), (100, 106, 98, 104),
                 (104, 105, 101, 103), (101, 102, 99, 100)]


@pytest.mark.parametrize("mode", ["on", "gap"])
def test_entrybar_second_pass_skips_exits_checked_in_first_pass(monkeypatch, mode):
    monkeypatch.setenv("PINE_ENTRYBAR_STOP", mode)
    trades = run(ENTRYBAR_SRC, ENTRYBAR_ROWS)
    assert [(t.exit_price, t.exit_time.minute - 30) for t in trades] == [(105, 1), (100, 3)]
    assert [t.extra['exit_kind'] for t in trades] == ['tp', 'sl']


def test_entrybar_second_pass_still_checks_exit_created_in_fill_bar(monkeypatch):
    """Exit, der erst NACH der Fuellung im Skript entsteht, wird weiter geprueft."""
    monkeypatch.setenv("PINE_ENTRYBAR_STOP", "on")
    src = '''//@version=5
strategy("t")
if bar_index == 0
    strategy.order("L", strategy.long, qty=1, limit=100)
if strategy.opentrades > 0
    strategy.exit("X", from_entry="L", qty=1, stop=99)
'''
    # Bar1 fuellt @100, Tief 98.5 -> 2. Durchgang stoppt bei 99 in Bar1.
    trades = run(src, [(101, 101.5, 100.5, 101), (100, 101, 98.5, 100)])
    assert len(trades) == 1 and trades[0].exit_price == 99
    assert trades[0].exit_time == T0 + timedelta(minutes=1)


# ── 3. profit=/loss= in Ticks ──

def test_profit_loss_ticks_relative_to_entry():
    src = '''//@version=5
strategy("t")
if bar_index == 0
    strategy.order("A", strategy.long, qty=1, limit=100)
    strategy.exit("XA", from_entry="A", profit=40, loss=20)
'''
    # 40 Ticks * 0.25 = 10 Punkte -> TP 110; 20 Ticks = 5 Punkte -> SL 95.
    win = run(src, PRE + [(101, 111, 100.5, 110)])
    assert [(t.exit_price, t.extra['exit_kind']) for t in win] == [(110, 'tp')]
    loss = run(src, PRE + [(99, 99.5, 94, 95)])
    assert [(t.exit_price, t.extra['exit_kind']) for t in loss] == [(95, 'sl')]


def test_profit_ticks_with_custom_mintick():
    api = StrategyAPI(mintick=1.0)
    api.order("A", "long", qty=1, limit=100)
    api.process_bar(bars_of(PRE)[1])           # fuellt @100
    api.exit("XA", from_entry="A", profit=10)  # 10 Ticks * 1.0 = 10 Punkte
    b = Bar(T0 + timedelta(minutes=2), 101, 111, 100.5, 110, 2)
    api.process_bar(b)
    assert api.get_results()[0].exit_price == 110


# ── 4. Trailing ──

@pytest.mark.parametrize("act", ["trail_points=20", "trail_price=105"])
def test_trailing_stop_no_lookahead(act):
    src = f'''//@version=5
strategy("t")
if bar_index == 0
    strategy.order("L", strategy.long, qty=1, limit=100)
    strategy.exit("T", from_entry="L", {act}, trail_offset=8, comment_trailing="TRL")
'''
    # Aktivierung 100 + 20*0.25 = 105; Offset 8*0.25 = 2 Punkte.
    # Bar2 Hoch 106 -> aktiv, Extrem 106 (gilt ab Bar3): Stop 104, Bar3 Tief 104.5 -> kein Exit.
    # Bar3 Hoch 108 -> Stop ab Bar4 = 106; Bar4 Tief 105 -> Exit 106 (Open 107 > 106).
    # Mit Lookahead haette Bar3 bereits bei 106 gestoppt.
    rows = PRE + [(102, 106, 101, 105), (105, 108, 104.5, 107), (107, 107.5, 105, 105.5)]
    trades = run(src, rows)
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_price == 106 and t.exit_time == T0 + timedelta(minutes=4)
    assert t.extra['exit_kind'] == 'trail' and t.exit_comment == 'TRL'


def test_trailing_short_with_fixed_stop_tighter_wins():
    src = '''//@version=5
strategy("t")
if bar_index == 0
    strategy.order("S", strategy.short, qty=1, limit=100)
    strategy.exit("T", from_entry="S", stop=103, trail_points=8, trail_offset=40, comment_loss="SL")
'''
    # Short @100 (Bar1). Aktivierung 98; Offset 10 Punkte -> Trail-Stop waere lockerer als 103.
    rows = [(99, 99.5, 98.5, 99), (99, 100.5, 98.8, 100),
            (99, 99.5, 97, 98), (98, 103.5, 97.5, 103)]
    trades = run(src, rows)
    assert [(t.exit_price, t.extra['exit_kind'], t.exit_comment) for t in trades] == [(103, 'sl', 'SL')]


# ── 5. qty_percent ──

def test_qty_percent_partial_exits():
    src = '''//@version=5
strategy("t")
if bar_index == 0
    strategy.order("L", strategy.long, qty=4, limit=100)
    strategy.exit("TP1", from_entry="L", qty_percent=50, limit=105)
    strategy.exit("TP2", from_entry="L", qty_percent=100, limit=110)
'''
    trades = run(src, PRE + [(101, 105.5, 100.5, 105), (105, 111, 104, 110)])
    assert [(t.qty, t.exit_price) for t in trades] == [(2, 105), (2, 110)]


# ── 6. comment / comment_trailing ──

def test_comment_fallback_and_specific_override():
    src = '''//@version=5
strategy("t")
if bar_index == 0
    strategy.order("L", strategy.long, qty=2, limit=100)
    strategy.exit("A", from_entry="L", qty=1, limit=105, stop=95, comment="ALL", comment_profit="WIN")
    strategy.exit("B", from_entry="L", qty=1, limit=120, stop=95, comment="ALL")
'''
    trades = run(src, PRE + [(101, 105.5, 100.5, 105), (104, 104.5, 94, 95)])
    assert [(t.exit_comment, t.exit_price) for t in trades] == [("WIN", 105), ("ALL", 95)]


# ── 7. strategy.cancel storniert Exit-Orders ──

def test_cancel_removes_exit_order():
    src = '''//@version=5
strategy("t")
if bar_index == 0
    strategy.order("L", strategy.long, qty=1, limit=100)
    strategy.exit("X", from_entry="L", qty=1, stop=95)
if bar_index == 1
    strategy.cancel("X")
'''
    trades = run(src, PRE + [(99, 99.5, 90, 91)])
    assert trades == []


def test_cancel_by_kwarg_id():
    src = '''//@version=5
strategy("t")
if bar_index == 0
    strategy.order("L", strategy.long, qty=1, limit=90)
if bar_index == 0
    strategy.cancel(id="L")
'''
    assert run(src, PRE + [(95, 96, 80, 85)]) == []


# ── 8. strategy.exit ohne from_entry ──

def test_exit_without_from_entry_applies_to_all_positions():
    src = '''//@version=5
strategy("t")
if bar_index == 0
    strategy.order("A", strategy.long, qty=1, limit=100)
    strategy.order("B", strategy.long, qty=2, limit=100)
if bar_index == 1
    strategy.exit("ALL", stop=95, comment_loss="SL")
'''
    trades = run(src, PRE + [(99, 99.5, 94, 95), (95, 96, 80, 85)])
    assert sorted((t.entry_id, t.qty, t.exit_price) for t in trades) == [("A", 1, 95), ("B", 2, 95)]
    assert all(t.extra['exit_kind'] == 'sl' for t in trades)


def test_exit_with_from_entry_only_touches_that_entry():
    src = '''//@version=5
strategy("t")
if bar_index == 0
    strategy.order("A", strategy.long, qty=1, limit=100)
    strategy.order("B", strategy.long, qty=1, limit=100)
if bar_index == 1
    strategy.exit("XA", from_entry="A", qty=1, stop=95)
'''
    trades = run(src, PRE + [(99, 99.5, 94, 95)])
    assert [(t.entry_id, t.exit_price) for t in trades] == [("A", 95)]


# ── 10. PINE_INTRABAR mit Stop-only/Limit-only ──

@pytest.mark.parametrize("mode", ["tv", "worst", "best"])
def test_intrabar_modes_consistent_with_single_sided_exits(monkeypatch, mode):
    monkeypatch.setenv("PINE_INTRABAR", mode)
    wide = PRE + [(100, 112, 88, 101)]   # erreicht beide Seiten
    stop_only = '''//@version=5
strategy("t")
if bar_index == 0
    strategy.order("L", strategy.long, qty=1, limit=100)
    strategy.exit("X", from_entry="L", qty=1, stop=90)
'''
    limit_only = stop_only.replace("stop=90", "limit=110")
    both = stop_only.replace("stop=90", "limit=110, stop=90")
    assert [(t.exit_price, t.extra['exit_kind']) for t in run(stop_only, wide)] == [(90, 'sl')]
    assert [(t.exit_price, t.extra['exit_kind']) for t in run(limit_only, wide)] == [(110, 'tp')]
    # Beide Seiten: bullische Bar -> tv=TP, worst=SL, best=TP.
    exp = {"tv": (110, 'tp'), "worst": (90, 'sl'), "best": (110, 'tp')}[mode]
    assert [(t.exit_price, t.extra['exit_kind']) for t in run(both, wide)] == [exp]


# ── Codegen: Positionsargumente von strategy.exit ──

def test_codegen_exit_positional_args():
    code = compile_pine('''//@version=5
strategy("t")
strategy.exit("X", "L", 1, 50, 40)
''').python_code
    assert 'id="X"' in code or "id='X'" in code
    assert 'from_entry=' in code and 'qty=1' in code
    assert 'qty_percent=50' in code and 'profit=40' in code


def test_default_exit_spec_unchanged():
    """Ohne neue Parameter bleibt die Exit-Spec byte-identisch (Plugin-Vertrag)."""
    api = StrategyAPI()
    api.exit("X", from_entry="L", qty=1, limit=105, stop=95,
             comment_profit="P", comment_loss="L")
    assert api.broker.exit_orders["X"] == {
        "from_entry": "L", "qty": 1, "limit": 105, "stop": 95,
        "comment_profit": "P", "comment_loss": "L"}
