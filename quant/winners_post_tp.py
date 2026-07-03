#!/usr/bin/env python3
"""Shared-foundation dataset for the 'post-TP runway' study.

For every WINNING TP exit of a strategy, measure how far price would have
continued in the favourable direction AFTER the TP was hit, until the RTH
close (16:00 America/New_York) of that same NY day — i.e. the Maximum
Favourable Excursion BEYOND the TP. Also record weekday and previous-NY-day
reference levels so downstream agents can test correlations.

Output CSV is the single source every analysis subagent reads.

Usage:
  python3 quant/winners_post_tp.py --pine F.pine --data NQ_continuous_1m.csv \
      --start 2024-03-13 --end 2026-03-13 --out quant/winners_post_tp.csv
"""
import argparse, csv, os, sys
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pine_engine.engine import compile_pine, run_backtest
from pine_engine.data.loader import load_bars_csv

NY = ZoneInfo("America/New_York")
RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)
PREOPEN_START = time(9, 10)
PREOPEN_END = time(9, 29)


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pine", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--param", action="append", default=[])
    return ap.parse_args()


def load_raw_bars(path, start, end):
    """Read CSV bars in [start,end] (UTC date filter), return list of dicts with NY-localised time."""
    bars = []
    sd = datetime.fromisoformat(start).date() if start else None
    ed = datetime.fromisoformat(end).date() if end else None
    with open(path) as f:
        r = csv.DictReader(f)
        for row in r:
            ts = datetime.fromisoformat(row["datetime"])
            d = ts.date()
            if sd and d < sd:
                continue
            if ed and d > ed:
                continue
            ny = ts.astimezone(NY)
            bars.append({
                "ts": ts, "ny": ny, "ny_date": ny.date(), "ny_t": ny.time(),
                "o": float(row["open"]), "h": float(row["high"]),
                "l": float(row["low"]), "c": float(row["close"]),
            })
    bars.sort(key=lambda b: b["ts"])
    return bars


def build_day_index(bars):
    """ny_date -> list of bars (chronological); plus per-day reference levels."""
    by_day = {}
    for b in bars:
        by_day.setdefault(b["ny_date"], []).append(b)
    levels = {}
    for d, lst in by_day.items():
        rth = [b for b in lst if RTH_OPEN <= b["ny_t"] <= RTH_CLOSE]
        pre = [b for b in lst if PREOPEN_START <= b["ny_t"] <= PREOPEN_END]
        if not rth:
            continue
        hi = max(b["h"] for b in rth)
        lo = min(b["l"] for b in rth)
        cl = rth[-1]["c"]
        op = rth[0]["o"]
        lvl = {"rth_high": hi, "rth_low": lo, "rth_close": cl, "rth_open": op,
               "rth_mid": (hi + lo) / 2.0, "rth_range": hi - lo}
        if pre:
            ph = max(b["h"] for b in pre)
            pl = min(b["l"] for b in pre)
            lvl["preopen_high"] = ph
            lvl["preopen_low"] = pl
            lvl["preopen_mid"] = (ph + pl) / 2.0
        else:
            lvl["preopen_high"] = lvl["preopen_low"] = lvl["preopen_mid"] = None
        levels[d] = lvl
    return by_day, levels


def prev_day_map(levels):
    days = sorted(levels.keys())
    return {days[i]: days[i - 1] for i in range(1, len(days))}


