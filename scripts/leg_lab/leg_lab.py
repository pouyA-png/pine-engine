#!/usr/bin/env python3
"""
5m Leg-Variant Lab — pre-open-leg strategy, ALL FILTERS OFF, hold-to-17:00.

Tests N invented leg-detection methods. For each method it simulates the strategy
across the 4 fixed SL values and tracks every trade with full dimensions
(weekday, session-minute, level, side, half, outcome, RR).

Strategy mechanics (from spec.md):
  Leg -> (startPrice, endPrice). Levels: price(L) = endPrice + L*(startPrice-endPrice).
  Entries (limit @ 09:30): Short@1.78, Short@2.54, Long@-0.78, Long@-1.40.
  TP map:  Long -0.78 -> TP1 1.00 / TP2 2.54 ; Short 1.78 -> TP1 0.00 / TP2 -1.40
           Short 2.54 -> TP1 0.50 / TP2 -1.40 ; Long -1.40 -> TP1 0.50 / TP2 2.54
  SL fixed points (swept). 50/50 halves a(TP1)/b(TP2). After TP1 -> b SL to BE.
  ALL FILTERS OFF: every day, all valid levels long+short, both halves, no cancels,
  no max/day, unfilled+open close at 17:00 NY.

Assumptions (conservative): sell-limit valid only if level>open, buy-limit if level<open;
intrabar both SL&TP -> SL first; BE applies from bar AFTER TP1.
"""
import argparse, csv, json, math, sys
from collections import defaultdict
from datetime import datetime, time
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
DATA_DEFAULT = "/mnt/d/C-Transfer-2026-06-11/Claude-memories/HistoricalTradingData/NQ_continuous_5m.csv"
SL_GRID = [8.0, 12.5, 14.0, 16.0]

# level ratios used
LV = {"S178": 1.78, "S254": 2.54, "L078": -0.78, "L140": -1.40}
# TP1/TP2 ratios per entry
TPMAP = {
    "L078": (1.00, 2.54),
    "S178": (0.00, -1.40),
    "S254": (0.50, -1.40),
    "L140": (0.50, 2.54),
}
SIDE = {"S178": "short", "S254": "short", "L078": "long", "L140": "long"}

# ---------- data ----------
def load_days(path, start, end):
    """Return dict ny_date -> list of bars (each: dict o,h,l,c,v, nyt=time, dt)."""
    days = defaultdict(list)
    s = datetime.fromisoformat(start).date() if start else None
    e = datetime.fromisoformat(end).date() if end else None
    with open(path) as f:
        r = csv.reader(f)
        header = next(r)
        idx = {n.lower(): i for i, n in enumerate(header)}
        di, oi, hi, li, ci = idx["datetime"], idx["open"], idx["high"], idx["low"], idx["close"]
        vi = idx.get("volume")
        for row in r:
            ts = row[di]
            dt = datetime.fromisoformat(ts)            # tz-aware UTC
            nt = dt.astimezone(NY)
            d = nt.date()
            if s and d < s: continue
            if e and d > e: continue
            days[d].append({
                "o": float(row[oi]), "h": float(row[hi]), "l": float(row[li]),
                "c": float(row[ci]), "v": float(row[vi]) if vi is not None and row[vi] not in ("", "na") else 0.0,
                "t": nt.time(), "dt": nt,
            })
    return days

def split_day(bars):
    """Return (preopen_bars, session_bars). preopen: < 09:30. session: 09:30<=t<17:00."""
    pre, ses = [], []
    for b in bars:
        t = b["t"]
        if t < time(9, 30):
            pre.append(b)
        elif time(9, 30) <= t < time(17, 0):
            ses.append(b)
    return pre, ses

# ---------- leg methods (the 100 inventions) ----------
def _atr(bars):
    if len(bars) < 2: return max((b["h"]-b["l"]) for b in bars) if bars else 1.0
    trs = [bars[i]["h"]-bars[i]["l"] for i in range(len(bars))]
    return sum(trs)/len(trs) or 1.0

