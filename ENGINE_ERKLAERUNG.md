# Pine Engine — Erklärung (Stand 2026-10-15)

Diese Engine führt **TradingView-Pine-Script-v5-Strategien lokal in Python aus** — ohne
TradingView, auf beliebigen Minuten-CSV-Daten, beliebig oft und skriptbar. Gedacht für
Backtests, Parameter-Sweeps und Forschung an NQ/US100-Intraday-Strategien.

Stand dieser Fassung: 308 automatische Tests grün, rund 150 Zusatzfunktionen seit
2026-09-29 (Erweiterungs-Registry). Ohne Aufruf einer Zusatzfunktion liefert jeder
Backtest exakt dasselbe Ergebnis wie die Fassung davor.

---

## 1. Wie die Engine arbeitet

```
.pine-Datei
   │  lexer.py      zerlegt den Text in Tokens (inkl. Einrückung wie Python)
   ▼
   │  parser.py     baut daraus einen Syntaxbaum (ast_nodes.py)
   ▼
   │  codegen.py    übersetzt den Baum in Python-Code
   ▼
   │  engine.py     lädt Bars (data/loader.py) und ruft den Code einmal je Bar auf
   ▼
   │  runtime/      Series mit History ([1], [2] …), na-Logik, ta.*-Builtins,
   │                strategy.* (strategy.py) und der Broker-Emulator (broker.py),
   │                der Orders gegen Open/High/Low/Close jeder Bar füllt
   ▼
reporting/          Trade-Liste, Kennzahlen (PF, Netto, Drawdown, Trefferquote …)
```

- **Eine Bar = ein Durchlauf** des Skripts, genau wie in TradingView.
- Der Broker füllt Limit-/Stop-Orders gegen Open/High/Low/Close der Bar. Sind Stop und Ziel
  in derselben Bar erreichbar, entscheidet eine Heuristik nach Bar-Richtung wie in TradingView
  (Standard `PINE_INTRABAR=tv`). Zum Eingrenzen: `PINE_INTRABAR=worst` (immer Stop zuerst) bzw.
  `best` (immer Ziel). Das ist die Hauptquelle für Abweichungen gegenüber TV (gemessene Parität
  ca. 2 % auf den geprüften Bots). Exits in der Einstiegs-Bar: Standard aus wie in TV,
  umschaltbar mit `PINE_ENTRYBAR_STOP=on|gap`.
- Zeiten: intern UTC, Session-Logik in New-York-Zeit (Sommerzeit wird berücksichtigt).

## 2. Installation und erster Lauf

```bash
git clone https://github.com/pouyA-png/pine-engine.git && cd pine-engine
python3 -m pip install -e .            # Python >= 3.10, braucht pandas + numpy
python3 -m pytest -q pine_engine/tests # erwartet: 308 passed

python3 -m pine_engine.main run meine_strategie.pine --data bars.csv
```

Datenformat (`--data`): CSV mit Kopfzeile `datetime,open,high,low,close,volume`, eine Zeile
je Minute, z. B. `2026-03-06 01:57:00+00:00,25046.95,25049.85,25042.45,25044.15,322`.
Die Zeitspalte darf auch `date`, `time` oder `timestamp` heißen; Groß-/Kleinschreibung egal.

## 3. Kommandozeile

| Befehl | Zweck |
|---|---|
| `run <pine> --data <csv>` | Backtest ausführen |
| `--start 2025-01-01 --end 2025-12-31` | Zeitraum einschränken |
| `--param name=wert` (mehrfach) | `input.*`-Werte überschreiben, z. B. `--param i_useTilt=false` |
| `--metrics` | erweiterte Kennzahlen (Brutto/Netto-PF, Drawdown in $ und %, Serien, Tageswerte) |
| `--export-trades trades.csv` | jede Ausführung als CSV, inkl. Exit-Art und MFE/MAE |
| `--group-by-entry` | Teilexits (TP1/TP2) zu einer Position zusammenfassen |
| `--point-value 20 --capital 100000` | $ je Punkt und Startkapital für `--metrics` |
| `info <pine>` | Inputs und Strategie-Einstellungen anzeigen |
| `compile <pine>` | erzeugten Python-Code ausgeben (Fehlersuche) |

Parameter-Sweeps: `pine_engine/batch/param_grid.py` + `runner.py` (siehe README, Abschnitt
„Parameter sweeps“).

## 4. Was an Pine unterstützt wird

