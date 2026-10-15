# ta.* — Durchschnitte und Volatilitaet (Paket P2)

Modul: `pine_engine/ext/ta_ma.py`, Tests: `pine_engine/tests/test_ext_ta_ma.py`.
Jede Aufrufstelle hat einen eigenen Zustand mit eigener History (unabhaengig von der
300-Bar-Grenze der Quell-Series). Quelle darf eine Series (`close`) oder ein Ausdruck
(`high - low`) sein. Einheit der Ergebnisse = Einheit der Quelle (NQ-Punkte), ausser `ta.roc` (Prozent).

| Pine-Signatur | Was es tut | Einheit | Beispiel |
|---|---|---|---|
| `ta.sma(src, len)` | Einfacher Durchschnitt der letzten `len` Werte; na bis `len` Werte da sind | wie src | `ta.sma(close, 20)` |
| `ta.ema(src, len)` | EMA, alpha = 2/(len+1); na fuer die ersten len-1 Bars, erster Wert = SMA der ersten len Werte | wie src | `ta.ema(high - low, 3)` |
| `ta.rma(src, len)` | Wilder-Glaettung, alpha = 1/len, gleicher SMA-Seed | wie src | `ta.rma(close, 14)` |
| `ta.wma(src, len)` | Linear gewichtet, neuester Wert Gewicht len, aeltester 1 | wie src | `ta.wma(close, 9)` |
| `ta.hma(src, len)` | Hull MA = wma(2*wma(src, len//2) - wma(src, len), floor(sqrt(len))) | wie src | `ta.hma(close, 16)` |
| `ta.tr` | True Range = max(high-low, abs(high-close[1]), abs(low-close[1])); erste Bar na (= `ta.tr(false)`) | Punkte | `r = ta.tr` |
| `ta.tr(handle_na)` | wie oben; `true` -> erste Bar high-low statt na | Punkte | `ta.tr(true)` |
| `ta.atr(len)` | Average True Range = rma(ta.tr(true), len) | Punkte | `sl = close - 1.5 * ta.atr(14)` |
| `ta.stdev(src, len, biased=true)` | Standardabweichung; biased teilt durch len, sonst len-1 | wie src | `ta.stdev(close, 20)` |
| `ta.dev(src, len)` | Mittlere absolute Abweichung vom SMA der letzten len Werte | wie src | `ta.dev(close, 20)` |
| `ta.change(src, len=1)` | src - src[len] | wie src | `ta.change(close)` |
| `ta.mom(src, len)` | Momentum = src - src[len] | wie src | `ta.mom(close, 10)` |
| `ta.roc(src, len)` | 100 * (src - src[len]) / src[len]; na wenn src[len] = 0 | Prozent | `ta.roc(close, 10)` |

## Semantik-Details
- **EMA-Seed:** Die Pine-Doku zeigt fuer `ta.ema` Beispielcode mit Seed = erster Quellwert,
  das TradingView-Builtin liefert aber na fuer die ersten len-1 Bars und startet mit der SMA.
  Umgesetzt ist das Builtin-Verhalten (SMA-Seed). Fuer `ta.rma` steht der SMA-Seed explizit in der Doku.
  Nicht gegen einen TradingView-Export geprueft (Annahme).
- **na in der Quelle:** Fensterfunktionen (sma, wma, hma, stdev, dev, change, mom, roc) liefern na,
  solange ein na im Fenster liegt. ema/rma/atr liefern bei na-Quelle na und behalten ihren Zustand.
- **Aufrufstellen:** Zwei identische Aufrufe an verschiedenen Stellen haben getrennte Zustaende.
  Ein Aufruf in einem `if`, der nicht jede Bar laeuft, sieht nur die Bars, an denen er lief (wie Pine).
  Mehrfachaufruf derselben Stelle in derselben Bar (Schleife) schreitet nicht doppelt fort.
- **`ta.tr` nutzt `close[1]`** der echten Kurs-Series (nicht die eigene History).
- **Nicht umgesetzt:** `ta.vwma` — die Bars haben kein Volumen.
- `len` muss >= 1 sein (sonst Fehler); `ta.change` erlaubt len >= 0.
