#!/usr/bin/env python3
"""Per-day analysis on the REAL FTMO 5m feed for the trader/viewer fan-out.

Detected leg = max_move_win6 (the sweep winner). For each day it reports the
detected leg/levels/outcome (SL16) AND solves the IDEAL leg: the leg-start anchor
that would place an entry level exactly on the session reversal extreme (perfect
top/bottom tick) and turn the day into a win — plus whether that ideal anchor
coincides with a recognisable pre-open feature (learnable).

Usage:
  python day_lab.py --rank                 # build ranked day list (losers first) -> days_ranked.json
  python day_lab.py --day N --role trader  # emit day N (trader view) as JSON
  python day_lab.py --day N --role viewer  # emit day N (viewer/ideal-leg view) as JSON
"""
import argparse, json, sys
from leg_lab import load_days, split_day, leg, LV, TPMAP, SIDE, sim_entry, build_methods

DATA = "/mnt/c/Users/nader/US100_M5_FTMO_utc.csv"
START, END = "2025-05-01", "2026-06-17"
SL = 16.0
METHOD = next(m for m in build_methods() if m["name"] == "max_move_win6")
RANKFILE = "/home/pouya/pine-engine/scripts/leg_lab/days_ranked.json"

def day_levels(pre):
    lg = leg(METHOD, pre)
    if lg is None: return None
    startP, endP = lg
    if startP == endP: return None
    rng = startP - endP
    prices = {n: endP + r * rng for n, r in LV.items()}
    tp = {}
    for n in LV:
        t1, t2 = TPMAP[n]
        tp[n] = (endP + t1 * rng, endP + t2 * rng)
    return startP, endP, prices, tp

def simulate_day(pre, ses):
    """Return (net, trades) for detected leg at SL16, all filters OFF (every level)."""
    dl = day_levels(pre)
    if dl is None: return 0.0, [], None
    startP, endP, prices, tp = dl
    O = ses[0]["o"]
    needed = {}
    trades = []
    for lname, lvl in prices.items():
        side = SIDE[lname]
        if side == "short" and not lvl > O: continue
        if side == "long" and not lvl < O: continue
        fill_i = None
        for j, b in enumerate(ses):
            if side == "short" and b["h"] >= lvl: fill_i = j; break
            if side == "long" and b["l"] <= lvl: fill_i = j; break
        if fill_i is None: continue
        # need prices keyed by ratio for sim_entry
        allr = sorted(set([0.0,0.5,1.0,2.54,-1.40,1.78,-0.78]))
        pr = {r: endP + r*(startP-endP) for r in allr}
        for t in sim_entry(lname, lvl, SL, pr, ses, fill_i):
            trades.append(t)
    net = sum(t["pnl"] for t in trades)
    return net, trades, (startP, endP, prices, tp)

def session_extremes(ses):
    hi = max(ses, key=lambda b: b["h"]); lo = min(ses, key=lambda b: b["l"])
    return {"high": hi["h"], "high_time": hi["t"].strftime("%H:%M"),
            "low": lo["l"], "low_time": lo["t"].strftime("%H:%M"),
            "open": ses[0]["o"], "close": ses[-1]["c"]}

def ideal_leg(pre, ses, detected):
    """For each level, the startP that puts it exactly on the day's reversal extreme,
    the delta vs detected startP, and the nearest pre-open feature that matches."""
    startP, endP, prices, tp = detected
    ext = session_extremes(ses)
    out = []
    targets = {"L078": ext["low"], "L140": ext["low"], "S178": ext["high"], "S254": ext["high"]}
    # pre-open features to test as "learnable anchors"
    feats = []
    for b in pre:
        feats.append((b["t"].strftime("%H:%M"), "high", b["h"]))
        feats.append((b["t"].strftime("%H:%M"), "low", b["l"]))
        feats.append((b["t"].strftime("%H:%M"), "close", b["c"]))
    for lname, L in LV.items():
        T = targets[lname]
        if L == 0: continue
        ideal_start = endP + (T - endP) / L            # so that endP+L*(start-endP)=T
        # nearest pre-open feature to ideal_start
        nf = min(feats, key=lambda f: abs(f[2] - ideal_start))
        out.append({
            "level": lname, "side": SIDE[lname], "target_tick": round(T, 2),
            "ideal_startP": round(ideal_start, 2),
            "detected_startP": round(startP, 2),
            "delta_vs_detected": round(ideal_start - startP, 2),
            "nearest_preopen_feature": {"time": nf[0], "type": nf[1], "price": round(nf[2], 2),
                                         "match_err": round(abs(nf[2] - ideal_start), 2)},
        })
    return ext, out

def build_day(d, bars):
    pre, ses = split_day(bars)
    if len(pre) < 2 or len(ses) < 5: return None
    net, trades, detected = simulate_day(pre, ses)
    if detected is None: return None
    startP, endP, prices, tp = detected
    rec = {
        "date": d.isoformat(), "weekday": ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][d.weekday()],
        "net": round(net, 2), "was_win": net > 0, "n_trades": len(trades),
        "detected_leg": {"startP": round(startP,2), "endP": round(endP,2),
                          "levels": {k: round(v,2) for k,v in prices.items()}},
        "trades": [{"level": t["level"], "side": t["side"], "outcome": t["outcome"],
                    "pnl": round(t["pnl"],2)} for t in trades],
    }
    ext, ideal = ideal_leg(pre, ses, detected)
    rec["session"] = {k: round(v,2) if isinstance(v,float) else v for k,v in ext.items()}
    rec["ideal_leg"] = ideal
    return rec

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rank", action="store_true")
    ap.add_argument("--day", type=int)
    ap.add_argument("--role", choices=["trader","viewer"], default="trader")
    ap.add_argument("--n", type=int, default=150)
    a = ap.parse_args()
    days = load_days(DATA, START, END)

    if a.rank:
        recs = []
        for d in sorted(days):
            r = build_day(d, days[d])
            if r: recs.append(r)
        recs.sort(key=lambda r: r["net"])          # losers first
        sel = recs[:a.n]
        json.dump([{"date": r["date"], "net": r["net"]} for r in sel], open(RANKFILE,"w"))
        print(f"ranked {len(recs)} days, selected worst {len(sel)} -> {RANKFILE}")
        print("worst 5:", [(r["date"], r["net"]) for r in sel[:5]])
        print("best of selected:", sel[-1]["date"], sel[-1]["net"])
        return

    ranked = json.load(open(RANKFILE))
    import datetime
    target = datetime.date.fromisoformat(ranked[a.day]["date"])
    rec = build_day(target, days[target])
    if a.role == "trader":
        rec.pop("ideal_leg", None)
    print(json.dumps(rec, default=str))

if __name__ == "__main__":
    main()
