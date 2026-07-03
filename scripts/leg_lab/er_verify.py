#!/usr/bin/env python3
"""
Hard verification of the ER-vs-max_move A/B on the real FTMO M5 feed.
Deterministic stats only (no agents): significance, sub-period stability,
in/out-of-sample split, top-winner sensitivity. Trustworthy ground truth that
the adversarial workflow then tries to refute.
"""
import argparse, math
from collections import defaultdict
import leg_lab as L

WIN = 6


def tstat(rs):
    n = len(rs)
    if n < 2: return 0.0, 0.0
    mu = sum(rs) / n
    sd = (sum((x - mu) ** 2 for x in rs) / (n - 1)) ** 0.5
    t = mu / (sd / math.sqrt(n)) if sd else 0.0
    return mu, t


def pf_of(trades):
    gp = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gl = abs(sum(t["pnl"] for t in trades if t["pnl"] <= 0))
    return (gp / gl) if gl else float("inf"), gp - gl, len(trades)


def monthly(trades):
    m = defaultdict(float)
    for t in trades:
        m[t["date"][:7]] += t["pnl"]
    return dict(sorted(m.items()))


def split_half(days):
    ks = sorted(days)
    mid = len(ks) // 2
    return ks[:mid], ks[mid:]


def get_trades(days, method, sl):
    return L.run_method(method, days, [sl])[sl]


def report(label, trades):
    pf, net, n = pf_of(trades)
    rs = [t["rr"] for t in trades]
    mu, t = tstat(rs)
    # top-5 winner removal
    wins = sorted((x["pnl"] for x in trades if x["pnl"] > 0), reverse=True)
    net_no5 = net - sum(wins[:5])
    print(f"\n## {label}")
    print(f"  n={n} PF={pf:.2f} net={net:.0f}pt  meanR={mu:.3f} t={t:.2f}  net_minus_top5winners={net_no5:.0f}pt")
    mo = monthly(trades)
    pos = sum(1 for v in mo.values() if v > 0)
    print(f"  months: {len(mo)} ({pos} pos / {len(mo)-pos} neg)")
    print("  " + "  ".join(f"{k[5:]}:{v:+.0f}" for k, v in mo.items()))
    return pf, net, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/mnt/c/Users/nader/US100_M5_FTMO_utc.csv")
    ap.add_argument("--start", default="2025-04-28")
    ap.add_argument("--end", default="2026-06-17")
    ap.add_argument("--sl", type=float, default=16.0)
    args = ap.parse_args()
    days = L.load_days(args.data, args.start, args.end)

    mm = {"fam": "max_move", "p": {"win": WIN}, "id": -1, "name": "max_move"}
    # candidates flagged by the sweep
    er_best = {"fam": "efficiency_ratio", "id": -2, "name": "ER_0.35_3",
               "p": {"win": WIN, "minER": 0.35, "minLegBars": 3, "dirLast": True, "minRange": 5.0, "fallback": False}}
    er_robust = {"fam": "efficiency_ratio", "id": -3, "name": "ER_dirFalse_0.55_1",
                 "p": {"win": WIN, "minER": 0.55, "minLegBars": 1, "dirLast": False, "minRange": 5.0, "fallback": False}}

    print(f"# FTMO M5 {args.start}..{args.end} SL={args.sl}  (PnL in points)")
    print("=" * 70)
    print("### FULL-PERIOD")
    report("BASELINE max_move", get_trades(days, mm, args.sl))
    report("ER best-PF (0.35/3, dirLast)", get_trades(days, er_best, args.sl))
    report("ER dirLast=False (0.55/1)", get_trades(days, er_robust, args.sl))

    # in/out-of-sample split (params were 'found' in-sample => second half is the honest test)
    print("\n" + "=" * 70)
    print("### IN-SAMPLE (first half of days) vs OUT-OF-SAMPLE (second half, frozen)")
    h1, h2 = split_half(days)
    d1 = {k: days[k] for k in h1}; d2 = {k: days[k] for k in h2}
    print(f"  IS days {h1[0]}..{h1[-1]} ({len(h1)})   OOS days {h2[0]}..{h2[-1]} ({len(h2)})")
    for name, m in [("max_move", mm), ("ER 0.35/3", er_best), ("ER dirF 0.55/1", er_robust)]:
        p1, n1, c1 = pf_of(get_trades(d1, m, args.sl))
        p2, n2, c2 = pf_of(get_trades(d2, m, args.sl))
        print(f"  {name:18s} IS: PF={p1:.2f} net={n1:6.0f} (n={c1})   OOS: PF={p2:.2f} net={n2:6.0f} (n={c2})")


if __name__ == "__main__":
    main()