def leg(method, pre):
    """Return (startPrice, endPrice) or None. end candle = last pre-open bar (spec)."""
    fam = method["fam"]; p = method["p"]
    win = p.get("win", 12)
    w = pre[-win:] if len(pre) >= 2 else pre
    if len(w) < 2: return None
    end = w[-1]
    endPrice = end["c"]

    if fam == "fixed_n":
        n = min(p["n"], len(w)-1)
        return w[-1-n]["c"], endPrice

    if fam == "win_extreme":
        mode = p["mode"]
        if mode == "high":
            sb = max(w, key=lambda b: b["h"])
        elif mode == "low":
            sb = min(w, key=lambda b: b["l"])
        else:  # auto: extreme farthest from endPrice
            hi = max(w, key=lambda b: b["h"]); lo = min(w, key=lambda b: b["l"])
            sb = hi if abs(hi["h"]-endPrice) >= abs(lo["l"]-endPrice) else lo
        sp = sb["h"] if (mode == "high" or (mode == "auto" and sb is max(w, key=lambda b: b["h"]))) else sb["l"]
        return sb["c"], endPrice

    if fam == "pivot":
        k = p["k"]
        # last fractal pivot (high or low) in interior of window
        cand = None
        for i in range(len(w)-1-k, k-1, -1):
            seg = w[i-k:i+k+1]
            if w[i]["h"] == max(b["h"] for b in seg) or w[i]["l"] == min(b["l"] for b in seg):
                cand = w[i]; break
        if cand is None: cand = w[0]
        return cand["c"], endPrice

    if fam == "biggest_bar":
        sb = max(w[:-1], key=lambda b: b["h"]-b["l"]) if len(w) > 1 else w[0]
        anchor = sb["o"] if p.get("anchor") == "open" else sb["c"]
        return anchor, endPrice

    if fam == "max_move":
        best = None; bd = -1
        for b in w[:-1]:
            d = abs(endPrice - b["c"])
            if d > bd: bd = d; best = b
        return best["c"], endPrice

    if fam == "efficiency_ratio":
        # Faithful port of the Kaufman ER backward walk in
        # trading_bot_5m_visualleg.pine. END = close of last pre-open bar (= w[-1]).
        # Walk one bar back at a time over the window; keep extending while the
        # segment stays clean (ER >= minER) and holds the seed direction; lock on
        # the first cleanliness-drop / flip -> most-recent contiguous clean leg.
        # w[-1].c == Pine close[1]; w[-k].c == Pine close[k]; win == i_legBars.
        minER = p.get("minER", 0.55)
        minLegBars = p.get("minLegBars", 2)
        dirLast = p.get("dirLast", True)
        minRange = p.get("minRange", 5.0)
        fb = p.get("fallback", False)
        n = len(w)
        # direction seed
        if dirLast:
            _dir = 1 if w[-1]["c"] >= w[-2]["c"] else -1
        else:
            big = 0.0; _dir = 1
            for k in range(2, win + 1):
                if k > n - 1: break
                s = w[-(k - 1)]["c"] - w[-k]["c"]
                if abs(s) > big: big = abs(s); _dir = 1 if s >= 0 else -1
        sumAbs = 0.0; bestStart = endPrice; bestLen = 0; bestER = 0.0; locked = False
        for k in range(2, win + 1):
            if k > n - 1: break            # w[-k] / Pine close[k] out of window
            step = w[-(k - 1)]["c"] - w[-k]["c"]
            sumAbs += abs(step)
            net = w[-1]["c"] - w[-k]["c"]
            er = abs(net) / sumAbs if sumAbs > 0 else 0.0
            dirOk = (_dir == 1 and net > 0) or (_dir == -1 and net < 0)
            if not locked:
                if dirOk and er >= minER:
                    bestStart = w[-k]["c"]; bestLen = k - 1; bestER = er
                else:
                    locked = True
        legOk = (bestLen >= minLegBars) and (abs(bestStart - endPrice) >= minRange) and (bestER >= minER)
        if legOk:
            return bestStart, endPrice
        if fb:                              # graceful degrade to deterministic max_move
            best = None; bd = -1
            for b in w[:-1]:
                d = abs(endPrice - b["c"])
                if d > bd: bd = d; best = b
            return best["c"], endPrice
        return None                         # stand aside (no clean leg today)

    if fam == "run":
        tol = p.get("tol", 1)
        dirn = 1 if endPrice >= w[-2]["c"] else -1
        i = len(w)-2; counter = 0; start = w[-2]
        while i >= 0:
            step = w[i]["c"] - (w[i-1]["c"] if i-1 >= 0 else w[i]["o"])
            if (step >= 0 and dirn > 0) or (step <= 0 and dirn < 0):
                start = w[i]; i -= 1
            else:
                counter += 1
                if counter > tol: break
                i -= 1
        return start["c"], endPrice

    if fam == "atr_walk":
        kf = p["k"]; atr = _atr(w)
        i = len(w)-2; start = w[-2]
        while i >= 1 and abs(w[i]["c"]-w[i-1]["c"]) > kf*atr:
            start = w[i-1]; i -= 1
        return start["c"], endPrice

    if fam == "regression":
        n = len(w); xs = list(range(n)); ys = [b["c"] for b in w]
        mx = sum(xs)/n; my = sum(ys)/n
        den = sum((x-mx)**2 for x in xs) or 1.0
        slope = sum((xs[i]-mx)*(ys[i]-my) for i in range(n))/den
        inter = my - slope*mx
        return inter + slope*0, inter + slope*(n-1)  # predicted start/end

    if fam == "wick":
        # anchor leg-start to the pre-open WICK extreme farthest from endP
        hi = max(w, key=lambda b: b["h"]); lo = min(w, key=lambda b: b["l"])
        sp = hi["h"] if abs(hi["h"] - endPrice) >= abs(lo["l"] - endPrice) else lo["l"]
        return sp, endPrice

    if fam == "volume_origin":
        sb = max(w[:-1], key=lambda b: b["v"]) if len(w) > 1 else w[0]
        return sb["c"], endPrice

    if fam == "velocity":
        best = None; bd = -1
        for i in range(1, len(w)):
            d = abs(w[i]["c"]-w[i-1]["c"])
            if d > bd: bd = d; best = w[i-1]
        return (best or w[0])["c"], endPrice

    return None

