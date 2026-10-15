# strategy_vars — strategy.*-Kennzahlen als Pine-Variablen (P1c)

Modul: `pine_engine/ext/strategy_vars.py`. Liest nur `ctx.strategy.broker`, keine Hooks. Ohne Aufruf aendert sich kein Backtest.
Geldwerte in **$** = Punkte x Menge x Punktwert (`ctx.strategy._point_value`, Standard 20 $/Punkt), **ohne Kosten**.
Jede Teilschliessung zaehlt als eigener geschlossener Trade. Zeiten in **ms** wie Pine `time`. Index ausserhalb des Bereichs -> `na`.

| Pine | Bedeutung | Einheit | Beispiel |
|---|---|---|---|
| `strategy.position_size` | Netto-Restmenge offener Trades, long +, short −, flat 0 | Kontrakte | `if strategy.position_size == 0` |
| `strategy.position_avg_price` | mengengewichteter Einstiegspreis der offenen Restmengen; flat -> na | Preis | `be = strategy.position_avg_price` |
| `strategy.openprofit` | unrealisierter PnL zum Close der aktuellen Bar | $ | `if strategy.openprofit < -400` |
| `strategy.netprofit` | Summe realisierter PnL | $ | `strategy.netprofit > 1000` |
| `strategy.grossprofit` | Summe der Gewinntrades | $ | |
| `strategy.grossloss` | Summe der Verlusttrades, positiv | $ | `pf = strategy.grossprofit / strategy.grossloss` |
| `strategy.wintrades` / `.losstrades` / `.eventrades` | Anzahl Gewinn / Verlust / PnL = 0 | Stueck | `wr = strategy.wintrades / strategy.closedtrades` |
| `strategy.max_drawdown` | groesster Rueckgang der **realisierten** Equity vom Hoch (Start 0) | $, positiv | `if strategy.max_drawdown > 2000` |
| `strategy.max_runup` | groesster Anstieg der realisierten Equity vom Tief | $, positiv | |
| `strategy.initial_capital` | Startkapital der StrategyAPI (Standard 100000; `strategy(initial_capital=)` wird von der Engine nicht uebernommen) | $ | |
| `strategy.opentrades.size(i)` | Restmenge offener Trade i, short negativ | Kontrakte | `strategy.opentrades.size(0)` |
| `strategy.opentrades.entry_time(i)` | Fuellzeit | ms | |
| `strategy.opentrades.entry_bar_index(i)` | bar_index der Fuellbar, aus entry_time abgeleitet | Bar | `bar_index - strategy.opentrades.entry_bar_index(0) > 30` |
| `strategy.closedtrades.entry_price(k)` / `.exit_price(k)` | Ein-/Ausstiegspreis | Preis | `strategy.closedtrades.exit_price(strategy.closedtrades - 1)` |
| `strategy.closedtrades.entry_time(k)` / `.exit_time(k)` | Ein-/Ausstiegszeit | ms | |
| `strategy.closedtrades.max_runup(k)` / `.max_drawdown(k)` | `extra['mfe']` bzw. `extra['mae']` (Punkte) x qty x Punktwert; ohne MFE/MAE-Plugin `na` | $ | |
| `strategy.closedtrades.first_index` | Index des aeltesten geschlossenen Trades (immer 0) | Index | |
| `nq.day_netprofit` | realisierter PnL des heutigen Handelstags = New-York-Kalendertag der exit_time (naive Zeitstempel = UTC) | $ | `if nq.day_netprofit > -1000` (Tagesverlust-Sperre) |

Grenzen:
- `max_drawdown`/`max_runup` nur realisiert (TradingView rechnet mit offener Equity) -> Werte koennen kleiner sein als in TV.
- `position_avg_price` mittelt ueber alle offenen Trades; bei gleichzeitig long+short (in dieser Engine moeglich) ist der Wert wenig sinnvoll.
- `entry_bar_index`: Suche in `ctx.time` (letzte 300 Bars), danach in einer eigenen Tabelle (nur Bars, in denen ein Name dieses Moduls ausgewertet wurde), sonst `na`.
- `extra['mfe'/'mae']` wird derzeit von keinem Modul gesetzt; Einheit Punkte ist Annahme.
- Unveraendert (codegen, nicht hier): `strategy.closedtrades.profit(k)` liefert **Punkte x Menge**, nicht $.
