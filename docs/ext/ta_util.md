# ta.* — Hilfsfunktionen und Oszillatoren (Paket P3)

Modul: `pine_engine/ext/ta_util.py`, Tests: `pine_engine/tests/test_ext_ta_util.py`.
Semantik nach TradingView-Doku (Pine v5). Jede Aufrufstelle hat eigene History; wie in Pine zaehlen nur
Bars, auf denen die Zeile ausgefuehrt wurde (Funktionen daher nicht nur in `if`-Zweigen aufrufen).
Fenster-Funktionen liefern `na`, bis genug Bars vorliegen; Division durch 0 ergibt `na`.

| Pine-Signatur | Was es tut | Einheit | Beispiel |
|---|---|---|---|
| `ta.barssince(condition)` | Bars seit letzter wahrer Bedingung (0 = diese Bar), `na` falls nie | Bars | `ta.barssince(close > open) == 2` |
| `ta.valuewhen(condition, source, occurrence)` | `source` an der `occurrence`-t juengsten wahren Bar (0 = juengste, inkl. aktueller) | wie source | `ta.valuewhen(up, low, 1)` |
| `ta.cum(source)` | laufende Summe ueber alle Bars (`na` zaehlt als 0) | wie source | `ta.cum(1)` = Bar-Zaehler |
| `ta.cross(source1, source2)` | true bei Kreuzung nach oben ODER unten in dieser Bar | bool | `ta.cross(close, vwapLevel)` |
| `ta.rising(source, length)` | true, wenn source > jeder der letzten `length` Vorwerte | bool | `ta.rising(close, 3)` |
| `ta.falling(source, length)` | true, wenn source < jeder der letzten `length` Vorwerte | bool | `ta.falling(low, 2)` |
| `ta.highestbars(source, length)` | Versatz (<= 0) zum Hoch der letzten `length` Bars; Gleichstand -> juengste Bar | Bars (negativ) | `ta.highestbars(high, 20)` |
| `ta.lowestbars(source, length)` | Versatz (<= 0) zum Tief; Gleichstand -> juengste Bar | Bars (negativ) | `ta.lowestbars(low, 20)` |
| `ta.range(source, length)` | Hoechster minus tiefster Wert der letzten `length` Bars | Punkte (wie source) | `ta.range(close, 30)` |
| `ta.median(source, length)` | Median der letzten `length` Werte (gerade Anzahl: Mittel der zwei mittleren) | wie source | `ta.median(close, 5)` |
| `ta.percentrank(source, length)` | Anteil der vorherigen `length` Werte <= aktuellem Wert | Prozent 0..100 | `ta.percentrank(close, 50)` |
| `ta.stoch(source, high, low, length)` | 100*(source - lowest(low)) / (highest(high) - lowest(low)) | Prozent 0..100 | `ta.stoch(close, high, low, 14)` |
| `ta.cci(source, length)` | (source - SMA) / (0.015 * mittlere absolute Abweichung) | dimensionslos | `ta.cci(hlc3, 20)` |
| `ta.linreg(source, length, offset)` | Regressionsgerade ueber `length` Bars: intercept + slope*(length-1-offset) | wie source | `ta.linreg(close, 20, 0)` |
| `ta.correlation(source1, source2, length)` | Pearson-Korrelation ueber `length` Bars (`na` bei Varianz 0) | -1..1 | `ta.correlation(close, open, 20)` |

Grenzen: History je Aufrufstelle max. 5000 Bars (bzw. length+1). `ta.median` bei gerader Laenge und
Gleichstandsregel von highestbars/lowestbars sind nach Pine-Referenzverhalten umgesetzt, aber nicht gegen
einen TradingView-Export gegengeprueft. `length < 1` wirft einen Fehler.