def main():
    a = parse_args()
    c = compile_pine(a.pine)
    eng_bars = load_bars_csv(a.data, start_date=a.start, end_date=a.end)
    params = {}
    for p in a.param:
        k, v = p.split("=", 1)
        if v.lower() in ("true", "false"):
            v = v.lower() == "true"
        else:
            try:
                v = float(v) if ("." in v or v.lstrip("-").isdigit()) else v
            except Exception:
                pass
        params[k] = v
    trades = run_backtest(c, eng_bars, params or None)

    raw = load_raw_bars(a.data, a.start, a.end)
    by_day, levels = build_day_index(raw)
    prevmap = prev_day_map(levels)

    rows = []
    n_tp = 0
    for t in trades:
        if "TP" not in (t.exit_comment or ""):
            continue
        n_tp += 1
        side = t.side
        tp_price = t.exit_price
        entry = t.entry_price
        xt = t.exit_time
        if xt.tzinfo is None:
            xt = xt.replace(tzinfo=ZoneInfo("UTC"))
        xt_ny = xt.astimezone(NY)
        nyd = xt_ny.date()
        day_bars = by_day.get(nyd, [])
        # horizon bars: strictly after TP exit, up to RTH close 16:00 NY same day
        close_dt = datetime.combine(nyd, RTH_CLOSE, tzinfo=NY)
        fwd = [b for b in day_bars if b["ts"] > xt and b["ny"] <= close_dt]
        if fwd:
            if side == "long":
                peak = max(b["h"] for b in fwd)
                peak_b = max(fwd, key=lambda b: b["h"])
                trough = min(b["l"] for b in fwd)
                post_fav = peak - tp_price          # extra favourable pips beyond TP
                post_adv = tp_price - trough        # adverse pullback after TP
                eod = fwd[-1]["c"] - tp_price        # held-to-close beyond TP
            else:
                peak = min(b["l"] for b in fwd)
                peak_b = min(fwd, key=lambda b: b["l"])
                trough = max(b["h"] for b in fwd)
                post_fav = tp_price - peak
                post_adv = trough - tp_price
                eod = tp_price - fwd[-1]["c"]
            t2p = (peak_b["ts"] - xt).total_seconds() / 60.0
            peak_price = peak
        else:
            post_fav = post_adv = eod = 0.0
            t2p = 0.0
            peak_price = tp_price

        realized_tp = (tp_price - entry) if side == "long" else (entry - tp_price)

        pl = levels.get(prevmap.get(nyd))
        row = {
            "date": nyd.isoformat(),
            "weekday": nyd.strftime("%a"),
            "side": side,
            "entry_level": t.entry_comment,
            "tp_comment": (t.exit_comment or "").strip(),
            "entry": round(entry, 2),
            "tp_price": round(tp_price, 2),
            "tp_time_ny": xt_ny.strftime("%H:%M"),
            "realized_tp_pips": round(realized_tp, 2),
            "post_tp_max_pips": round(post_fav, 2),
            "post_tp_max_adverse_pips": round(post_adv, 2),
            "held_to_close_pips": round(eod, 2),
            "time_to_peak_min": round(t2p, 1),
            "peak_price": round(peak_price, 2),
        }
        if pl:
            for name in ("rth_high", "rth_low", "rth_close", "rth_mid", "rth_range",
                         "preopen_high", "preopen_low", "preopen_mid"):
                v = pl.get(name)
                row["prev_" + name] = round(v, 2) if v is not None else ""
            # signed distance of the post-TP PEAK to each prev-day level (peak - level)
            for name in ("rth_high", "rth_low", "rth_mid", "preopen_mid", "rth_close"):
                v = pl.get(name)
                row["dist_peak_to_prev_" + name] = round(peak_price - v, 2) if v is not None else ""
            # nearest prev-day level to the peak (abs)
            cands = [(nm, pl.get(nm)) for nm in ("rth_high", "rth_low", "rth_mid", "preopen_mid", "rth_close") if pl.get(nm) is not None]
            if cands:
                nm, vv = min(cands, key=lambda kv: abs(peak_price - kv[1]))
                row["nearest_prev_level"] = nm
                row["nearest_prev_level_dist"] = round(abs(peak_price - vv), 2)
        rows.append(row)

    # union of columns
    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print(f"trades total={len(trades)}  TP-winners={n_tp}  rows={len(rows)} -> {a.out}")
    # quick weekday sanity
    from collections import defaultdict
    agg = defaultdict(list)
    for r in rows:
        agg[r["weekday"]].append(r["post_tp_max_pips"])
    print("weekday | n | median post-TP pips | mean | max")
    order = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    for d in order:
        v = sorted(agg.get(d, []))
        if not v:
            continue
        med = v[len(v) // 2]
        print(f"  {d} | {len(v):3d} | {med:7.2f} | {sum(v)/len(v):7.2f} | {max(v):7.2f}")


if __name__ == "__main__":
    main()
