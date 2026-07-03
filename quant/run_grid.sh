#!/bin/bash
cd /home/pouya/pine-engine/quant
P="/mnt/c/Users/nader/Documents/Claude-memories/trading bot/v25_engine.pine"
D=/mnt/d/C-Transfer-2026-06-11/Claude-memories/HistoricalTradingData/NQ_continuous_1m.csv
run(){ python3 export_trades.py --pine "$P" --data "$D" --start 2019-01-01 "$@"; }
run --param slPoints=9     --param slPointsWedThu=9    --out trades_g1_sl9.csv
run --param slPoints=12.5  --param slPointsWedThu=14   --out trades_g2_sl12.csv
run --param slPoints=16    --param slPointsWedThu=16   --out trades_g3_sl16.csv
run --param enableKillWindow=false                     --out trades_g4_nokw.csv
run --param skipAfterWin=2                              --out trades_g5_skip2.csv
run --param cutoffAfterOpenMin=60                       --out trades_g6_cut60.csv
run --param enableWedThuTrading=false                  --out trades_g7_nowed.csv
run --param enableRetraceOverride=false                --out trades_g8_noretr.csv
# baseline restricted to 2019+ for fair PBO alignment
run --out trades_base2019.csv
echo "GRID_DONE"
