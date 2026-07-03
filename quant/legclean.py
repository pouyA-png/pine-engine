import sys; sys.path.insert(0,"/home/pouya/pine-engine")
from pine_engine.engine import compile_pine, run_backtest
from pine_engine.data.loader import load_bars_csv
from sweep import metr
c=compile_pine("/mnt/c/Users/nader/Documents/Claude-memories/trading bot/v25_dyn.pine")
for yr,(s,e) in [("2017",("2017-01-01","2017-12-31"))]:
    bars=load_bars_csv("nq_1617.csv",start_date=s,end_date=e)
    print(f"== {yr} leg-scaled SL, Leg-Filter ON (clean) ==")
    print(f"{'variant':16} {'n':>4} {'PF0':>5} {'PFc':>5} {'WR':>5} {'mDD':>6}")
    for nm,pp in [("FIX30",{"slMode":"static","slPoints":30,"slPointsWedThu":30})]:
        tr=run_backtest(c,bars,pp);m=metr(tr,2.5,20,1e5);m0=metr(tr,0,20,1e5)
        print(f"{nm:16} {m['n']:>4} {m0['pf']:>5.2f} {m['pf']:>5.2f} {m['wr']:>5} {m['maxdd']:>6,}")
    for k in [2,3,4,6]:
        pp={"slMode":"volwin","slVolFactor":k,"slFloor":3,"slCap":80}  # dynLeg default ON
        tr=run_backtest(c,bars,pp);m=metr(tr,2.5,20,1e5);m0=metr(tr,0,20,1e5)
        print(f"legxk{k:<11} {m['n']:>4} {m0['pf']:>5.2f} {m['pf']:>5.2f} {m['wr']:>5} {m['maxdd']:>6,}")
print("DONE")
