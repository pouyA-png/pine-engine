# P7 Positionsmanagement: Break-even, Trailing, Zeit-Exits (`pine_engine/ext/mgmt_stops.py`)

Ein BrokerHook (key `nq.mgmt_stops`). Jeder Aufruf setzt nur Parameter (idempotent, gleicher
Aufruf ersetzt die Werte) und wirkt ab der naechsten Bar. Ohne Aufruf: kein Hook, Backtest unveraendert.

Begriffe: **Position** = eine Entry-Id (z. B. `Long_078`). **Entry-Gruppe** = alle Exit-Specs mit
derselben `from_entry`-Id (der Bot haengt `ExL078_tp1`/`_tp2` an die eine Order `Long_078`; TP1 ist
eine Teilschliessung derselben Position, kein Praefix-Matching). **R** = |Entry − erster wirksamer Stop|
in Punkten, gemerkt beim ersten `before_exits` nach der Fuellung (`trade.extra['r0']`).
**Extrem** = bestes Hoch (long) / Tief (short) abgeschlossener Bars; in der Fuellbar nur
max/min(Entry, Close), weil deren Hoch/Tief vor der Fuellung liegen kann.
Kein Lookahead: Stops in Bar t nutzen nur Bars bis t−1. Stops werden nur verschaerft und jede Bar
erneut auf alle Specs der Position gelegt (das Skript registriert `strategy.exit` oft neu).
Gefeuerte Hook-Stops tragen `exit_kind` `be` bzw. `trail`.

| Pine | Wirkung | Einheit | Beispiel |
|---|---|---|---|
| `nq.be_after_partial(offset_points=0)` | nach einem TP-Teilexit der Position Stop des Rests auf Entry ± offset (+ = Gewinnrichtung) | Punkte | `nq.be_after_partial(2)` |
| `nq.be_at_r(trigger_r, offset_r=0)` | ab Extrem ≥ trigger·R Stop auf Entry ± offset·R | R | `nq.be_at_r(1, 0.1)` |
| `nq.be_at_points(trigger_points, offset_points=0)` | wie oben in Punkten | Punkte | `nq.be_at_points(20, 1)` |
| `nq.trail_r(start_r, dist_r)` | ab Extrem ≥ start·R Stop = Extrem ∓ dist·R (TRAIL4/1) | R | `nq.trail_r(4, 1)` |
| `nq.trail_points(start_points, dist_points)` | wie oben in Punkten | Punkte | `nq.trail_points(40, 10)` |
| `nq.trail_step(step_r=1)` | Lock-in in Stufen: Extrem ≥ k·step·R (k≥2) → Stop Entry ± (k−1)·step·R | R | `nq.trail_step(1)` |
| `nq.trail_bars(n)` | Stop = tiefstes Tief (long) / hoechstes Hoch (short) der letzten n abgeschlossenen Bars seit Fuellung (erst ab n Bars) | Bars | `nq.trail_bars(5)` |
| `nq.be_off()` / `nq.trail_off()` | schaltet alle BE- bzw. Trail-Regeln ab (bereits verschobene Stops bleiben) | – | `nq.trail_off()` |
| `nq.time_stop(minutes)` | Position ohne bisherigen TP-Teilexit nach N Minuten zum Open der ersten Bar mit Zeit ≥ Entry+N schliessen (`TIME_STOP`, exit_kind `time`) | Minuten | `nq.time_stop(90)` |
| `nq.time_max_bars(n)` | Schliessung zum Open der Bar, nachdem n Bars gehalten wurden (Fuellbar = 1), unabhaengig von TP (`TIME_MAX_BARS`, `time`) | Bars | `nq.time_max_bars(60)` |
| `nq.time_off()` | Zeit-Exits aus | – | |
| `nq.eod_flat(hhmm_ny)` | erste Bar mit NY-Zeit ≥ hhmm: Pending-Orders stornieren, Positionen zum Bar-Open schliessen (`EOD_FLAT`, exit_kind `eod`), danach bis Ende des NY-Kalendertags keine Fuellungen | HHMM New York | `nq.eod_flat(1555)` |
| `nq.eod_off()` | EOD-Flat aus | – | |

Grenzen: Specs ohne `from_entry` (gelten fuer alle Positionen) werden nicht angefasst. Hat eine
Position keine eigene Exit-Spec, legt der Hook eine Stop-only-Spec `__mgmt_<id>` an (`MGMT_STOP`).
Der Entrybar-Durchgang (PINE_ENTRYBAR_STOP) ruft keine before_exits-Hooks — dort wirken nur die Skript-Stops.
