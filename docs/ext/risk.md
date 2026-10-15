# nq.risk_* — Risiko- und Kontoregeln (FTMO), Paket P8

Modul: `pine_engine/ext/risk.py`, Tests: `pine_engine/tests/test_ext_risk.py`.

Alle Regeln sitzen in einem Broker-Hook (`key = "nq.risk"`). Aktiviert wird er erst
durch einen Pine-Aufruf; ohne Aufruf bleibt jeder Backtest byte-identisch. Die Aufrufe
sind idempotent und duerfen jede Bar laufen (der letzte Wert gilt). Mit `na` oder `0`
wird eine Regel abgeschaltet.

**Geld:** $ = Punkte × qty × Punktwert (`strategy._point_value`, NQ = 20 $/Punkt).
Realisierte Trades zaehlen netto, also abzueglich `ClosedTrade.extra['cost_usd']`,
falls der Kosten-Hook das Feld setzt.

**Handelstag:** Standard `Europe/Prague`, Wechsel um 00:00 Ortszeit. So rechnet FTMO den
Tagesverlust (Mitternacht CET/CEST). Den CME-Handelstag (Wechsel 18:00 New York) stellst
du mit `nq.risk_timezone("America/New_York")` ein. Naive Bar-Zeitstempel gelten als UTC.

**Zeitablauf, kein Lookahead:** Eine Regel wird am Anfang von Bar t geprueft. Dafuer zaehlen
nur Trades, die bis zum Ende von Bar t-1 geschlossen wurden, und offene Positionen werden
zum Close von Bar t-1 bewertet. Eine Sperre wirkt also ab der Bar nach dem ausloesenden
Ereignis. Eine Zwangsschliessung fuellt zum Open von Bar t. Solange ein Tag oder das Konto
gesperrt ist, werden wartende Limit-Orders jede Bar storniert, also auch Orders, die das
Skript neu setzt.

| Pine-Signatur | Wirkung | Einheit | Beispiel |
|---|---|---|---|
| `nq.risk_daily_loss(usd)` | Wenn der realisierte Tages-PnL ≤ −usd ist, gibt es fuer den Rest des Tages keine neuen Entries, und Pending-Orders werden storniert. Offene Positionen laufen weiter. | $ | `nq.risk_daily_loss(1000)` |
| `nq.risk_daily_loss_hard(usd)` | Wenn realisiert + offen (zum Close der Vorbar) ≤ −usd ist, gilt die Tagessperre, und alle offenen Positionen werden zum naechsten Open geschlossen (Exit-Kommentar `RISK_DAILY_HARD`). | $ | `nq.risk_daily_loss_hard(2500)` |
| `nq.risk_daily_target(usd)` | Wenn der realisierte Tages-PnL ≥ usd ist, gibt es fuer den Rest des Tages keine neuen Entries. | $ | `nq.risk_daily_target(1500)` |
| `nq.risk_max_trades_day(n)` | Hoechstens n gefuellte Entries pro Handelstag. Danach gilt die Tagessperre. | Anzahl | `nq.risk_max_trades_day(3)` |
| `nq.risk_max_losses_row(n)` | Nach n Verlust-Positionen in Folge am selben Tag gilt die Tagessperre. Ein Gewinn oder ±0 setzt die Serie zurueck, ebenso ein neuer Tag. | Anzahl | `nq.risk_max_losses_row(2)` |
| `nq.risk_cooldown(minutes)` | Nach einer Verlust-Position sind bis zur Exit-Zeit + minutes keine Entries erlaubt. Pending-Orders bleiben liegen. | Minuten | `nq.risk_cooldown(30)` |
| `nq.risk_max_open(n)` | Hoechstens n gleichzeitig offene Positionen. Weitere Orders fuellen nicht, bleiben aber liegen. | Anzahl | `nq.risk_max_open(1)` |
| `nq.risk_total_loss(usd)` | FTMO-Maximalverlust: Wenn realisiert gesamt + offen ≤ −usd ist, wird der Handel dauerhaft abgeschaltet und offene Positionen werden zum naechsten Open geschlossen (`RISK_TOTAL`). | $ | `nq.risk_total_loss(10000)` |
| `nq.risk_timezone(tz, rollover_hour)` | Legt den Handelstag fest: Zeitzone plus Stunde des Tageswechsels in Ortszeit. Ohne Stunde gilt 18 fuer `America/New_York`, sonst 0. | Zone, Stunde | `nq.risk_timezone("America/New_York")` |
| `nq.risk_qty(risk_usd, entry, stop)` | Reine Rechenfunktion: floor(risk_usd / (\|entry−stop\| × Punktwert)), mindestens 0. Liefert `na`, wenn ein Eingang na ist. | Kontrakte | `q = nq.risk_qty(500, lim, sl)` → 500/(5×20) = 5 |
| `nq.risk_blocked` | Variable: `true`, wenn heute (oder dauerhaft) gesperrt ist. Stand ist das Ende der aktuellen Bar, Wirkung ab der naechsten Bar. | bool | `if not nq.risk_blocked` |
| `nq.risk_day_pnl` | Variable: realisierter Tages-PnL (netto Kosten) + offener PnL zum aktuellen Close. | $ | `plot(nq.risk_day_pnl)` |

## Grenzen

- Eine Position zaehlt fuer Verlustserie und Cooldown erst, wenn sie komplett geschlossen ist.
  Massgeblich ist die Summe aller Teilausstiege (TP1 + Rest).
- `daily_loss` und `daily_target` pruefen nur realisierte Trades. Nur `daily_loss_hard` und
  `total_loss` beziehen offene Positionen ein, wie FTMO es mit dem Equity-Stand tut.
  Eine Unterschreitung innerhalb einer Bar (Tief statt Close) wird nicht erkannt.
- Beim Tageswechsel ist die Basis der Kontostand zu Tagesbeginn (realisiert). Der offene PnL
  einer ueber Nacht gehaltenen Position zaehlt dabei komplett zum neuen Tag.
- `cost_usd` wird nur beruecksichtigt, wenn es beim naechsten Bar-Start im `extra` steht.
  Das trifft zu, wenn der Kosten-Hook es in `on_close` setzt.
