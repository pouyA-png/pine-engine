import sys,os,json,itertools
sys.path.insert(0,os.path.dirname(os.path.abspath("."))); sys.path.insert(0,"/home/pouya/pine-engine")
from pine_engine.engine import compile_pine, run_backtest
from pine_engine.data.loader import load_bars_csv
from sweep import metr
P="/mnt/c/Users/nader/Documents/Claude-memories/trading bot/v25_dyn.pine"
c=compile_pine(P)
for yr,(s,e) in [("2017",("2017-01-01","2017-12-31")),("2016",("2016-01-01","2016-12-31"))]:
    bars=load_bars_csv("nq_1617.csv",start_date=s,end_date=e)
    print(f"\n==== {yr}  ({len(bars)} bars) — leg-scaled SL (= factor x preopen-window-range) ====")
    print(f"{'variant':22} {'n':>4} {'PF0':>5} {'PFc2.5':>6} {'net':>8} {'WR':>5} {'maxDD':>6} {'strk':>4}")
    # baseline fixed for reference
    for nm,pp in [("FIXED 11.25",{"slMode":"static","slPoints":11.25,"slPointsWedThu":11.25}),
                  ("FIXED 30",{"slMode":"static","slPoints":30,"slPointsWedThu":30})]:
        tr=run_backtest(c,bars,pp); m=metr(tr,2.5,20,100000); m0=metr(tr,0,20,100000)
        print(f"{nm:22} {m['n']:>4} {m0['pf']:>5.2f} {m['pf']:>6.2f} {m['net']:>8,} {m['wr']:>5} {m['maxdd']:>6,} {m['streak']:>4}")
    for k in [0.2,0.3,0.4,0.5,0.75]:
        for fl in [1,2,3]:
            pp={"slMode":"volwin","slVolFactor":k,"slFloor":fl,"slCap":40,"enableDynLeg":False}
            tr=run_backtest(c,bars,pp); m=metr(tr,2.5,20,100000); m0=metr(tr,0,20,100000)
            print(f"legSL k{k} floor{fl:<6} {m['n']:>4} {m0['pf']:>5.2f} {m['pf']:>6.2f} {m['net']:>8,} {m['wr']:>5} {m['maxdd']:>6,} {m['streak']:>4}")