def build_methods():
    M = []
    wins = [3, 4, 6, 9, 12, 18, 24]            # 15..120 min on 5m
    # fixed_n
    for win in wins:
        for n in [1, 2, 3]:
            if n < win:
                M.append({"fam": "fixed_n", "p": {"win": win, "n": n}})
    # win_extreme
    for win in wins:
        for mode in ["high", "low", "auto"]:
            M.append({"fam": "win_extreme", "p": {"win": win, "mode": mode}})
    # pivot
    for win in [6, 9, 12, 18, 24]:
        for k in [1, 2, 3]:
            M.append({"fam": "pivot", "p": {"win": win, "k": k}})
    # biggest_bar
    for win in wins:
        for anchor in ["open", "close"]:
            M.append({"fam": "biggest_bar", "p": {"win": win, "anchor": anchor}})
    # max_move
    for win in wins:
        M.append({"fam": "max_move", "p": {"win": win}})
    # run
    for win in [4, 6, 9, 12, 18, 24]:
        for tol in [0, 1, 2]:
            M.append({"fam": "run", "p": {"win": win, "tol": tol}})
    # atr_walk
    for win in [6, 9, 12, 18, 24]:
        for k in [0.3, 0.5, 0.8]:
            M.append({"fam": "atr_walk", "p": {"win": win, "k": k}})
    # regression
    for win in wins:
        M.append({"fam": "regression", "p": {"win": win}})
    # volume_origin
    for win in wins:
        M.append({"fam": "volume_origin", "p": {"win": win}})
    # velocity
    for win in wins:
        M.append({"fam": "velocity", "p": {"win": win}})
    # name + id, fix to exactly 100
    for i, m in enumerate(M):
        m["id"] = i
        m["name"] = m["fam"] + "_" + "_".join(f"{k}{v}" for k, v in m["p"].items())
    if len(M) > 100:
        M = M[:100]
    while len(M) < 100:  # pad with extra fixed_n big windows
        win = 24; n = (len(M) % 20) + 1
        m = {"fam": "fixed_n", "p": {"win": win, "n": n}, "id": len(M)}
        m["name"] = f"fixed_n_pad{len(M)}"
        M.append(m)
    for i, m in enumerate(M): m["id"] = i
    return M

