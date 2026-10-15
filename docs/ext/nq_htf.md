# nq.htf_* — hoehere Zeitebenen aus M1 (Paket P6)

Modul: `pine_engine/ext/nq_htf.py`, Tests: `pine_engine/tests/test_ext_nq_htf.py`.

## Aggregation und Lookahead

- **Minuten-Zeitebenen** (`tf_minutes` = 5, 15, 60, 240 ...): Kerzen an UTC-Epoch-Vielfachen ausgerichtet
  (60 = volle UTC-Stunde, 240 = 00/04/08/... UTC). `tf` darf auch String sein: `"5"`, `"D"`, `"W"`.
- **Tag**: NY-Handelstag ab 18:00 America/New_York (Sommer-/Winterzeit korrekt). **Woche**: ab Sonntag 18:00 NY.
- **Abgeschlossen** ist eine Kerze nach Schluss der M1-Bar, deren Ende (time + 1 min) das Kerzenende erreicht
  (5-Min-Kerze 14:30 ist nach der M1-Bar 14:34 fertig), sonst spaetestens mit der ersten Bar der naechsten Kerze
  (Datenluecken; Tag/Woche wechseln daher erst um 18:00 NY, nicht um 17:00).
- `offset >= 1` = abgeschlossene Kerzen (1 = letzte). `offset = 0` = Kerze der aktuellen M1-Bar, **Stand bis jetzt**
  (laufend; auf ihrer letzten M1-Bar identisch mit offset 1). Standard ist `offset = 1`.
- Kein Lookahead: ein Wert fuer offset 1 aendert sich fruehestens am Schluss der letzten M1-Bar der Kerze;
  eine darauf basierende Order fuellt ab der naechsten Bar.
- Nicht genug Kerzen -> `na`. Die Aggregatoren starten beim ersten Aufruf (Nachfuellung aus den letzten
  max. 300 M1-Bars der eingebauten Series), danach fuettert ein lesender Broker-Hook (`nq_htf`) jede Bar,
  auch wenn der Aufruf in einem `if` steht. Ohne Aufruf: kein Hook, Backtest unveraendert.
- Annahme: M1-Daten (Bar-Dauer 60 s).

## Funktionen

| Pine-Signatur | Was | Einheit | Beispiel |
|---|---|---|---|
| `nq.htf_open/high/low/close(tf_minutes, offset=1)` | OHLC der HTF-Kerze | Punkte (Preis) | `c5 = nq.htf_close(5)` |
| `nq.htf_new_bar(tf_minutes)` | true auf der ersten M1-Bar einer neuen HTF-Kerze | bool | `if nq.htf_new_bar(60)` |
| `nq.htf_ema(tf_minutes, len)` | EMA der Closes abgeschlossener HTF-Kerzen (Seed = SMA der ersten len) | Punkte | `nq.htf_ema(15, 20)` |
| `nq.htf_atr(tf_minutes, len)` | ATR (RMA der True Range) abgeschlossener HTF-Kerzen | Punkte | `nq.htf_atr(60, 14)` |
| `nq.htf_day_open/high/low/close(offset=1)` | NY-Handelstag ab 18:00 | Punkte | `pdh = nq.htf_day_high(1)` |
| `nq.htf_week_high/low(offset=1)` | Handelswoche ab So 18:00 NY | Punkte | `pwl = nq.htf_week_low(1)` |
| `nq.htf_bar_index(tf_minutes)` | 0-basierter Index der aktuellen HTF-Kerze (ab erster gesehener) | Anzahl Kerzen | `nq.htf_bar_index(5)` |
| `nq.htf_highest/lowest(tf_minutes, len)` | Max-Hoch / Min-Tief der letzten len abgeschlossenen Kerzen | Punkte | `nq.htf_highest(5, 12)` |
| `nq.htf_body_dir(tf_minutes, offset=1)` | 1 gruen, -1 rot, 0 Doji | -1/0/1 | `nq.htf_body_dir(5) == 1` |
| `nq.htf_range(tf_minutes, offset=1)` | Hoch - Tief der Kerze | Punkte | `nq.htf_range(15, 1) > 20` |
| `request.security(sym, tf, expr)` | nur `expr` = open/high/low/close; Wert der letzten **abgeschlossenen** Kerze (lookahead off, = `nq.htf_*(tf, 1)`); `sym` wird ignoriert | Punkte | `request.security(syminfo.tickerid, "5", close)` |

## Grenzen

- `request.security`: andere Ausdruecke (z. B. `close + 1`, `ta.ema(...)`) -> ValueError; `lookahead=barmerge.lookahead_off`
  kann nicht geschrieben werden, weil `barmerge.*` im Parser/Codegen nicht definiert ist (NameError) — einfach weglassen.
- Kein Symbolwechsel, nur das geladene Instrument.
