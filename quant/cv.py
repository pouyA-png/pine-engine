#!/usr/bin/env python3
"""Time-series validation + overfitting control on trade lists.
- chronological IS/OS split
- walk-forward windows (fixed config -> stability of the as-is edge)
- Deflated Sharpe Ratio (Bailey & Lopez de Prado) given #trials
- PBO via CSCV (Combinatorially-Symmetric Cross-Validation) over a config matrix

DSR/PBO operate on per-PERIOD return series. build_period_matrix() turns N config
trade-CSVs into an aligned (periods x configs) daily-return matrix.
Usage examples:
  python3 quant/cv.py split   --trades T.csv --point_value 1
  python3 quant/cv.py wf      --trades T.csv --point_value 1 --folds 6
  python3 quant/cv.py dsr     --trades T.csv --point_value 1 --trials 20
  python3 quant/cv.py pbo     --matrix cfgA.csv cfgB.csv ... --point_value 1
"""
import argparse, csv, json, math
from collections import defaultdict
from datetime import datetime
import metrics as M


def daily_series(trades, point_value, capital):
    d = defaultdict(float)
    for t in trades:
        d[t["exit_time"].date()] += t["ppc"] * t["qty"] * point_value
    return [d[k] for k in sorted(d)], sorted(d)


def sharpe_of(rets):
    if len(rets) < 2: return 0.0
    mu = sum(rets) / len(rets)
    sd = (sum((x - mu) ** 2 for x in rets) / (len(rets) - 1)) ** 0.5
    return (mu / sd * math.sqrt(252)) if sd else 0.0