# ---------- simulation ----------
def sim_entry(level_name, entry_px, sl_px_dist, prices, ses, fill_i):
    """Simulate one entry (both halves) from fill bar index onward. Returns list of trade dicts."""
    side = SIDE[level_name]
    tp1r, tp2r = TPMAP[level_name]
    tp1 = prices[_lvlkey(tp1r)]; tp2 = prices[_lvlkey(tp2r)]
    if side == "long":
        sl = entry_px - sl_px_dist
    else:
        sl = entry_px + sl_px_dist
    out = []
    a_done = b_done = False
    tp1_hit = False
    b_sl = sl
    for j in range(fill_i, len(ses)):
        bar = ses[j]
        hi, lo = bar["h"], bar["l"]
        # half a (target TP1) — SL first (conservative)
        if not a_done:
            if side == "long":
                if lo <= sl:
                    out.append(_mk(level_name, "a", side, entry_px, sl, sl_px_dist, "SL")); a_done = True
                elif hi >= tp1:
                    out.append(_mk(level_name, "a", side, entry_px, tp1, sl_px_dist, "TP1")); a_done = True; tp1_hit = True
            else:
                if hi >= sl:
                    out.append(_mk(level_name, "a", side, entry_px, sl, sl_px_dist, "SL")); a_done = True
                elif lo <= tp1:
                    out.append(_mk(level_name, "a", side, entry_px, tp1, sl_px_dist, "TP1")); a_done = True; tp1_hit = True
        # half b (target TP2) — SL/BE first
        if not b_done:
            if side == "long":
                if lo <= b_sl:
                    oc = "BE" if b_sl == entry_px else "SL"
                    out.append(_mk(level_name, "b", side, entry_px, b_sl, sl_px_dist, oc)); b_done = True
                elif hi >= tp2:
                    out.append(_mk(level_name, "b", side, entry_px, tp2, sl_px_dist, "TP2")); b_done = True
            else:
                if hi >= b_sl:
                    oc = "BE" if b_sl == entry_px else "SL"
                    out.append(_mk(level_name, "b", side, entry_px, b_sl, sl_px_dist, oc)); b_done = True
                elif lo <= tp2:
                    out.append(_mk(level_name, "b", side, entry_px, tp2, sl_px_dist, "TP2")); b_done = True
        # BE move applies from NEXT bar after TP1
        if tp1_hit and not b_done:
            b_sl = entry_px
        if a_done and b_done:
            break
    # EOD close remaining at last session close
    eod = ses[-1]["c"]
    if not a_done:
        out.append(_mk(level_name, "a", side, entry_px, eod, sl_px_dist, "EOD"))
    if not b_done:
        out.append(_mk(level_name, "b", side, entry_px, eod, sl_px_dist, "EOD"))
    return out

def _lvlkey(ratio):
    return ratio  # prices keyed by ratio float

def _mk(level_name, half, side, entry, exit_px, sld, outcome):
    pnl = (exit_px - entry) if side == "long" else (entry - exit_px)
    return {"level": level_name, "half": half, "side": side, "entry": entry,
            "exit": exit_px, "sl_dist": sld, "outcome": outcome, "pnl": pnl,
            "rr": pnl / sld if sld else 0.0}

def run_method(method, days, sl_grid):
    """Return per-sl list of trade records (with day/time dims)."""
    results = {sl: [] for sl in sl_grid}
    needed_ratios = sorted(set(list(LV.values()) + [r for pair in TPMAP.values() for r in pair] + [0.0, 0.5, 1.0]))
    for d in sorted(days):
        bars = days[d]
        pre, ses = split_day(bars)
        if len(pre) < 2 or len(ses) < 2:
            continue
        lg = leg(method, pre)
        if lg is None:
            continue
        startP, endP = lg
        if startP == endP:
            continue
        prices = {r: endP + r * (startP - endP) for r in needed_ratios}
        O = ses[0]["o"]
        weekday = d.weekday()
        # determine valid entries and their fill bar/price
        for lname, ratio in LV.items():
            lvl = prices[ratio]
            side = SIDE[lname]
            if side == "short" and not (lvl > O):   # sell-limit must be above open
                continue
            if side == "long" and not (lvl < O):     # buy-limit must be below open
                continue
            # find fill bar
            fill_i = None
            for j, bar in enumerate(ses):
                if side == "short" and bar["h"] >= lvl:
                    fill_i = j; break
                if side == "long" and bar["l"] <= lvl:
                    fill_i = j; break
            if fill_i is None:
                continue
            fill_bar = ses[fill_i]
            smin = (fill_bar["t"].hour - 9) * 60 + (fill_bar["t"].minute - 30)
            for sl in sl_grid:
                trades = sim_entry(lname, lvl, sl, prices, ses, fill_i)
                for t in trades:
                    t.update({"date": d.isoformat(), "weekday": weekday,
                              "session_min": smin, "entry_time": fill_bar["t"].strftime("%H:%M")})
                    results[sl].append(t)
    return results

