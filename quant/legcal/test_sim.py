#!/usr/bin/env python3
"""Unit-Tests fuer die load-bearing Sim (gridlevels/orders_for/sim_day) — bisher 0 Tests.
Prueft Level-Mathe gegen v25_engine-Spec + Order-Konstruktion + Erst-Beruehrungs-Logik.
Lauf:  python3 -m unittest test_sim -v
"""
import unittest
from datetime import time
from pilot_analyze import gridlevels, orders_for, sim_day

def bar(t, o, h, l, c): return {"t": t, "o": o, "h": h, "l": l, "c": c}

class TestGrid(unittest.TestCase):
    def test_levels_match_v25(self):
        # v25: range = start - pivot; 0.0=pivot, 1.0=start, 0.5=pivot+0.5*range, dev -1.40/-0.78/1.78/2.54
        g = gridlevels(100.0, 90.0)   # start=100, pivot=90 -> range=10 (DOWN leg: pivot<start)
        self.assertAlmostEqual(g["l000"], 90.0)
        self.assertAlmostEqual(g["l100"], 100.0)
        self.assertAlmostEqual(g["l050"], 95.0)
        self.assertAlmostEqual(g["n140"], 90 - 1.40*10)   # 76.0
        self.assertAlmostEqual(g["n078"], 90 - 0.78*10)   # 82.2
        self.assertAlmostEqual(g["l178"], 90 + 1.78*10)   # 107.8
        self.assertAlmostEqual(g["l254"], 90 + 2.54*10)   # 115.4

class TestOrders(unittest.TestCase):
    def test_downleg_core_has_4_orders(self):
        # DOWN leg (pivot<start) an Core-Day (Di=1) -> L078,L140,S178,S254
        o, sl = orders_for(100.0, 90.0, 1)
        self.assertEqual(sl, 11.25)
        self.assertEqual(len(o), 4)
        sides = sorted(x[0] for x in o)
        self.assertEqual(sides, ["L", "L", "S", "S"])
    def test_upleg_only_shorts(self):
        # UP leg (pivot>start) -> v25: NUR Shorts
        o, sl = orders_for(90.0, 100.0, 1)
        self.assertTrue(all(x[0] == "S" for x in o))
    def test_sl_by_weekday(self):
        self.assertEqual(orders_for(100.0, 90.0, 2)[1], 12.5)   # Mi
        self.assertEqual(orders_for(100.0, 90.0, 4)[1], 11.25)  # Fr
    def test_long_sl_below_entry(self):
        o, sl = orders_for(100.0, 90.0, 1)
        for side, e, slp, tp in o:
            if side == "L": self.assertLess(slp, e)   # Long-SL unter Entry
            else: self.assertGreater(slp, e)          # Short-SL ueber Entry

class TestSim(unittest.TestCase):
    def test_long_hits_tp(self):
        # Long entry@100 sl@95 tp@110; Bar faellt auf 100 (fill), spaeter steigt auf 110 (TP)
        orders = [("L", 100.0, 95.0, 110.0)]
        post = [bar(time(9,30), 102, 103, 99, 101), bar(time(9,35), 101, 111, 100, 110)]
        r = sim_day(orders, 5.0, post)
        self.assertAlmostEqual(r, (110-100)/5.0)   # +2 R
    def test_long_hits_sl(self):
        # Fill auf Bar0 (low 99.5<=100), SL erst auf Bar1 (low 94<=95) — kein Same-Bar-Exit (Look-ahead-frei)
        orders = [("L", 100.0, 95.0, 110.0)]
        post = [bar(time(9,30), 101, 102, 99.5, 100), bar(time(9,35), 100, 101, 94, 96)]
        r = sim_day(orders, 5.0, post)
        self.assertAlmostEqual(r, -1.0)
    def test_no_exit_on_fill_bar(self):
        # Entry und SL im selben Bar -> KEIN Stop am Fill-Bar (Look-ahead vermieden); EOD-Close am letzten Bar
        orders = [("L", 100.0, 95.0, 110.0)]
        post = [bar(time(9,30), 101, 102, 94, 98)]   # low 94 trifft Entry+SL im selben Bar
        r = sim_day(orders, 5.0, post)
        self.assertAlmostEqual(r, (98-100)/5.0)      # -0.4R via EOD-Close, NICHT -1.0
    def test_no_fill_no_trade(self):
        orders = [("L", 100.0, 95.0, 110.0)]
        post = [bar(time(9,30), 105, 106, 101, 104)]   # nie auf 100 -> kein Fill
        r = sim_day(orders, 5.0, post)
        self.assertEqual(r, 0.0)
    def test_cutoff_blocks_late_fill(self):
        # Entry erst nach 10:00 beruehrt -> kein Fill (Cutoff +30min)
        orders = [("L", 100.0, 95.0, 110.0)]
        post = [bar(time(10,5), 101, 102, 99, 100)]
        r = sim_day(orders, 5.0, post)
        self.assertEqual(r, 0.0)
    def test_sidelock_blocks_opposite(self):
        # Long fuellt zuerst -> Short danach geblockt (Side-Lock)
        orders = [("L", 100.0, 95.0, 110.0), ("S", 101.0, 106.0, 96.0)]
        post = [bar(time(9,30), 100, 101.5, 99, 100)]  # beruehrt Long-Entry 100 und Short-Entry 101
        r = sim_day(orders, 5.0, post)
        # nur Long offen; EOD-close am letzten close 100 -> 0 R fuer Long; Short nie gefuellt
        self.assertEqual(r, 0.0)

if __name__ == "__main__":
    unittest.main()
