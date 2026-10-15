# P9 — Kosten und realistische Fuellungen (`nq.cost_*`, `nq.fill_*`)

Modul: `pine_engine/ext/costs.py`. Ein BrokerHook (key `nq.costs`), aktiviert beim
ersten Aufruf. Jeder Aufruf setzt nur einen Parameter (idempotent, jede Bar erneut
aufrufen ist unschaedlich). Wirkung ab der naechsten Fuellung (Aufruf in Bar t ->
ab Bar t+1; `strategy.close*` im selben Skriptlauf sind sofort betroffen).
Ohne Aufruf: Backtest unveraendert. Forschungsstandard bisher: `nq.cost_points(2)`.

Punktwert 20 $/Punkt (`strategy._point_value`), 1 Tick = 0,25 Punkte.

| Pine | Wirkung | Einheit | Beispiel |
|---|---|---|---|
| `nq.cost_points(pts)` | Round-Turn-Kosten je Kontrakt, nur verbucht (Preise unveraendert) | Punkte | `nq.cost_points(2)` |
| `nq.cost_commission(usd)` | Round-Turn-Kommission je Kontrakt, nur verbucht | $ je Kontrakt | `nq.cost_commission(4.5)` |
| `nq.fill_slippage(entry_pts, exit_pts, limits=false)` | adverse Preisverschiebung: Market-/Stop-Einstiege, SL/Trail, close/close_all/Reversal/Flatten immer; Limit-Einstiege und TP nur bei Gap-Fuellung zum Open (hoechstens bis zum Limit); `limits=true` auch auf normale Limit-Einstiege/TP | Punkte | `nq.fill_slippage(0.5, 1)` |
| `nq.fill_stop_slippage(pts)` | zusaetzliche Slippage nur bei Stop-/Trail-Ausloesung (addiert sich zu `exit_pts`) | Punkte | `nq.fill_stop_slippage(1)` |
| `nq.fill_spread(pts)` | halber Spread je Fuellung (Ein- und Ausstieg) adversativ | Punkte (voller Spread) | `nq.fill_spread(0.5)` |
| `nq.fill_trade_through(ticks)` | Limit-Einstieg fuellt nur, wenn das Bar-Extrem das Limit um >= ticks durchschreitet; sonst bleibt die Order stehen. Fuellpreis = Limit (Gap-Open jenseits: Open) | Ticks | `nq.fill_trade_through(1)` |
| `nq.fill_tp_trade_through(ticks)` | TP (`limit=` oder `profit=`) fuellt nur bei Durchschreiten um >= ticks, sonst kein TP in dieser Bar; Fuellpreis = TP | Ticks | `nq.fill_tp_trade_through(1)` |
| `nq.fill_round_tick(on=true)` | Fuellpreise adversativ auf 0,25 runden (Long-Einstieg auf, Long-Ausstieg ab; Short umgekehrt) | – | `nq.fill_round_tick()` |
| `nq.cost_net_pnl` | Variable: realisierter Netto-PnL = Brutto (Preise inkl. Fuellanpassungen) − Summe `cost_usd` | $ | `if nq.cost_net_pnl < -2000` |
| `nq.cost_off()` | Hook entfernen; alle Kosten/Fuellregeln ab jetzt aus | – | `nq.cost_off()` |

Reihenfolge der Preisanpassung: Slippage -> halber Spread -> Tick-Rundung.

## Verbuchung in `ClosedTrade.extra` (jede Teil-Schliessung)

- `cost_points` = `pts + commission_usd / 20` (Round-Turn je Kontrakt, Punkte)
- `cost_usd` = `cost_points x qty x 20` ($)
- `fill_adj_points` = Summe der adversen Preisverschiebung Einstieg + Ausstieg je
  Kontrakt (Punkte; nur Info, steckt schon im Preis, NICHT in `cost_usd`)

Beispiel: Long 2 Kontrakte 100 -> 110, `nq.cost_points(1)` + `nq.cost_commission(4.5)`:
`cost_points` = 1,225, `cost_usd` = 49 $, `nq.cost_net_pnl` = 400 − 49 = 351 $.

## Grenzen

- `nq.fill_tp_trade_through` wird ueber `before_exits` umgesetzt (TP der Spec wird
  waehrend der Pruefung um ticks nach aussen geschoben, in `after_exits`
  zurueckgestellt). Gilt NICHT fuer den zweiten Ausstiegs-Durchgang
  (`PINE_ENTRYBAR_STOP=on|gap`) und nicht fuer Specs ohne `from_entry`.
- `nq.fill_trade_through` gilt nur fuer reine Limit-Einstiege (nicht Stop-Limit).
- Schliessungen ausserhalb von `adjust_exit` (close/close_all, Reversal, EOD/Risk-
  Flatten anderer Plugins) werden in `on_close` angepasst; Hooks, die vor
  `nq.costs` registriert wurden, sehen in ihrem `on_close` noch den Rohpreis.
- `strategy.equity` / `closedtrades.profit` enthalten Fuellanpassungen (im Preis),
  aber nicht `cost_usd` — dafuer `nq.cost_net_pnl`.