# ---------- stats ----------
def stats(trades):
    if not trades:
        return {"trades": 0}
    ps = [t["pnl"] for t in trades]
    wins = [p for p in ps if p > 0]; losses = [p for p in ps if p <= 0]
    gp = sum(wins); gl = abs(sum(losses))
    net = gp - gl
    # max drawdown over time-ordered cum pnl
    ordered = sorted(trades, key=lambda t: (t["date"], t["session_min"], t["half"]))
    eq = peak = mdd = 0.0
    for t in ordered:
        eq += t["pnl"]; peak = max(peak, eq); mdd = max(mdd, peak - eq)
    rrs = [t["rr"] for t in trades]
    # daily sharpe annualized
    daily = defaultdict(float)
    for t in trades: daily[t["date"]] += t["pnl"]
    dv = list(daily.values())
    if len(dv) > 1:
        mu = sum(dv)/len(dv); sd = (sum((x-mu)**2 for x in dv)/(len(dv)-1))**0.5
        sharpe = mu/sd*math.sqrt(252) if sd else 0.0
    else:
        sharpe = 0.0
    return {
        "trades": len(trades), "wins": len(wins), "wr": len(wins)/len(trades)*100,
        "pf": (gp/gl) if gl else float("inf"), "net": net, "gp": gp, "gl": gl,
        "avg_rr": sum(rrs)/len(rrs), "expectancy": net/len(trades),
        "max_dd": mdd, "dd_to_net": (mdd/net) if net > 0 else None,
        "sharpe": sharpe, "pos_days": sum(1 for x in dv if x > 0), "days": len(dv),
    }

def breakdown(trades, key):
    out = {}
    grp = defaultdict(list)
    for t in trades: grp[t[key]].append(t)
    for k, ts in grp.items():
        ps = [x["pnl"] for x in ts]; w = [p for p in ps if p > 0]
        out[k] = {"n": len(ts), "wr": len(w)/len(ts)*100,
                  "net": sum(ps), "avg_rr": sum(x["rr"] for x in ts)/len(ts)}
    return out

WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DATA_DEFAULT)
    ap.add_argument("--start", default="2025-03-13")
    ap.add_argument("--end", default="2026-03-13")
    ap.add_argument("--method", type=int, default=None, help="single method id")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", action="store_true", help="emit compact json summary")
    args = ap.parse_args()

    methods = build_methods()
    assert len(methods) == 100, len(methods)
    if args.list:
        for m in methods: print(m["id"], m["name"])
        return

    days = load_days(args.data, args.start, args.end)

    def summarize(m):
        res = run_method(m, days, SL_GRID)
        per_sl = {sl: stats(res[sl]) for sl in SL_GRID}
        # best sl by pf (min 30 trades)
        valid = {sl: s for sl, s in per_sl.items() if s.get("trades", 0) >= 30}
        best_sl = max(valid, key=lambda sl: valid[sl]["pf"]) if valid else None
        base = res[12.5]
        rec = {"id": m["id"], "name": m["name"], "fam": m["fam"],
               "per_sl": {str(sl): per_sl[sl] for sl in SL_GRID},
               "best_sl": best_sl,
               "by_weekday": {WD[k]: v for k, v in breakdown(base, "weekday").items()},
               "by_level": breakdown(base, "level"),
               "by_session_min": breakdown(base, "session_min"),
               }
        return rec

    if args.method is not None:
        rec = summarize(methods[args.method])
        print(json.dumps(rec, default=str))
        return

    if args.all:
        allrecs = [summarize(m) for m in methods]
        print(json.dumps(allrecs, default=str))
        return

    ap.error("specify --method N, --all, or --list")

if __name__ == "__main__":
    main()
