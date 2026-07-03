#!/usr/bin/env python3
"""Quant metric library — consumes a trades CSV (from export_trades.py) and computes
the full professional metric set. Point-based PnL; pass --point_value & --capital for $.
A cost (points/contract/round-trip) can be charged to stress execution realism.
Usage: python3 quant/metrics.py --trades T.csv [--point_value 20 --capital 100000 --cost_pts 0]
Importable: load_trades(), compute(trades, ...)
"""
import argparse, csv, json, math
from collections import defaultdict
from datetime import datetime


def load_trades(path):
    out = []
    with open(path) as f:
        for r in csv.DictReader(f):
            out.append({
                "entry_time": datetime.fromisoformat(r["entry_time"]),
                "exit_time": datetime.fromisoformat(r["exit_time"]),
                "side": r["side"], "qty": float(r["qty"]),
                "ppc": float(r["pnl_pts_per_contract"]),
                "exit_comment": r.get("exit_comment", ""),
            })
    return out


def _streaks(signs):
    mx_loss = cur = 0
    for s in signs:
        if s <= 0:
            cur += 1; mx_loss = max(mx_loss, cur)
        else:
            cur = 0
    return mx_loss


def compute(trades, point_value=20.0, capital=100000.0, cost_pts=0.0):
    if not trades:
        return {"trades": 0}
    # $ pnl per trade with cost charged per contract round-trip
    pnls = [(t["ppc"] - cost_pts) * t["qty"] * point_value for t in trades]
    n = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gp, gl = sum(wins), abs(sum(losses))
    net = sum(pnls)
    # equity / drawdown
    eq = capital; peak = capital; mdd = 0.0; curve = []
    for p in pnls:
        eq += p; curve.append(eq); peak = max(peak, eq); mdd = max(mdd, peak - eq)
    mdd_pct = mdd / peak * 100 if peak else 0.0
    # daily aggregation for ratios
    daily = defaultdict(float)
    for t, p in zip(trades, pnls):
        daily[t["exit_time"].date()] += p
    dv = list(daily.values())
    span_days = (trades[-1]["exit_time"].date() - trades[0]["entry_time"].date()).days or 1
    years = span_days / 365.25
    # returns relative to capital
    drets = [d / capital for d in dv]
    mu = sum(drets) / len(drets) if drets else 0.0
    sd = (sum((x - mu) ** 2 for x in drets) / (len(drets) - 1)) ** 0.5 if len(drets) > 1 else 0.0
    downside = [x for x in drets if x < 0]
    dsd = (sum(x * x for x in downside) / len(downside)) ** 0.5 if downside else 0.0
    sharpe = (mu / sd * math.sqrt(252)) if sd else 0.0
    sortino = (mu / dsd * math.sqrt(252)) if dsd else 0.0
    cagr = ((capital + net) / capital) ** (1 / years) - 1 if years > 0 and (capital + net) > 0 else float("nan")
    calmar = (cagr * 100) / mdd_pct if mdd_pct else float("nan")
    # VaR / ES on per-trade $ (historical, 95%)
    sp = sorted(pnls)
    k = max(0, int(0.05 * n) - 1)
    var95 = sp[k]
    es95 = sum(sp[:k + 1]) / (k + 1)
    # monthly
    monthly = defaultdict(float)
    for t, p in zip(trades, pnls):
        monthly[t["exit_time"].strftime("%Y-%m")] += p
    mvals = list(monthly.values())
    return {
        "trades": n, "years": round(years, 2), "span_days": span_days,
        "net_$": round(net, 0), "gross_profit": round(gp, 0), "gross_loss": round(gl, 0),
        "pf": round(gp / gl, 3) if gl else float("inf"),
        "wr_%": round(len(wins) / n * 100, 1),
        "avg_win_$": round(sum(wins) / len(wins), 1) if wins else 0.0,
        "avg_loss_$": round(sum(losses) / len(losses), 1) if losses else 0.0,
        "payoff": round((sum(wins) / len(wins)) / abs(sum(losses) / len(losses)), 2) if wins and losses else float("nan"),
        "expectancy_$": round(net / n, 1),
        "max_dd_$": round(mdd, 0), "max_dd_%": round(mdd_pct, 2),
        "max_losing_streak": _streaks(pnls),
        "cagr_%": round(cagr * 100, 2) if cagr == cagr else None,
        "sharpe": round(sharpe, 2), "sortino": round(sortino, 2),
        "calmar": round(calmar, 2) if calmar == calmar else None,
        "var95_$": round(var95, 0), "es95_$": round(es95, 0),
        "trades_per_year": round(n / years, 1) if years > 0 else None,
        "months": len(mvals), "pos_months": sum(1 for x in mvals if x > 0),
        "best_month_$": round(max(mvals), 0) if mvals else 0, "worst_month_$": round(min(mvals), 0) if mvals else 0,
        "cost_pts": cost_pts,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades", required=True)
    ap.add_argument("--point_value", type=float, default=20.0)
    ap.add_argument("--capital", type=float, default=100000.0)
    ap.add_argument("--cost_pts", type=float, default=0.0)
    ap.add_argument("--start", default=None, help="YYYY-MM-DD inclusive (by entry_time)")
    ap.add_argument("--end", default=None, help="YYYY-MM-DD inclusive")
    args = ap.parse_args()
    tr = load_trades(args.trades)
    if args.start:
        s = datetime.fromisoformat(args.start).date(); tr = [t for t in tr if t["entry_time"].date() >= s]
    if args.end:
        e = datetime.fromisoformat(args.end).date(); tr = [t for t in tr if t["entry_time"].date() <= e]
    m = compute(tr, args.point_value, args.capital, args.cost_pts)
    print(json.dumps(m, indent=2))


if __name__ == "__main__":
    main()
