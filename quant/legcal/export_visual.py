#!/usr/bin/env python3
"""Build the interactive visual leg-labeler with a 1m/5m timeframe toggle.
Both timeframes come from the FTMO feed. Days = where BOTH 1m and 5m exist
(the last ~74 days). Each day embeds candles + detected pre-open leg candidates
for BOTH timeframes; the app toggles between them.
"""
import argparse, csv, json, os, sys
from datetime import datetime, time
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import leg_candidates as L

NY = ZoneInfo("America/New_York")
BERLIN = ZoneInfo("Europe/Berlin")          # display timezone (Pouyas Uhr)
OPEN_T = time(9, 30)


def load_disp(path, dstart, dend):
    """Display window filtered by BERLIN time [dstart,dend] (e.g. 14:00-17:00);
    bar['t'] stays NY (for pre-open leg detection), bar['tmin'] is Berlin minutes (x-axis)."""
    days = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            ts = datetime.fromisoformat(row["datetime"])     # UTC-aware
            ny = ts.astimezone(NY)
            be = ts.astimezone(BERLIN)
            if not (dstart <= be.time() <= dend):
                continue
            days.setdefault(ny.date(), []).append({
                "ts": ts, "t": ny.time(), "tmin": be.hour * 60 + be.minute,
                "o": float(row["open"]), "h": float(row["high"]),
                "l": float(row["low"]), "c": float(row["close"]), "v": float(row.get("volume", 0) or 0)})
    for d in days:
        days[d].sort(key=lambda b: b["ts"])
    return days


def build_tf(bars, lbs, min_abs, min_pct, ls, le, prev):
    cs = L.candidates_for_day(bars, lbs, min_abs, min_pct, le, prev, anchor_win=(ls, le))
    cs = [c for c in cs if bars[c["i0"]]["t"] >= ls and bars[c["i1"]]["t"] < le and bars[c["i0"]]["t"] < le]
    cs = sorted(cs, key=lambda x: x["_pt"])
    open_idx = next((i for i, b in enumerate(bars) if b["t"] >= OPEN_T), -1)
    return {
        "open_idx": open_idx,
        "tmin": [b["tmin"] for b in bars],
        "bars": [[round(b["o"], 2), round(b["h"], 2), round(b["l"], 2), round(b["c"], 2)] for b in bars],
        "cands": [{
            "i0": c["i0"], "i1": c["i1"], "dir": c["direction"], "start": c["start_price"],
            "pivot": c["pivot_price"], "size": c["leg_size"], "clean": c["clean"], "eff": c["efficiency"],
            "disp": c["displacement"], "sweep": c["sweep"] == "J", "wick": c["wick"] == "J",
            "distlvl": (c["dist_level"] if c["dist_level"] != "" else None), "round": c["round_dist"],
            "minopen": c["min_before_open"],
        } for c in cs],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data1m", required=True)
    ap.add_argument("--data5m", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--last-n", type=int, default=80)
    ap.add_argument("--min-abs", type=float, default=20.0)
    ap.add_argument("--min-pct", type=float, default=0.10)
    ap.add_argument("--disp-start", default="06:00")   # BERLIN time — ganzer Handelstag (NY 00:00 -> US-Close)
    ap.add_argument("--disp-end", default="23:00")
    ap.add_argument("--leg-start", default="08:00")
    ap.add_argument("--leg-end", default="09:30")
    a = ap.parse_args()

    ds, de = L.hhmm(a.disp_start), L.hhmm(a.disp_end)
    ls, le = L.hhmm(a.leg_start), L.hhmm(a.leg_end)
    d1 = load_disp(a.data1m, ds, de)
    d5 = load_disp(a.data5m, ds, de)
    prev = L.load_prev_rth_levels(a.data1m)
    # days where BOTH timeframes have pre-open bars
    def has_pre(bars):
        return any(ls <= b["t"] < le for b in bars)
    common = sorted(d for d in (set(d1) & set(d5)) if has_pre(d1[d]) and has_pre(d5[d]))
    common = common[-a.last_n:]

    out_days = []
    for d in common:
        tf1 = build_tf(d1[d], [3, 5], a.min_abs, a.min_pct, ls, le, prev.get(d))
        tf5 = build_tf(d5[d], [2, 3], a.min_abs, a.min_pct, ls, le, prev.get(d))
        out_days.append({"date": d.isoformat(), "tf": {"1m": tf1, "5m": tf5}})

    tmpl = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "visual_template.html"), encoding="utf-8").read()
    html = tmpl.replace("__DATA__", json.dumps(out_days, separators=(",", ":")))
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(html)
    c1 = sum(len(x["tf"]["1m"]["cands"]) for x in out_days)
    c5 = sum(len(x["tf"]["5m"]["cands"]) for x in out_days)
    print(f"days={len(out_days)} 1m-cands={c1} 5m-cands={c5} -> {a.out} ({len(html)//1024} KB)")


if __name__ == "__main__":
    main()
