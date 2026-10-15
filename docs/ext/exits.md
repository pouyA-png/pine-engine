# Exit-Kern (Paket P1a) — strategy.exit / strategy.cancel

Tickgroesse: `StrategyAPI(mintick=0.25)` (NQ-Standard, 1 Tick = 0,25 Punkte). Preise in NQ-Punkten.
Fehlender Wert, `0` und `na` bedeuten bei `limit`/`stop`/`profit`/`loss`/`trail_price` „nicht gesetzt“.

| Pine | Wirkung | Einheit | Beispiel |
|---|---|---|---|
| `strategy.exit(id, from_entry, qty, qty_percent, profit, limit, loss, stop, trail_price, trail_points, trail_offset, oca_name, comment, comment_profit, comment_loss, comment_trailing)` | Positionsargumente in Pine-v5-Reihenfolge; `alert_*`/`disable_alert` ohne Wirkung; `oca_name` wird abgelehnt (Laufzeitfehler statt stillem Ignorieren) | – | `strategy.exit("X", "L", 1)` |
| `stop=` ohne `limit=` | Nur Stop, kein Phantom-Ziel bei 0 (Bugfix). Umgekehrt `limit=` ohne `stop=`: kein Stop | Preis | `strategy.exit("X", from_entry="L", stop=90)` → Long 100 schliesst bei 90 |
| `profit=` / `loss=` | Ziel/Stop relativ zum tatsaechlichen Einstiegspreis: Long `entry ± Ticks·mintick`. Sind `limit` und `profit` beide gesetzt, gilt das naeher am Einstieg liegende (ebenso `stop`/`loss`) | Ticks | `profit=40, loss=20` → Long 100: TP 110, SL 95 |
| `trail_points=` / `trail_price=` + `trail_offset=` | Trailing-Stop: aktiv, sobald Hoch (Long) `trail_price` bzw. `entry + trail_points·mintick` erreicht; Stop = Extrem − `trail_offset·mintick` (Short spiegelbildlich). **Konservativ:** Aktivierung und Extrem einer Bar gelten erst ab der naechsten Bar; die Fuellungs-Bar zaehlt nicht. Ein zusaetzlicher fester `stop` gilt weiter, der engere Stop gewinnt | Ticks bzw. Preis | `trail_points=20, trail_offset=8` → ab 105 aktiv, Stop 2 Punkte unter Hoch |
| `qty_percent=` | Teilexit in Prozent der **Ursprungsmenge** der Position, abgerundet auf ganze Kontrakte; gekappt auf die Restmenge. Nur wirksam ohne `qty` | % | Menge 4: `qty_percent=50` → 2 Kontrakte |
| `qty` fehlt/0 | Pine-Default: ganze Restposition (vorher: Schliessung mit Menge 0) | Kontrakte | `strategy.exit("X", "L", stop=90)` |
| `comment=` / `comment_trailing=` | `comment` ist Rueckfall fuer Gewinn, Verlust und Trailing; `comment_profit`/`comment_loss`/`comment_trailing` haben Vorrang | Text | `comment="ALL", comment_profit="WIN"` |
| `from_entry` weggelassen | Exit gilt fuer **alle** offenen Positionen (auch spaeter gefuellte), feuert je Position hoechstens einmal. Mit `from_entry` unveraendert | – | `strategy.exit("ALL", stop=95)` |
| `strategy.cancel(id)` | Storniert die wartende Entry-Order **und** eine Exit-Order mit dieser id; auch `strategy.cancel(id="X")` | – | `strategy.cancel("X")` |

## Exit-Grund
`ClosedTrade.extra['exit_kind']` = `'tp'` | `'sl'` | `'trail'` (aus process_exits) sowie `extra['exit_id']`.
Gesetzt per `setdefault` **nach** den `on_close`-Hooks — ein Plugin-Grund (z. B. `'be'` aus ext/mgmt_stops) hat Vorrang.

## Bugfix Entrybar-Doppelpruefung (`PINE_ENTRYBAR_STOP=on|gap`)
Der zweite Durchgang nach dem Skript prueft nur (Exit-id, Entry-id)-Paare, die der erste Durchgang derselben Bar
**nicht** geprueft hat (vom Skript in dieser Bar neu angelegte Exits). Beispiel: Einstieg 100 zum Open, Bar 106/98,
TP1 105 fuellt, Skript zieht den Stop auf 100 → kein Ausstoppen in dieser Bar.

## PINE_INTRABAR
`tv`/`worst`/`best` wirken nur, wenn Ziel **und** Stop in derselben Bar erreichbar sind. Stop-only-Exits enden in allen
drei Modi am Stop, Limit-only-Exits am Ziel.
