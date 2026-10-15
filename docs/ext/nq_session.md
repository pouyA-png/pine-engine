# P5 — NQ-Session + Tageslevel (`pine_engine/ext/nq_session.py`)

Zeitbasis: Bar-Zeitstempel UTC (naive = UTC) → America/New_York (zoneinfo, Sommerzeit automatisch).
Handelstag beginnt um **18:00 NY** (Sonntag 18:00 NY → Handelstag Montag). RTH = 09:30–16:00 NY,
Overnight = 18:00–09:30 NY. Alle Werte enthalten nur Bars bis einschliesslich der aktuellen Bar (kein Lookahead).
Uhrzeiten als `930`, `"0930"` oder `"09:30"` (NY-Wandzeit). Preise in Indexpunkten, na = noch nicht verfuegbar.

| Pine | Was | Einheit | Beispiel |
|---|---|---|---|
| `nq.sess_in(start, end)` | Bar-Startzeit in [start, end), Uebernacht erlaubt; auch `nq.sess_in("0930-1600")` | bool | `nq.sess_in(1800, 930)` |
| `nq.rth` / `nq.eth` | Bar liegt in 09:30–16:00 NY / ausserhalb | bool | `if nq.rth` |
| `nq.sess_minutes_since(hhmm)` | Minuten seit hhmm im laufenden Handelstag; na davor | Minuten | `nq.sess_minutes_since(930) >= 15` |
| `nq.rth_open` / `nq.rth_high` / `nq.rth_low` | Eroeffnung/Hoch/Tief der heutigen RTH bis jetzt; na vor 09:30 | Punkte | `close > nq.rth_open` |
| `nq.rth_bars_since_open` | Bars seit der ersten RTH-Bar (0 = erste); na davor | Bars | `nq.rth_bars_since_open < 30` |
| `nq.pd_high` / `nq.pd_low` / `nq.pd_close` | Hoch/Tief/Schluss des letzten abgeschlossenen RTH-Tags (wechselt um 18:00 NY) | Punkte | `low < nq.pd_low` |
| `nq.eth_high` / `nq.eth_low` | Overnight-Hoch/Tief 18:00–09:30 bis jetzt, ab 09:30 eingefroren; 16:00–18:00 zaehlt nicht | Punkte | `close > nq.eth_high` |
| `nq.or_high(min)` / `nq.or_low(min)` | Opening Range ab 09:30 ueber `min` Minuten; na bis die Range fertig ist (M1: `or_high(15)` ab der 09:44-Bar) | Punkte | `close > nq.or_high(15)` |
| `nq.sess_first_bar` | erste Bar des Handelstags | bool | `if nq.sess_first_bar` |
| `nq.sess_new_rth` | erste RTH-Bar des Handelstags | bool | `if nq.sess_new_rth` |
| `nq.sess_day_index` | fortlaufender Handelstag-Zaehler (erste Bar = 0) | Tage | `nq.sess_day_index % 2 == 0` |
| `nq.sess_weekday` | Wochentag des Handelstags, 1=Mo … 5=Fr (Sonntagabend = 1; Rest-Bars Sonntag vor 18:00 = 7) | 1–7 | `nq.sess_weekday != 5` |
| `nq.sess_is_dst` | NY-Sommerzeit aktiv | bool | `nq.sess_is_dst` |
| `nq.sess_bars_since_open` | Bars seit der ersten Bar des Handelstags (0 = erste) | Bars | `nq.sess_bars_since_open > 60` |

Beispiel Opening-Range-Breakout:
```pine
orh = nq.or_high(15)
if nq.rth and not na(orh) and close > orh
    strategy.order("L", strategy.long, qty=1, limit=close)
```

Grenzen:
- Ein gemeinsamer Tracker je Backtest haengt sich beim **ersten** nq.*-Aufruf als Broker-Hook ein und sieht ab dann jede Bar.
  Bars davor kennt er nicht → nq.*-Aufrufe unbedingt auf oberster Ebene platzieren (dann ab Bar 0).
- Die Dauer einer Bar wird als kleinster beobachteter Abstand zwischen zwei Bars angenommen (Standard 1 Minute).
- Feiertage und verkuerzte Handelstage sind nicht hinterlegt: der RTH-Tag endet dort, wo die Daten enden.
  Ein Handelstag ohne RTH-Bars laesst `nq.pd_*` unveraendert.
- Ohne nq.*-Aufruf wird nichts registriert → Backtests ohne diese Funktionen bleiben byte-identisch.
