# P10 — Auswertung + Excursion-Tracking

Dateien: `pine_engine/ext/excursion.py` (Pine), `pine_engine/reporting/metrics_ext.py` (Python/CLI).
Ohne Aufruf/Flag aendert sich weder ein Backtest noch die Default-CLI-Ausgabe.

## Pine

| Signatur | Was | Einheit | Beispiel |
|---|---|---|---|
| `nq.track_excursion()` | Registriert BrokerHook `p10_excursion`; schreibt beim (Teil-)Schliessen `extra['mfe']`, `extra['mae']` in jeden ClosedTrade. Idempotent, wirkt ab der Folgebar. Rueckgabe `true`. | Punkte je Kontrakt, beide >= 0 | `nq.track_excursion()` oben im Skript |

Konservative Zaehlung (nur Preise, die nachweislich zwischen Fuellung und Ausstieg lagen):
Fuellbar = nur Fuellpreis (Hoch/Tief ausgeschlossen, Schlusskurs zaehlt, wenn die Position die Bar ueberlebt);
volle Bars = Hoch/Tief; Ausstiegsbar = Eroeffnung + Ausstiegspreis (Hoch/Tief nur, wenn erst per
`strategy.close/close_all` zum Schlusskurs geschlossen). Vor der Registrierung offene Positionen starten beim Einstiegspreis.

## Python: `metrics_ext.summary(trades, point_value=20, initial_capital=100000, group_by_entry=False, r_edges=...)`

Kosten aus `extra['cost_usd']` werden abgezogen (Netto); R aus `extra['r0']` (Anfangsrisiko in Punkten):
R = Netto-$ / (r0 x Menge x Punktwert). Ohne r0 fallen R-Kennzahlen weg (`None`).

| Schluessel | Was | Einheit |
|---|---|---|
| `count`, `winners`, `losers` | Anzahl Trades (bzw. Positionen bei `group_by_entry=True`) | Stueck |
| `gross_usd`, `cost_usd`, `net_usd` | Brutto, Kosten, Netto | $ |
| `profit_factor`, `profit_factor_gross` | PF netto / brutto | — |
| `win_rate` | Anteil Netto > 0 | % |
| `expectancy_usd`, `expectancy_r`, `r_count` | Erwartungswert je Trade | $ / R |
| `max_drawdown_usd`, `max_drawdown_pct` | Max. Drawdown der Netto-Equity (nach Schliessungen), % vom Startkapital | $ / % |
| `max_drawdown_days` | laengste Zeit vom Hoch bis zur Erholung (offen = bis letzte Schliessung) | Kalendertage |
| `sharpe_daily`, `sortino_daily`, `trading_days` | aus Tages-Netto je NY-Kalendertag der exit_time, x sqrt(252); Sortino mit Downside-Abw. sqrt(mean(min(0,x)^2)) | — |
| `max_consec_wins`, `max_consec_losses` | laengste Gewinn-/Verlustserie | Trades |
| `by_weekday` (0=Mo), `by_hour` | NY-Zeit der entry_time: `n`, `net`, `win_rate`, `avg` | $ |
| `by_month` (`'YYYY-MM'`), `by_year` | NY-Zeit der exit_time, Netto | $ |
| `r_hist` | Buckets `<-2`, `[-2,-1)`, ..., `>=3` mit `n` | Trades |
| `avg_mfe_pts`, `avg_mae_pts` | Mittel von extra mfe/mae (falls vorhanden) | Punkte |

`group_by_entry=True`: Teilexits (TP1/TP2/Rest) mit gleicher entry_id + entry_time + Seite + Einstiegspreis = eine Position
(Menge/PnL/Kosten summiert, exit_time/exit_kind = letzte Schliessung, mfe/mae = Maximum).

Weitere: `format_summary(s)` (Textblock), `records(...)`, `r_histogram(rs, edges)`,
`export_trades(trades, pfad, point_value=20, group_by_entry=False)` — CSV je Trade mit
`pnl_points, gross_usd, net_usd, r_mult, n_parts, exit_kind, cost_usd, mfe, mae, r0` + alle weiteren extra-Schluessel (ohne `_`-Praefix).

## CLI

```
python3 -m pine_engine.main run bot.pine --data bars.csv --metrics
python3 -m pine_engine.main run bot.pine --data bars.csv --export-trades out/trades.csv --group-by-entry
```
Zusatzflags: `--point-value 20` ($/Punkt), `--capital 100000` ($, Basis fuer DD-%), `--group-by-entry`.
Ohne diese Flags ist die Ausgabe unveraendert.
