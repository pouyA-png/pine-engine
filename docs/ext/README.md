# Engine-Erweiterungen — Katalog (Stand 2026-09-29)

Alle Features sind aus Pine aufrufbar und haben eigene Tests (`pine_engine/tests/test_ext_*.py`).
Ohne Aufruf eines neuen Features bleibt jeder Backtest byte-identisch zum alten Stand.
Architektur: Registry `pine_engine/runtime/ext.py`, Module `pine_engine/ext/*.py`, Broker-Hooks `BrokerHook` in `runtime/broker.py`.

## Kern (broker.py / strategy.py / codegen.py)

- [Exits](exits.md): Stop-only/Limit-only-Fix, Entrybar-Doppelprüfungs-Fix, `profit=`/`loss=` in Ticks, `trail_points`/`trail_price`/`trail_offset`, `qty_percent`, `comment`/`comment_trailing`, `strategy.cancel` für Exits, `strategy.exit` ohne `from_entry`, `extra['exit_kind']`
- [Entries](entries.md): Stop-/Stop-Limit-/Market-Orders, `strategy.entry` mit Reversal, `pyramiding`, `strategy.close(qty=, qty_percent=)`, `expire_bars=`, `strategy.risk.allow_entry_in`, OCA-Cancel
- [Auswertung](metrics.md): `--metrics`, `--export-trades`, `--group-by-entry` (CLI), `reporting/metrics_ext.py`

## [Kosten + realistische Füllungen](costs.md) — `costs.py`

`nq.cost_commission()`, `nq.cost_net_pnl`, `nq.cost_off()`, `nq.cost_points()`, `nq.fill_round_tick()`, `nq.fill_slippage()`, `nq.fill_spread()`, `nq.fill_stop_slippage()`, `nq.fill_tp_trade_through()`, `nq.fill_trade_through()`

## [MFE/MAE-Tracking](metrics.md) — `excursion.py`

`nq.track_excursion()`

## [Break-even, Trailing, Zeit-Exits, EOD](mgmt_stops.md) — `mgmt_stops.py`

`nq.be_after_partial()`, `nq.be_at_points()`, `nq.be_at_r()`, `nq.be_off()`, `nq.eod_flat()`, `nq.eod_off()`, `nq.time_max_bars()`, `nq.time_off()`, `nq.time_stop()`, `nq.trail_bars()`, `nq.trail_off()`, `nq.trail_points()`, `nq.trail_r()`, `nq.trail_step()`

## [Höhere Zeitebenen aus M1](nq_htf.md) — `nq_htf.py`

`nq.htf_atr()`, `nq.htf_bar_index()`, `nq.htf_body_dir()`, `nq.htf_close()`, `nq.htf_day_close()`, `nq.htf_day_high()`, `nq.htf_day_low()`, `nq.htf_day_open()`, `nq.htf_ema()`, `nq.htf_high()`, `nq.htf_highest()`, `nq.htf_low()`, `nq.htf_lowest()`, `nq.htf_new_bar()`, `nq.htf_open()`, `nq.htf_range()`, `nq.htf_week_high()`, `nq.htf_week_low()`, `request.security()`

## [Leg-/Level-Geometrie](nq_levels.md) — `nq_levels.py`

`nq.lvl_fib()`, `nq.lvl_half_neighbor_stop()`, `nq.lvl_leg_size()`, `nq.lvl_min_target()`, `nq.lvl_nearest()`, `nq.lvl_nudge()`, `nq.lvl_qty_split()`, `nq.lvl_r_multiple()`, `nq.lvl_ratio()`, `nq.lvl_round_tick()`, `nq.lvl_tp1_mid()`

## [NQ-Session + Tageslevel](nq_session.md) — `nq_session.py`

