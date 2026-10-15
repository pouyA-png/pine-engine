"""Tests P11 — nq.lvl_* Leg-/Level-Geometrie. Alle Zahlen in NQ-Punkten."""

from datetime import datetime, timedelta

import pytest

from pine_engine.engine import compile_pine, run_backtest
from pine_engine.runtime import ext as _ext
from pine_engine.runtime.broker import Bar
from pine_engine.runtime.na import NA, is_na

_ext.load_all()


def f(name, *args, **kw):
    return _ext.REGISTRY[name].fn(None, {}, *args, **kw)


# Beispiel-DOWN-Leg: Start 20100, Ende 20000 -> Range 100 Punkte.
END, START = 20000.0, 20100.0


# ── 1. lvl_fib ───────────────────────────────────────────────────────────

def test_fib_down_leg_matches_bot_levels():
    # Bot: price(level) = endP + level * (startP - endP)
    assert f('nq.lvl_fib', END, START, 0.0) == 20000.0
    assert f('nq.lvl_fib', END, START, 1.0) == 20100.0
    assert f('nq.lvl_fib', END, START, 0.5) == 20050.0
    assert f('nq.lvl_fib', END, START, 2.54) == pytest.approx(20254.0)
    assert f('nq.lvl_fib', END, START, -0.78) == pytest.approx(19922.0)
    assert f('nq.lvl_fib', END, START, -1.40) == pytest.approx(19860.0)


def test_fib_up_leg_negative_levels_above():
    # UP-Leg: Start 20000 (tief), Ende 20100 (hoch) -> -0,78 liegt oberhalb
    assert f('nq.lvl_fib', 20100.0, 20000.0, -0.78) == pytest.approx(20178.0)
    assert is_na(f('nq.lvl_fib', NA, START, 0.5))


# ── 2. lvl_ratio ─────────────────────────────────────────────────────────

def test_ratio_inverse_of_fib():
    assert f('nq.lvl_ratio', END, START, 20050.0) == 0.5
    assert f('nq.lvl_ratio', END, START, 19860.0) == pytest.approx(-1.40)
    assert f('nq.lvl_ratio', END, START, 20254.0) == pytest.approx(2.54)
    assert is_na(f('nq.lvl_ratio', END, END, 20050.0))  # Leg der Groesse 0


# ── 3. lvl_min_target ────────────────────────────────────────────────────

def test_min_target_long_and_short():
    # Long Entry 19927 (lvl_n078 + 5 Nudge), TP2_geo = lvl_254 - 8 = 20246
    assert f('nq.lvl_min_target', 19927.0, 20246.0, True) == 20246.0   # 319 pt > 150 -> bleibt
    # kleines Leg: TP2_geo nur 80 pt entfernt -> auf Entry + 150 verschoben
    assert f('nq.lvl_min_target', 19927.0, 20007.0, True) == 20077.0
    # Short Entry 20173, TP2_geo 20100 (73 pt) -> 20023
    assert f('nq.lvl_min_target', 20173.0, 20100.0, False) == 20023.0
    # Short, geo weiter weg (19800) -> bleibt
    assert f('nq.lvl_min_target', 20173.0, 19800.0, False) == 19800.0
    # eigener Mindestlauf 200 pt
    assert f('nq.lvl_min_target', 100.0, 250.0, True, 200.0) == 300.0
    # geo na -> reiner Mindestlauf
    assert f('nq.lvl_min_target', 100.0, NA, False) == -50.0


# ── 4. lvl_half_neighbor_stop ────────────────────────────────────────────

def test_half_neighbor_stop():
    # Long an -1,40 (19860), Nachbar -0,78 (19922): Abstand 62 -> Stop 31 pt tiefer
    assert f('nq.lvl_half_neighbor_stop', 19860.0, 19922.0, True) == 19829.0
    # Short an 2,54 (20254), Nachbar 1,78 (20178): Abstand 76 -> Stop 38 pt hoeher
    assert f('nq.lvl_half_neighbor_stop', 20254.0, 20178.0, False) == 20292.0
    # factor 0,4 -> 30,4 pt
    assert f('nq.lvl_half_neighbor_stop', 20254.0, 20178.0, False, 0.4) == pytest.approx(20284.4)
    # Seite folgt is_long, auch wenn der Nachbar auf der anderen Seite liegt
    assert f('nq.lvl_half_neighbor_stop', 100.0, 80.0, True) == 90.0


# ── 5. lvl_nudge ─────────────────────────────────────────────────────────