Kern: `strategy()`, `input.*`, `var`/`varip`, `if`/`for`/`while`, eigene Funktionen,
History-Zugriff `x[n]`, `na`/`nz`, `strategy.entry/order/exit/close/close_all/
cancel/cancel_all`, `request.security` (nur höhere Zeitebenen aus M1, ohne Lookahead).
Nicht unterstützt: Zeichnungen (`plot`, `line`, `label`, `box` werden ignoriert), Libraries
(`import`), eigene Typen/Methoden, Tick-genaue Intrabar-Simulation, `request.security` auf
fremde Symbole. Vollständige Tabelle: README, Abschnitt „What Pine v5 subset is supported“.

## 5. Die Erweiterungen (seit 2026-09-29)

Alle Zusatzfunktionen werden direkt im Pine-Code aufgerufen. Vollständiger Katalog mit
Parametern: [`docs/ext/README.md`](docs/ext/README.md).

| Bereich | Beispiele | Doku |
|---|---|---|
| Orders/Exits | Stop-/Stop-Limit-Entries, `pyramiding`, Reversal, `trail_points/offset`, `qty_percent`, `expire_bars` | `entries.md`, `exits.md` |
| Kosten/Füllung | `nq.cost_points(2)`, `nq.fill_slippage(0.25, 0.5)`, `nq.fill_trade_through()` | `costs.md` |
| Management | `nq.be_at_r(1)`, `nq.trail_r(4, 1)`, `nq.time_stop()`, `nq.eod_flat(1555)` | `mgmt_stops.md` |
| Risiko/Prop-Firm | `nq.risk_daily_loss(2000)`, `nq.risk_max_trades_day(3)`, `nq.risk_qty()` | `risk.md` |
| Höhere Zeitebenen | `nq.htf_close("15")`, `nq.htf_day_high()`, `request.security(...)` | `nq_htf.md` |
| Session/Tageslevel | `nq.rth`, `nq.or_high(15)`, `nq.pd_high`, `nq.sess_minutes_since(930)` | `nq_session.md` |
| Leg-/Level-Geometrie | `nq.lvl_fib()`, `nq.lvl_nudge()`, `nq.lvl_min_target(e, tp, long, 150)`, `nq.lvl_r_multiple()` | `nq_levels.md` |
| Indikatoren | `ta.ema/sma/rma/hma/atr/stdev/cci/stoch/linreg/valuewhen/barssince …` | `ta_ma.md`, `ta_util.md` |
| Kennzahlen | `strategy.netprofit`, `strategy.closedtrades.*`, MFE/MAE `nq.track_excursion()` | `strategy_vars.md`, `metrics.md` |

Lauffähiges Beispiel mit vielen Bausteinen: [`docs/ext/beispiel_kombi.pine`](docs/ext/beispiel_kombi.pine)
(Opening-Range-Ausbruch mit EMA-Filter, Kosten, Tagesverlustgrenze, Trailing). Es ist ein
Funktionstest, **keine profitable Strategie** (auf FTMO US100 M1 März–Juni 2026:
150 Trades, PF 0,55).

## 6. Eigene Funktionen ergänzen

Neue Builtins als eigenes Modul in `pine_engine/ext/` anlegen und per Dekorator registrieren —
`codegen.py` und `broker.py` bleiben unangetastet:

```python
from pine_engine.runtime.ext import builtin, cur

@builtin('nq.mein_wert', series_args=(0,))
def mein_wert(ctx, state, source, length):
    ...   # state = eigener Zustand je Aufrufstelle im Pine-Code
```

Eingriffe in die Ausführung (z. B. eigene Füllregeln) laufen über `BrokerHook`
in `runtime/broker.py` (`ctx.strategy.broker.add_hook(obj)`). Zu jedem Modul gehört ein
Test `pine_engine/tests/test_ext_<name>.py`.

## 7. Grenzen, die man kennen muss

- **Kein Ersatz für einen Forward-Test.** Ein guter Backtest beweist keinen künftigen Ertrag.
- Intrabar-Reihenfolge ist eine Annahme (siehe Abschnitt 1). Strategien mit engem Stop und
  Ziel in derselben Minute können sich gegenüber TV und Live deutlich unterscheiden.
- Die Erweiterungen sind mit eigenen Tests geprüft, aber nicht flächig gegen TradingView
  abgeglichen.
- Ergebnisse immer mit Datenquelle (Feed), Zeitraum, Positionsgröße und Einheit
  (Punkte, R, $) angeben.
