#!/usr/bin/env python3
"""Monte-Carlo robustness on a trade list (from export_trades.py).
Order-shuffle (maxDD/streak dist), bootstrap resample (net/PF/CI, P(loss)),
cost/slippage randomization. Pure stdlib + seeded PRNG (deterministic).
Usage: python3 quant/mc.py --trades T.csv [--point_value 1 --capital 100000 --runs 5000 --seed 7 --max_cost 2.5]
"""
import argparse, csv, json, math, random
from datetime import datetime


def load_ppc_qty(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rows.append((float(r["pnl_pts_per_contract"]), float(r["qty"])))
    return rows


def pf(pnls):
    gp = sum(p for p in pnls if p > 0); gl = abs(sum(p for p in pnls if p <= 0))
    return gp / gl if gl else float("inf")


def maxdd(pnls, capital):
    eq = peak = capital; mdd = 0.0
    for p in pnls:
        eq += p; peak = max(peak, eq); mdd = max(mdd, peak - eq)
    return mdd


def pct(xs, q):
    s = sorted(xs); i = min(len(s) - 1, max(0, int(q * len(s))))
    return s[i]


def run(rows, point_value=1.0, capital=100000.0, runs=5000, seed=7, max_cost=2.5, ruin_dd=0.10):
    rng = random.Random(seed)
    base = [(ppc) * q * point_value for ppc, q in rows]
    n = len(base)
    # 1) order shuffle -> maxDD / streak distribution (net & PF invariant)
    dds = []
    for _ in range(runs):
        s = base[:]; rng.shuffle(s); dds.append(maxdd(s, capital))
    # 2) bootstrap resample with replacement -> net / PF / P(loss)
    nets, pfs, bdds = [], [], []
    for _ in range(runs):
        samp = [base[rng.randrange(n)] for _ in range(n)]
        nets.append(sum(samp)); pfs.append(pf(samp)); bdds.append(maxdd(samp, capital))
    p_loss = sum(1 for x in nets if x <= 0) / runs
    ruin = sum(1 for d in bdds if d >= ruin_dd * capital) / runs
    # 3) cost/slippage randomization U[0,max_cost] pts per contract round-trip
    cnets, cpfs = [], []
    for _ in range(runs):
        s = [(ppc - rng.uniform(0, max_cost)) * q * point_value for ppc, q in rows]
        cnets.append(sum(s)); cpfs.append(pf(s))
    return {
        "trades": n, "runs": runs, "point_value": point_value,
        "order_shuffle_maxDD_$": {"median": round(pct(dds, .5)), "p95": round(pct(dds, .95)), "p99": round(pct(dds, .99)), "worst": round(max(dds))},
        "bootstrap_net_$": {"p5": round(pct(nets, .05)), "median": round(pct(nets, .5)), "p95": round(pct(nets, .95))},
        "bootstrap_pf": {"p5": round(pct(pfs, .05), 2), "median": round(pct(pfs, .5), 2), "p95": round(pct(pfs, .95), 2)},
        "P(net<=0)": round(p_loss, 4),
        "risk_of_ruin(dd>=%d%%)" % int(ruin_dd * 100): round(ruin, 4),
        "cost_rand_U0_%.1f_net_$" % max_cost: {"p5": round(pct(cnets, .05)), "median": round(pct(cnets, .5))},
        "cost_rand_pf": {"p5": round(pct(cpfs, .05), 2), "median": round(pct(cpfs, .5), 2)},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades", required=True)
    ap.add_argument("--point_value", type=float, default=1.0)
    ap.add_argument("--capital", type=float, default=100000.0)
    ap.add_argument("--runs", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--max_cost", type=float, default=2.5)
    a = ap.parse_args()
    print(json.dumps(run(load_ppc_qty(a.trades), a.point_value, a.capital, a.runs, a.seed, a.max_cost), indent=2))


if __name__ == "__main__":
    main()