def test_nudge_direction_towards_earlier_fill():
    assert f('nq.lvl_nudge', 19922.0, True, 5.0) == 19927.0    # Long_078 = lvl_n078 + Nudge
    assert f('nq.lvl_nudge', 20178.0, False, 5.0) == 20173.0   # Short_178 = lvl_178 - Nudge
    # TP-Limit eines Longs (Sell-Limit): lvl_100 - tpNudge 8
    assert f('nq.lvl_nudge', 20100.0, False, 8.0) == 20092.0


# ── 6. lvl_round_tick ────────────────────────────────────────────────────

def test_round_tick_modes():
    assert f('nq.lvl_round_tick', 19927.1, 'near') == 19927.0
    assert f('nq.lvl_round_tick', 19927.13, 'near') == 19927.25
    assert f('nq.lvl_round_tick', 19927.125, 'near') == 19927.25    # Gleichstand -> hoch
    assert f('nq.lvl_round_tick', 19927.01, 'up') == 19927.25
    assert f('nq.lvl_round_tick', 19927.24, 'down') == 19927.0
    assert f('nq.lvl_round_tick', 19927.25, 'up') == 19927.25       # exakt bleibt
    # tick 0.5, "up" = ceil05 des Bots: 12.23 -> 12.5, 12.51 -> 13.0, 12.5000000001 -> 12.5
    assert f('nq.lvl_round_tick', 12.23, 'up', 0.5) == 12.5
    assert f('nq.lvl_round_tick', 12.51, 'up', 0.5) == 13.0
    assert f('nq.lvl_round_tick', 12.5000000001, 'up', 0.5) == 12.5
    with pytest.raises(ValueError):
        f('nq.lvl_round_tick', 1.0, 'sideways')


# ── 7. lvl_r_multiple ────────────────────────────────────────────────────

def test_r_multiple():
    # 7 pt Risiko, 150 pt Ziel -> 21,43 R (CLAUDE.md-Beispiel)
    assert f('nq.lvl_r_multiple', 100.0, 93.0, 250.0, True) == pytest.approx(21.4286, abs=1e-4)
    # Short: Entry 20173, Stop 20192 (19 pt), Preis 20021 -> 8 R
    assert f('nq.lvl_r_multiple', 20173.0, 20192.0, 20021.0, False) == pytest.approx(8.0)
    # Verlust = -1 R
    assert f('nq.lvl_r_multiple', 100.0, 90.0, 90.0, True) == -1.0
    assert is_na(f('nq.lvl_r_multiple', 100.0, 100.0, 110.0, True))


# ── 8. lvl_qty_split ─────────────────────────────────────────────────────

def test_qty_split():
    assert [f('nq.lvl_qty_split', 7, 3, i) for i in range(3)] == [3, 2, 2]
    assert [f('nq.lvl_qty_split', 31, 2, i) for i in range(2)] == [16, 15]
    assert [f('nq.lvl_qty_split', 46, 2, i) for i in range(2)] == [23, 23]
    assert is_na(f('nq.lvl_qty_split', 10, 2, 2))
    assert is_na(f('nq.lvl_qty_split', 10, 0, 0))


# ── 9. lvl_nearest ───────────────────────────────────────────────────────

def test_nearest():
    assert f('nq.lvl_nearest', 20037.0, 25.0) == 20025.0
    assert f('nq.lvl_nearest', 20038.0, 25.0) == 20050.0
    assert f('nq.lvl_nearest', 20037.5, 25.0) == 20050.0            # Gleichstand -> hoch
    assert f('nq.lvl_nearest', 20037.0, 25.0, 20010.0) == 20035.0   # Raster 20010 + k*25
    assert is_na(f('nq.lvl_nearest', 1.0, 0.0))


# ── 10. lvl_leg_size / lvl_tp1_mid ───────────────────────────────────────

def test_leg_size_and_tp1():
    assert f('nq.lvl_leg_size', END, START) == 100.0
    assert f('nq.lvl_leg_size', START, END) == 100.0
    # DOWN-Leg: aeussere Entries -> 0,50
    assert f('nq.lvl_tp1_mid', END, START, True, True) == 20050.0     # Long_140
    assert f('nq.lvl_tp1_mid', END, START, True, False) == 20050.0    # Short_254
    # innere Entries -> gegenueberliegender Anker
    assert f('nq.lvl_tp1_mid', END, START, False, True) == 20100.0    # Long_078 -> lvl_100
    assert f('nq.lvl_tp1_mid', END, START, False, False) == 20000.0   # Short_178 -> lvl_000
    # UP-Leg (Start 20000, Ende 20100): Short an -0,78 -> lvl_100 = 20000
    assert f('nq.lvl_tp1_mid', 20100.0, 20000.0, False, False) == 20000.0


