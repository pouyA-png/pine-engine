# P11 — nq.lvl_* Leg-/Level-Geometrie

Modul: `pine_engine/ext/nq_levels.py`. Reine Rechenfunktionen ohne Zustand, ohne Bar-Daten (kein Lookahead), deterministisch.
Alle Preise/Abstaende in **NQ-Punkten**. Jedes `na`-Argument ergibt `na`.

**Leg-Konvention (spec.md §6):** `price(level) = endP + level * (startP - endP)`. In allen Helfern ist
`a` = Preis bei Ratio 0,00 (Leg-Ende `endP`), `b` = Preis bei Ratio 1,00 (Leg-Start `startP`).
`nq.lvl_fib(endP, startP, -0.78)` ist also genau `lvl_n078` des Bots — fuer DOWN- und UP-Legs.

**Nudge-Richtung (spec §7/§8):** Richtung 0,50 = fruehere/leichtere Fuellung. Long-Limit +pts, Short-Limit −pts.
Fuer TP-Limits die Gegenrichtung: `nq.lvl_nudge(tp, not isLong, tpNudge)` → Long `lvl_100 − 8`, Short `lvl_000 + 8`.

| Pine-Signatur | Was | Beispiel (Punkte) |
|---|---|---|
| `nq.lvl_fib(a, b, ratio)` | Preis auf dem Leg `a + ratio·(b−a)` | Ende 20000, Start 20100, −1,40 → 19860 |
| `nq.lvl_ratio(a, b, price)` | Position im Leg `(price−a)/(b−a)`; na bei a==b | 20050 → 0,50 |
| `nq.lvl_min_target(entry, tp_geo, is_long, min_pts=150)` | Endziel mit Mindestlauf: Long `max(tp, entry+150)`, Short `min(tp, entry−150)`; entry inkl. Nudge; tp_geo na → nur Mindestlauf | Long 19927, geo 20007 → 20077 |
| `nq.lvl_half_neighbor_stop(level, neighbor_level, is_long, factor=0.5)` | Stop ab LEVEL: `factor·|level−neighbor|` hinter dem Level (Long darunter, Short darueber) | Short 20254, Nachbar 20178 → 20292 (38 pt) |
| `nq.lvl_nudge(price, is_long, pts)` | Limit Richtung fruehere Fuellung: Long +pts, Short −pts | Long 19922, 5 → 19927 |
| `nq.lvl_round_tick(price, mode="near", tick=0.25)` | Tickraster; mode `"near"` (Gleichstand hoch), `"up"`, `"down"`; Toleranz 1e-9 wie `ceil05()` | 19927.01 "up" → 19927.25; 12.23 "up" tick 0.5 → 12.5 |
| `nq.lvl_r_multiple(entry, stop, price, is_long)` | Ergebnis bis `price` in R, R = |entry−stop|, vor Kosten; na bei Risiko 0 | 7 pt Risiko, +150 pt → 21,43 R |
| `nq.lvl_qty_split(total, parts, index)` | Ganzzahl-Aufteilung, index 0-basiert, Rest auf index 0; na bei ungueltigem index | 7 auf 3 → 3/2/2; 31 auf 2 → 16/15 |
| `nq.lvl_nearest(price, step, anchor=0)` | naechstes Level `anchor + k·step` (Gleichstand hoch) | 20037, 25 → 20025 |
| `nq.lvl_leg_size(a, b)` | Leggroesse `|b−a|` | 20000/20100 → 100 |
| `nq.lvl_tp1_mid(a, b, is_outer, is_long)` | TP1 geometrisch: aeusserer Entry → 0,50; innerer → gegenueberliegender Anker (Long `max(a,b)`, Short `min(a,b)`); ohne tpNudge | DOWN-Leg Long_078 → 20100, Short_254 → 20050 |

Abweichungen von der Auftragsskizze (begruendet):
- `nq.lvl_tp1_mid` braucht zusaetzlich `is_long`: "gegenueberliegender Anker" ist ohne Richtung nicht eindeutig
  (spec §9: Long_078 → `lvl_100`, Short_178 → `lvl_000`, UP-Leg-Short → `lvl_100`).
- `nq.lvl_round_tick` hat optionales `tick` (Default 0.25), damit auch die 0,5er-Aufrundung der SL-Regel v2 abbildbar ist.
- `nq.lvl_nearest`: `anchor` optional (Default 0).
- `nq.lvl_qty_split` ist Rechenhilfe fuer Backtests; Live-Lots bleiben laut spec §10 statische Inputs.

Pine-Beispiel (Long an Level 100, Nachbar 80, Leg 100→200):
```
e  = nq.lvl_nudge(100.0, true, 2.0)                                   // 102
tp = nq.lvl_min_target(e, nq.lvl_tp1_mid(100.0, 200.0, true, true), true)   // max(150, 252) = 252
sl = nq.lvl_half_neighbor_stop(100.0, 80.0, true)                     // 90
strategy.order("L", strategy.long, qty=2, limit=e)
strategy.exit("X", from_entry="L", qty=2, limit=tp, stop=sl)
```
