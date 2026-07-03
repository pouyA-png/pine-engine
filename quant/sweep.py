#!/usr/bin/env python3
"""Fast parameter sweep: compile pine ONCE, load bars ONCE, run many param sets.
Computes PF/WR/net/maxDD/streak/Sharpe per variant at a given cost. Stdlib only.
Usage: python3 sweep.py --pine F --data CSV [--cost 2.5 --pv 20 --capital 100000]
Reads variant grid from build_variants(); prints ranked table + JSON.
"""
import argparse, sys, os, json, itertools, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pine_engine.engine import compile_pine, run_backtest
from pine_engine.data.loader import load_bars_csv


def trade_pnls(trades, cost, pv):
    out = []
    for t in trades:
        d = (t.exit_price - t.entry_price) if t.side == "long" else (t.entry_price - t.exit_price)
        out.append((d - cost) * t.qty * pv)
    return out


def metr(trades, cost, pv, capital):
    p = trade_pnls(trades, cost, pv)
    if not p:
        return {"n": 0, "pf": 0, "net": 0, "wr": 0, "maxdd": 0, "streak": 0, "sharpe": 0}
    gp = sum(x for x in p if x > 0); gl = abs(sum(x for x in p if x <= 0))
    eq = peak = capital; mdd = 0.0
    for x in p:
        eq += x; peak = max(peak, eq); mdd = max(mdd, peak - eq)
    # streak
    s = mx = 0
    for x in p:
        if x <= 0: s += 1; mx = max(mx, s)
        else: s = 0
    # daily sharpe
    from collections import defaultdict
    daily = defaultdict(float)
    for t, x in zip(trades, p):
        daily[t.exit_time.date()] += x
    dv = [v / capital for v in daily.values()]
    mu = sum(dv) / len(dv) if dv else 0
    sd = (sum((z - mu) ** 2 for z in dv) / (len(dv) - 1)) ** 0.5 if len(dv) > 1 else 0
    sh = mu / sd * math.sqrt(252) if sd else 0
    wins = sum(1 for x in p if x > 0)
    return {"n": len(p), "pf": round(gp / gl, 3) if gl else 9.99, "net": round(sum(p)),
            "wr": round(wins / len(p) * 100, 1), "maxdd": round(mdd), "streak": mx, "sharpe": round(sh, 2)}


def build_variants():
    """~100 creative leg/SL/TP variants. Each = (name, paramdict)."""
    V = []
    # baseline
    V.append(("baseline", {}))
    # --- SL static sweep (Tue/Fri = WedThu same) ---
    for sl in [6, 8, 9, 11.25, 14, 16, 18, 22, 26, 30]:
        V.append((f"sl{sl}", {"slMode": "static", "slPoints": sl, "slPointsWedThu": sl}))
    # --- SL vol-window factor sweep ---
    for k in [0.20, 0.30, 0.40, 0.55, 0.70, 0.90]:
        for fl in [3, 6]:
            V.append((f"volSL_k{k}_fl{fl}", {"slMode": "volwin", "slVolFactor": k, "slFloor": fl, "slCap": 60, "enableDynLeg": False}))
    # --- TP nudge sweep (earlier/later exits) ---
    for tp in [0, 3, 5, 8, 12, 18]:
        V.append((f"tpNudge{tp}", {"tpNudgePts": tp}))
    # --- entry nudge sweep ---
    for en in [0, 1, 2, 4, 6]:
        V.append((f"entNudge{en}", {"entryNudgePts": en}))
    # --- BE offset sweep ---
    for be in [0, 1, 2, 4, 8]:
        V.append((f"be{be}", {"beOffsetPoints": be}))
    # --- minRange (leg) sweep ---
    for mr in [8, 14, 20, 28, 40, 60]:
        V.append((f"minRange{mr}", {"minRangeTicks": mr}))
    # --- pivot sweep ---
    for pl in [2, 3, 4]:
        V.append((f"pivot{pl}", {"pivotLeft": pl, "pivotRight": pl}))
    # --- cutoff sweep ---
    for cu in [15, 30, 45, 60, 90]:
        V.append((f"cutoff{cu}", {"cutoffAfterOpenMin": cu}))
    # --- kill-window on/off ---
    V.append(("noKW", {"enableKillWindow": False}))
    # --- skipAfterWin ---
    for sk in [1, 2, 3]:
        V.append((f"skip{sk}", {"skipAfterWin": sk}))
    # --- override toggles ---
    for nm, pk in [("noRetrace", "enableRetraceOverride"), ("noImpulse", "enableImpulseOriginOverride"),
                   ("noAccumMom", "enableAccumMomentumPriority"), ("noEarly", "enableEarlyScan")]:
        V.append((nm, {pk: False}))
    # --- weekday ---
    V.append(("noWedThu", {"enableWedThuTrading": False}))
    V.append(("mondayOn", {"enableMondayTrading": True}))
    # --- combos: best-guess SL x TP ---
    for sl in [14, 18, 22]:
        for tp in [0, 8]:
            V.append((f"sl{sl}_tp{tp}", {"slMode": "static", "slPoints": sl, "slPointsWedThu": sl, "tpNudgePts": tp}))
    # --- combos: volSL x cutoff ---
    for k in [0.30, 0.45]:
        for cu in [30, 60]:
            V.append((f"volk{k}_cut{cu}", {"slMode": "volwin", "slVolFactor": k, "slFloor": 4, "slCap": 60, "enableDynLeg": False, "cutoffAfterOpenMin": cu}))
    return V


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pine", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--cost", type=float, default=2.5)
    ap.add_argument("--pv", type=float, default=20)
    ap.add_argument("--capital", type=float, default=100000)
    ap.add_argument("--out", default="sweep_results.json")
    a = ap.parse_args()
    c = compile_pine(a.pine)
    bars = load_bars_csv(a.data, start_date=a.start, end_date=a.end)
    print(f"compiled, {len(bars)} bars, {len(build_variants())} variants, cost={a.cost}", file=sys.stderr)
    rows = []
    for i, (name, params) in enumerate(build_variants()):
        try:
            tr = run_backtest(c, bars, params or None)
            m = metr(tr, a.cost, a.pv, a.capital)
            m0 = metr(tr, 0.0, a.pv, a.capital)
            m["pf0"] = m0["pf"]; m["name"] = name; m["params"] = params
            rows.append(m)
        except Exception as e:
            rows.append({"name": name, "error": str(e)[:80], "params": params, "pf": -1, "n": 0})
        if (i + 1) % 20 == 0:
            print(f"  {i+1} done", file=sys.stderr)
    rows.sort(key=lambda r: r.get("pf", -1), reverse=True)
    json.dump(rows, open(a.out, "w"), indent=1)
    print(f"\n{'name':22} {'n':>5} {'PF0':>6} {'PFc':>6} {'net':>9} {'WR':>5} {'maxDD':>7} {'strk':>4} {'shrp':>5}")
    for r in rows:
        if "error" in r:
            print(f"{r['name']:22} ERR {r['error']}"); continue
        print(f"{r['name']:22} {r['n']:>5} {r['pf0']:>6.2f} {r['pf']:>6.2f} {r['net']:>9,} {r['wr']:>5} {r['maxdd']:>7,} {r['streak']:>4} {r['sharpe']:>5}")


if __name__ == "__main__":
    main()