`nq.eth`, `nq.eth_high`, `nq.eth_low`, `nq.or_high()`, `nq.or_low()`, `nq.pd_close`, `nq.pd_high`, `nq.pd_low`, `nq.rth`, `nq.rth_bars_since_open`, `nq.rth_high`, `nq.rth_low`, `nq.rth_open`, `nq.sess_bars_since_open`, `nq.sess_day_index`, `nq.sess_first_bar`, `nq.sess_in()`, `nq.sess_is_dst`, `nq.sess_minutes_since()`, `nq.sess_new_rth`, `nq.sess_weekday`

## [Pine-Standard math/str/syminfo/Zeit](pine_std.md) — `pine_std.py`

`fixnan()`, `math.avg()`, `math.log()`, `math.log10()`, `math.pow()`, `math.random()`, `math.round_to_mintick()`, `math.sign()`, `math.sqrt()`, `math.sum()`, `nz()`, `second`, `second()`, `str.contains()`, `str.endswith()`, `str.format()`, `str.length()`, `str.lower()`, `str.replace_all()`, `str.startswith()`, `str.tonumber()`, `str.upper()`, `time()`, `time_close`, `timestamp()`, `weekofyear`, `weekofyear()`

## [Risiko + FTMO-Kontoregeln](risk.md) — `risk.py`

`nq.risk_blocked`, `nq.risk_cooldown()`, `nq.risk_daily_loss()`, `nq.risk_daily_loss_hard()`, `nq.risk_daily_target()`, `nq.risk_day_pnl`, `nq.risk_max_losses_row()`, `nq.risk_max_open()`, `nq.risk_max_trades_day()`, `nq.risk_qty()`, `nq.risk_timezone()`, `nq.risk_total_loss()`

## [strategy.*-Kennzahlen](strategy_vars.md) — `strategy_vars.py`

`nq.day_netprofit`, `strategy.closedtrades.entry_price()`, `strategy.closedtrades.entry_time()`, `strategy.closedtrades.exit_price()`, `strategy.closedtrades.exit_time()`, `strategy.closedtrades.first_index`, `strategy.closedtrades.max_drawdown()`, `strategy.closedtrades.max_runup()`, `strategy.eventrades`, `strategy.grossloss`, `strategy.grossprofit`, `strategy.initial_capital`, `strategy.losstrades`, `strategy.max_drawdown`, `strategy.max_runup`, `strategy.netprofit`, `strategy.openprofit`, `strategy.opentrades.entry_bar_index()`, `strategy.opentrades.entry_time()`, `strategy.opentrades.size()`, `strategy.position_avg_price`, `strategy.position_size`, `strategy.wintrades`

## [Durchschnitte + Volatilität](ta_ma.md) — `ta_ma.py`

`ta.atr()`, `ta.change()`, `ta.dev()`, `ta.ema()`, `ta.hma()`, `ta.mom()`, `ta.rma()`, `ta.roc()`, `ta.sma()`, `ta.stdev()`, `ta.tr`, `ta.tr()`, `ta.wma()`

## [ta-Hilfsfunktionen + Oszillatoren](ta_util.md) — `ta_util.py`

`ta.barssince()`, `ta.cci()`, `ta.correlation()`, `ta.cross()`, `ta.cum()`, `ta.falling()`, `ta.highestbars()`, `ta.linreg()`, `ta.lowestbars()`, `ta.median()`, `ta.percentrank()`, `ta.range()`, `ta.rising()`, `ta.stoch()`, `ta.valuewhen()`

Konstanten: `barmerge.gaps_off`, `barmerge.gaps_on`, `barmerge.lookahead_off`, `barmerge.lookahead_on`, `syminfo.currency`, `syminfo.mintick`, `syminfo.pointvalue`, `syminfo.ticker`, `syminfo.tickerid`, `syminfo.timezone`, `timeframe.isdaily`, `timeframe.isdwm`, `timeframe.isintraday`, `timeframe.isminutes`, `timeframe.ismonthly`, `timeframe.isseconds`, `timeframe.isweekly`, `timeframe.multiplier`, `timeframe.period`