# ── Handels-Tests ueber compile_pine/run_backtest ────────────────────────

def _bars(rows):
    t0 = datetime(2026, 1, 5, 14, 30)
    return [Bar(t0 + timedelta(minutes=i), o, h, l, c, i) for i, (o, h, l, c) in enumerate(rows)]


_TRADE_SRC = '''//@version=5
strategy("lvl")
if bar_index == 1
    lvl = nq.lvl_fib(100.0, 200.0, 0.0)
    e = nq.lvl_nudge(lvl, true, 2.0)
    tpGeo = nq.lvl_tp1_mid(100.0, 200.0, true, true)
    tp = nq.lvl_min_target(e, tpGeo, true, min_pts=150)
    sl = nq.lvl_half_neighbor_stop(lvl, 80.0, true)
    strategy.order("L", strategy.long, qty=2, limit=e)
    strategy.exit("X", from_entry="L", qty=2, limit=tp, stop=sl)
'''


def test_trade_min_target_as_tp():
    # Level 100, Entry 102 (Nudge +2), TP_geo = 0,50 = 150 (48 pt) -> Mindestlauf 102+150 = 252.
    # Stop = 100 - 0,5*|100-80| = 90.
    rows = [
        (110, 111, 109, 110),
        (110, 111, 109, 110),   # Bar 1: Orders gesetzt
        (105, 106, 101, 104),   # Bar 2: Limit 102 fuellt
        (104, 200, 103, 190),   # Bar 3: TP_geo 150 waere getroffen, 252 nicht
        (190, 260, 189, 255),   # Bar 4: 252 getroffen
    ]
    trades = run_backtest(compile_pine(_TRADE_SRC), _bars(rows))
    assert len(trades) == 1
    t = trades[0]
    assert t.side == 'long' or t.side.lower().startswith('l')
    assert t.qty == 2
    assert t.entry_price == 102.0
    assert t.exit_price == 252.0
    # 150 pt * 2 Kontrakte, R = 150 / 12 = 12,5 R
    assert (t.exit_price - t.entry_price) * t.qty == 300.0
    assert f('nq.lvl_r_multiple', 102.0, 90.0, t.exit_price, True) == pytest.approx(12.5)


def test_trade_half_neighbor_stop_hit():
    rows = [
        (110, 111, 109, 110),
        (110, 111, 109, 110),
        (105, 106, 101, 104),   # Fill 102
        (104, 105, 89, 92),     # Stop 90 getroffen
    ]
    trades = run_backtest(compile_pine(_TRADE_SRC), _bars(rows))
    assert len(trades) == 1
    assert trades[0].entry_price == 102.0
    assert trades[0].exit_price == 90.0


def test_trade_short_round_tick_and_qty_split():
    # Short-Limit: Level 200.1 -> Nudge -2 -> 198.1 -> "down" auf 198.0; qty 5 auf 2 Teile -> 3
    # TP_geo 0,00-Anker = 100 (98 pt) -> Mindestlauf 198 - 150 = 48; Stop 200.1 + 0,5*|200.1-180| = 210.15
    src = '''//@version=5
strategy("lvl2")
if bar_index == 1
    e = nq.lvl_round_tick(nq.lvl_nudge(200.1, false, 2.0), "down")
    q = nq.lvl_qty_split(5, 2, 0)
    tp = nq.lvl_min_target(e, nq.lvl_tp1_mid(100.0, 200.0, false, false), false)
    sl = nq.lvl_round_tick(nq.lvl_half_neighbor_stop(200.1, 180.0, false), "up")
    strategy.order("S", strategy.short, qty=q, limit=e)
    strategy.exit("X", from_entry="S", qty=q, limit=tp, stop=sl)
'''
    rows = [
        (190, 191, 189, 190),
        (190, 191, 189, 190),
        (195, 199, 194, 196),   # High 199 >= 198 -> Short fuellt bei 198
        (196, 197, 90, 95),     # 100 (geo) erreicht, 48 nicht
        (95, 96, 40, 45),       # 48 erreicht
    ]
    trades = run_backtest(compile_pine(src), _bars(rows))
    assert len(trades) == 1
    t = trades[0]
    assert t.qty == 3
    assert t.entry_price == 198.0
    assert t.exit_price == 48.0
