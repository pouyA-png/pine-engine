# P4 — Pine-Standard: math / str / syminfo / timeframe / Zeit

Modul: `pine_engine/ext/pine_std.py` · Tests: `pine_engine/tests/test_ext_pine_std.py`

Instrument-Annahmen (fest): NQ, 1-Minuten-Bars, Tick 0,25 Punkte, Punktwert 20 $/Punkt,
Exchange-Zeitzone `America/New_York`. Zeitwerte sind Unix-Millisekunden (UTC).
Bereits vorhandene Builtins (`hour`, `minute`, `dayofweek`, `year`, `month`, `dayofmonth`,
`math.abs/min/max/round/floor/ceil/exp`, `na`, `str.tostring`) bleiben in `codegen.BUILTIN_MAP`
und werden hier nicht ueberschrieben. `math.round(x, 2)` mit Praezision kann das bereits.

## math

| Pine | Wirkung | Einheit | Beispiel |
|---|---|---|---|
| `math.sqrt(x)` | Quadratwurzel, na bei x < 0 | wie x^0,5 | `math.sqrt(16)` → 4 |
| `math.pow(b, e)` | b hoch e, na bei ungueltig | — | `math.pow(2, 10)` → 1024 |
| `math.log(x)` / `math.log10(x)` | natuerlicher / 10er-Logarithmus, na bei x ≤ 0 | — | `math.log10(1000)` → 3 |
| `math.sign(x)` | −1 / 0 / +1 | — | `math.sign(-3.5)` → −1 |
| `math.avg(a, b, ...)` | Mittelwert, na wenn ein Argument na | wie Eingabe | `math.avg(1, 2, 6)` → 3 |
| `math.sum(src, len)` | gleitende Summe der letzten `len` Bars (inkl. aktueller), na bis genug Werte da / bei na im Fenster | wie src | `math.sum(close, 3)` |
| `math.round_to_mintick(x)` | auf 0,25-Punkte-Raster, Mitte weg von 0 | NQ-Punkte | `math.round_to_mintick(100.13)` → 100.25 |
| `math.random(min, max, seed)` | gleichverteilt in [min, max), Folge je Aufrufstelle deterministisch aus `seed`; ohne seed Seed 0 (Abweichung von Pine: dort zufaellig) | — | `math.random(0, 10, 42)` |

## na-Hilfen

| Pine | Wirkung | Beispiel |
|---|---|---|
| `nz(x, repl=0)` | x, oder `repl` wenn x na | `nz(close[1])` → 0 auf Bar 0 |
| `fixnan(x)` | letzter Nicht-na-Wert von x, eigener Zustand je Aufrufstelle | `fixnan(ta.pivothigh(high, 3, 3))` |

## syminfo / timeframe (Konstanten)

| Pine | Wert |
|---|---|
| `syminfo.mintick` | 0.25 (Punkte) |
| `syminfo.pointvalue` | 20.0 ($ je Punkt und Kontrakt) |
| `syminfo.ticker` / `syminfo.tickerid` | "NQ" / "CME_MINI:NQ1!" |
| `syminfo.timezone` / `syminfo.currency` | "America/New_York" / "USD" |
| `timeframe.period` / `timeframe.multiplier` | "1" / 1 |
| `timeframe.isintraday`, `timeframe.isminutes` | true |
| `timeframe.isseconds/isdaily/isweekly/ismonthly/isdwm` | false |

## Zeit

