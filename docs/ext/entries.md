# Entries + Ordertypen (Paket P1b)

Alle Preise in NQ-Punkten (Indexpunkte), Mengen in Kontrakten, Zeit in Bars (M1 = 1 Minute).
Das Skript laeuft am Bar-Ende; jede Order wirkt fruehestens ab der **naechsten** Bar.
Ohne die neuen Argumente/Funktionen bleibt jeder Backtest byte-identisch.

| Pine | Wirkung | Beispiel |
|---|---|---|
| `strategy.order(id, dir, qty, stop=S)` | Stop-Entry. Long fuellt bei `high >= S` zu `max(open, S)`, Short bei `low <= S` zu `min(open, S)`. | `strategy.order("BO", strategy.long, qty=1, stop=high+2)` |
| `strategy.order(id, dir, qty, stop=S, limit=L)` | Stop-Limit. Nach Trigger Limit bei L. Trigger im Bar-Innern und Triggerpreis nicht limitfaehig -> Limit erst ab Folgebar (Reihenfolge in der Bar unbekannt). | `strategy.order("SL", strategy.long, qty=1, stop=105, limit=106)` |
| `strategy.order(id, dir, qty)` | Market: fuellt zum Open der naechsten Bar. | `strategy.order("M", strategy.short, qty=2)` |
| `strategy.entry(id, dir, qty, limit, stop, oca_name, oca_type, comment)` | Wie order, plus: Gegenrichtung schliesst alle Gegenpositionen zum selben Fuellpreis und dreht (Reversal, `exit_kind='reverse'`, Exit-Kommentar = Kommentar bzw. id der neuen Order). Gleiche Richtung wird ignoriert, solange schon `max(1, pyramiding)` Entries offen sind. `limit/stop = na` = nicht gesetzt. | `strategy.entry("L", strategy.long, qty=1)` |
| `strategy(..., pyramiding=N)` | Max. N offene Entries gleicher Richtung (nur strategy.entry). Gleiche id mehrfach -> Positionen `L`, `L#2`, `L#3` ... | `strategy("x", pyramiding=2)` |
| `strategy.close(id, comment, qty=, qty_percent=)` | Schliesst zum Close der aktuellen Bar; qty/qty_percent = Teilschliessung (FIFO ueber `L`, `L#2`...; Prozent bei ganzzahliger Menge abgerundet). `exit_kind='close'`. | `strategy.close("L", qty_percent=50, comment="TP1")` |
| `strategy.close_all(comment)` | Wie bisher, zusaetzlich `ClosedTrade.extra['exit_kind']='close'`. | `strategy.close_all(comment="EOD")` |
| `strategy.order/entry(..., expire_bars=N)` | Erweiterung (nicht Pine-Standard): Order hat N Bars Chance zu fuellen, danach verfaellt sie. Erneuter Aufruf mit gleicher id setzt den Zaehler zurueck. | `strategy.order("L", strategy.long, qty=1, limit=95, expire_bars=30)` |
| `strategy.direction.long/short/all` | Konstanten `"long"`, `"short"`, `"all"`. | |
| `strategy.risk.allow_entry_in(dir)` | Richtungsfilter ab Aufruf. Gesperrte Richtung eroeffnet keine Position (strategy.entry UND - Erweiterung - strategy.order); strategy.entry in gesperrter Richtung schliesst nur die Gegenposition (`exit_kind='direction_filter'`). | `strategy.risk.allow_entry_in(strategy.direction.long)` |
| `oca_name=, oca_type=strategy.oca.cancel` | Fuellt eine Order der Gruppe, werden die anderen wartenden Orders der Gruppe storniert. `strategy.oca.reduce` -> NotImplementedError. | Bracket-Breakout mit zwei Stop-Orders |
| Limit-Fuellung | Limit-Orders fuellen erst ab der Bar NACH der Platzierung (per Test abgesichert). | |

Grenzen:
- `strategy.order(..., limit=na)` ohne stop behaelt das Altverhalten (fuellt nie), damit bestehende Backtests unveraendert bleiben. Bei strategy.entry ist `na` = Market (Pine).
- Reversal-Menge: Gegenposition komplett zu, neue Position = qty (Pine-Nettoposition).
- Pyramiding mit gleicher id: nur die erste Position heisst `L`; `strategy.exit(from_entry="L")` betrifft nur sie, die weiteren `L#2`... muessen einzeln adressiert werden (oder `from_entry=""`).
- alert_message/disable_alert/immediately werden ignoriert (ohne Wirkung im Backtest).