def _norm_cdf(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def deflated_sharpe(rets, trials):
    """DSR: prob the observed (annualized) Sharpe is real after N trials, adjusting for
    non-normality (skew/kurt) and selection. Returns SR, DSR, and the haircut threshold."""
    n = len(rets)
    if n < 3: return {"error": "too few obs"}
    mu = sum(rets) / n
    sd = (sum((x - mu) ** 2 for x in rets) / (n - 1)) ** 0.5
    if sd == 0: return {"error": "zero vol"}
    sr = mu / sd  # per-period (non-annualized) for DSR math
    skew = (sum(((x - mu) / sd) ** 3 for x in rets) / n)
    kurt = (sum(((x - mu) / sd) ** 4 for x in rets) / n)
    # expected max Sharpe under N independent trials (null SR=0)
    euler = 0.5772156649
    e = math.e
    z1 = _inv_norm(1 - 1.0 / trials)
    z2 = _inv_norm(1 - 1.0 / (trials * e))
    sr0 = (sd * 0 + 1) * 0  # null mean SR=0
    exp_max = (z1 * (1 - euler) + z2 * euler) / math.sqrt(252) * 0 + (z1 * (1 - euler) + z2 * euler)
    exp_max_sr = exp_max / math.sqrt(n)  # variance of SR estimate ~1/n under null  -> threshold SR
    # DSR statistic
    denom = math.sqrt(1 - skew * sr + (kurt - 1) / 4 * sr ** 2)
    dsr = _norm_cdf(((sr - exp_max_sr) * math.sqrt(n - 1)) / denom) if denom > 0 else float("nan")
    return {"sharpe_ann": round(sr * math.sqrt(252), 2), "skew": round(skew, 2), "kurtosis": round(kurt, 2),
            "trials": trials, "expected_max_sharpe_ann_under_null": round(exp_max_sr * math.sqrt(252), 2),
            "DSR": round(dsr, 4), "verdict": "real edge (DSR>0.95)" if dsr > 0.95 else ("ambiguous" if dsr > 0.5 else "likely overfit")}


def _inv_norm(p):
    # Acklam's inverse normal CDF approximation
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    pl = 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p)); return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p <= 1 - pl:
        q = p - 0.5; r = q*q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2 * math.log(1 - p)); return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def pbo_cscv(matrix, names, S=10):
    """Probability of Backtest Overfitting via CSCV. matrix: list of per-config daily-return
    lists (aligned same length). Splits T periods into S blocks, all C(S,S/2) train/test
    combos; for each, IS-best config's OOS rank -> logit. PBO = P(OOS rank in bottom half)."""
    import itertools
    C = len(matrix); T = min(len(m) for m in matrix)
    mat = [m[:T] for m in matrix]
    blocks = [list(range(i, T, S)) for i in range(S)]  # interleaved blocks
    half = S // 2
    lam = []
    for tr in itertools.combinations(range(S), half):
        te = [b for b in range(S) if b not in tr]
        tr_idx = [i for b in tr for i in blocks[b]]
        te_idx = [i for b in te for i in blocks[b]]
        def sr_on(cfg, idx): return sharpe_of([mat[cfg][i] for i in idx])
        is_sr = [sr_on(c, tr_idx) for c in range(C)]
        best = max(range(C), key=lambda c: is_sr[c])
        oos = [sr_on(c, te_idx) for c in range(C)]
        rank = sorted(range(C), key=lambda c: oos[c]).index(best)  # 0=worst
        w = (rank + 1) / (C + 1)
        lam.append(math.log(w / (1 - w)))
    pbo = sum(1 for x in lam if x <= 0) / len(lam)
    return {"configs": C, "periods": T, "splits": S, "combos": len(lam),
            "PBO": round(pbo, 4), "median_logit": round(sorted(lam)[len(lam)//2], 3),
            "verdict": "robust (PBO<0.5)" if pbo < 0.5 else "OVERFIT (PBO>=0.5)"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["split", "wf", "dsr", "pbo"])
    ap.add_argument("--trades")
    ap.add_argument("--matrix", nargs="+")
    ap.add_argument("--point_value", type=float, default=1.0)
    ap.add_argument("--capital", type=float, default=100000.0)
    ap.add_argument("--folds", type=int, default=6)
    ap.add_argument("--trials", type=int, default=20)
    ap.add_argument("--is_frac", type=float, default=0.5)
    a = ap.parse_args()

    if a.cmd == "split":
        tr = M.load_trades(a.trades); tr.sort(key=lambda t: t["entry_time"])
        k = int(len(tr) * a.is_frac)
        IS = M.compute(tr[:k], a.point_value, a.capital); OS = M.compute(tr[k:], a.point_value, a.capital)
        key = ["trades", "pf", "wr_%", "net_$", "max_dd_%", "sharpe", "sortino", "expectancy_$"]
        print(json.dumps({"IS": {x: IS[x] for x in key}, "OS": {x: OS[x] for x in key},
                          "pf_decay": round(OS["pf"] - IS["pf"], 2)}, indent=2))
    elif a.cmd == "wf":
        tr = M.load_trades(a.trades); tr.sort(key=lambda t: t["entry_time"])
        N = len(tr); sz = N // a.folds
        out = []
        for i in range(a.folds):
            seg = tr[i*sz: (i+1)*sz if i < a.folds-1 else N]
            m = M.compute(seg, a.point_value, a.capital)
            out.append({"fold": i+1, "n": m["trades"], "pf": m["pf"], "wr": m["wr_%"], "net": m["net_$"], "sharpe": m["sharpe"]})
        pfs = [o["pf"] for o in out if o["pf"] != float("inf")]
        print(json.dumps({"folds": out, "pf_min": round(min(pfs),2), "pf_median": round(sorted(pfs)[len(pfs)//2],2),
                          "folds_pf>1": sum(1 for p in pfs if p>1), "of": len(pfs)}, indent=2))
    elif a.cmd == "dsr":
        tr = M.load_trades(a.trades); rets, _ = daily_series(tr, a.point_value, a.capital)
        print(json.dumps(deflated_sharpe(rets, a.trials), indent=2))
    elif a.cmd == "pbo":
        mats = []; names = []
        for p in a.matrix:
            tr = M.load_trades(p); rets, _ = daily_series(tr, a.point_value, a.capital)
            mats.append(rets); names.append(p.split("/")[-1])
        T = min(len(m) for m in mats)
        print(json.dumps(pbo_cscv(mats, names, S=10), indent=2))


if __name__ == "__main__":
    main()
