import pandas as pd, numpy as np, sys

def audit(path, has_symbol):
    print("="*70); print("FILE:", path); print("="*70)
    df = pd.read_csv(path)
    print("rows:", len(df), "cols:", list(df.columns))
    df['dt'] = pd.to_datetime(df['datetime'], utc=True)
    n = len(df)
    # monotonicity
    diffs = df['dt'].diff()
    mono = (diffs.dropna() > pd.Timedelta(0)).all()
    print("strictly increasing timestamps:", mono)
    # duplicates
    dups = df['dt'].duplicated().sum()
    print("duplicate timestamps:", dups)
    if dups:
        print("  sample dup ts:", df['dt'][df['dt'].duplicated(keep=False)].head(6).tolist())
    print("first:", df['dt'].iloc[0], "last:", df['dt'].iloc[-1])
    span_days = (df['dt'].iloc[-1]-df['dt'].iloc[0]).days
    print("span days:", span_days)
    # gaps: count distribution of consecutive minute diffs
    d_min = (diffs.dt.total_seconds()/60).dropna()
    print("diff(min) describe:", d_min.describe().to_dict())
    print("  ==1 min:", int((d_min==1).sum()), " >1min:", int((d_min>1).sum()), " <=0:", int((d_min<=0).sum()))
    # big gaps > 1 day (weekend/holiday/roll boundaries)
    big = diffs[diffs > pd.Timedelta(hours=12)]
    print("gaps >12h count:", len(big))
    # weekend coverage: bars per weekday
    df['wd'] = df['dt'].dt.dayofweek
    print("bars per weekday (0=Mon..6=Sun):", df.groupby('wd').size().to_dict())
    # hours-of-day coverage
    hrs = df['dt'].dt.hour.value_counts().sort_index()
    print("hours present (UTC):", sorted(hrs.index.tolist()))
    # price scale over time (yearly close min/max)
    df['yr'] = df['dt'].dt.year
    yr = df.groupby('yr')['close'].agg(['min','max','mean','count'])
    print("yearly close min/max/mean/count:")
    print(yr.to_string())
    # tick size inference
    px = df['close'].round(4)
    pdiff = np.diff(np.sort(px.unique()))
    pdiff = pdiff[pdiff>0]
    print("min price increment seen:", round(pdiff.min(),4) if len(pdiff) else None,
          " median incr:", round(np.median(pdiff),4) if len(pdiff) else None)
    if has_symbol:
        print("--- CONTRACT ROLL (symbol col) ---")
        df['sym_change'] = df['symbol'] != df['symbol'].shift(1)
        rolls = df[df['sym_change']].copy()
        print("distinct symbols:", df['symbol'].nunique(), "rolls:", len(rolls)-1)
        # measure jump at each roll seam
        seams=[]
        for idx in rolls.index[1:]:
            pos = df.index.get_loc(idx)
            if pos==0: continue
            prev_close = df['close'].iloc[pos-1]
            new_open = df['open'].iloc[pos]
            gap = new_open - prev_close
            seams.append((str(df['dt'].iloc[pos]), df['symbol'].iloc[pos-1], df['symbol'].iloc[pos], round(prev_close,2), round(new_open,2), round(gap,2)))
        print("roll seams (dt, from, to, prevclose, newopen, gap_pts):")
        for s in seams: print("  ", s)
        gaps_pts = [abs(s[5]) for s in seams]
        if gaps_pts:
            print("roll seam abs gap pts: max", max(gaps_pts), "mean", round(np.mean(gaps_pts),2),
                  ">11.25pt (SL size):", sum(1 for g in gaps_pts if g>11.25))
    print()
    return df

audit("/mnt/d/C-Transfer-2026-06-11/Claude-memories/HistoricalTradingData/NQ_continuous_1m.csv", True)
audit("/mnt/c/Users/nader/US100_M1_FTMO_utc.csv", False)