| Pine | Wirkung | Einheit | Beispiel |
|---|---|---|---|
| `time_close` | Ende der aktuellen Bar = Oeffnung + 60 000 | UTC ms | `time_close - time` → 60000 |
| `weekofyear` / `weekofyear(t, tz)` | Kalenderwoche nach ISO 8601 (Montag-Start) in NY-Zeit | Woche | 05.01.2026 → 2 |
| `second` / `second(t, tz)` | Sekunde der Bar-Zeit | s | M1-Bars → 0 |
| `timestamp(tz, y, m, d, hh, mm[, ss])` | Zeitpunkt → ms; tz: IANA, "UTC", "GMT+2" (= UTC+2) | UTC ms | `timestamp("America/New_York", 2026, 1, 5, 9, 30)` |
| `timestamp(y, m, d, hh, mm[, ss])` | wie oben in Exchange-TZ New York | UTC ms | `timestamp(2026, 1, 5, 9, 30)` |
| `timestamp("2026-01-05T09:30:00-05:00")` | ISO-String → ms (ohne Offset: New York) | UTC ms | |
| `time(tf, session, tz)` | Bar-Oeffnungszeit (bei tf = N Minuten, 60 % N == 0: auf N-Minuten-Raster abgerundet), **na**, wenn die Bar ausserhalb der Session liegt | UTC ms | `not na(time(timeframe.period, "0930-1600:23456"))` |

Session-Regeln von `time()`:
- Format `HHMM-HHMM`, mehrere per Komma (`0930-1200,1300-1600`), optional Tagesfilter `:23456`
  (1 = So … 7 = Sa; ohne Filter alle Tage). Start inklusiv, Ende exklusiv. `0000-0000` = 24 h.
- Session-Zeit in der Exchange-TZ New York (Sommer-/Winterzeit automatisch), ausser `tz` ist angegeben.
- Uebernacht-Sessions (`1800-0930`): der Teil ab 18:00 gehoert zum **Folgetag** (Futures-Handelstag).
  `1800-0930:23456` ist also So 18:00 → Mo 09:30 drin, Fr 18:00 → Sa draussen.
- Nicht unterstuetzt (wirft `NotImplementedError`, statt still falsch zu rechnen): Timeframes
  ausser Minuten, die 60 teilen (z. B. "240", "D"), und `bars_back`.

## str

| Pine | Wirkung | Beispiel |
|---|---|---|
| `str.format(fmt, a, b, ...)` | `{0}`-Platzhalter; Zahlen per Default wie Pine/Java `#,##0.###` (Tausender-Komma, max. 3 Nachkommastellen, halbe gerade), `{0,number,#.##}` / `{0,number,0.00}` eigene Muster; bool → true/false, na → NaN | `str.format("{0} {1}", "NQ", 1.5)` → "NQ 1.5" |
| `str.contains(s, t)` / `str.startswith(s, t)` / `str.endswith(s, t)` | bool | `str.startswith("TP1 hit", "TP1")` |
| `str.length(s)` | Zeichenanzahl | `str.length("abcd")` → 4 |
| `str.upper(s)` / `str.lower(s)` | Gross-/Kleinschreibung | |
| `str.replace_all(s, alt, neu)` | alle Vorkommen ersetzen | `str.replace_all("a-b", "-", "+")` |
| `str.tonumber(s)` | Zahl oder na | `str.tonumber("abc")` → na |

## Bewusst weggelassen

`last_bar_index`, `last_bar_time`, `barstate.islast`: Diese Werte kennen das Ende des Datensatzes
schon auf der ersten Bar. Ein Skript, das damit Entscheidungen trifft, sieht im Backtest in die Zukunft
(Lookahead) und verhaelt sich live anders. Deshalb nicht registriert (Test prueft das).

## Codegen-Befunde

- Lexer/Parser liefern `syminfo.mintick`, `timeframe.period` usw. als einen Identifier mit Punkt → ext-Konstanten greifen.
- `time` steht in `BUILTIN_SERIES`, das gilt aber nur fuer Identifier/History (`time`, `time[1]`).
  Ein Aufruf `time("1", "0930-1600")` ist ein FunctionCall, faellt an `BUILTIN_MAP` vorbei in die ext-Registry → funktioniert (Test).
- `weekofyear`/`second` sind zugleich Variable (ohne Klammern) und Funktion; eine gleichnamige
  eigene Pine-Variable hat Vorrang vor der ext-Variable.
