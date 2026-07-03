#!/usr/bin/env python3
"""Build the leg-labeling dashboard with TWO selectable datasets:

  ftmo : last ~74 days, US100 (FTMO M1/M5 feed)            -> short, high-res
  cme  : last 5 years,  NQ continuous futures (M1/M5 feed) -> long history

Each dataset = list of days; each day embeds 1m+5m candles + detected pre-open
leg candidates for both timeframes (identical schema to export_visual.py).

The CME 1m source is ~227MB, so the loader STREAMS the file once and flushes a
day as soon as the NY date rolls over -> memory stays at one day, not the whole
5 years. Prev-day RTH levels are carried forward during the same pass.
"""
import argparse, json, os, sys
from datetime import datetime, time
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import leg_candidates as L

NY = ZoneInfo("America/New_York")
BERLIN = ZoneInfo("Europe/Berlin")
UTC = ZoneInfo("UTC")
OPEN_T = time(9, 30)
RTH_OPEN, RTH_CLOSE = time(9, 30), time(16, 0)


def tf_for_day(bars, lbs, min_abs, min_pct, ls, le, prev):
    """Same candidate/serialisation as export_visual.build_tf, for one day's bars."""
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


def build_tf_stream(path, lbs, min_abs, min_pct, ds, de, ls, le, cutoff):
    """Stream `path` once -> {ny_date: tf_obj}. cutoff = aware UTC datetime or None.
    Carries previous-day RTH (H,L,C) forward so no second pass is needed."""
    out = {}
    cur_date = None
    disp_bars = []                 # display-window bars for current NY day
    cur_hi, cur_lo, cur_cl, cur_rth_n = -1e18, 1e18, None, 0   # this day's RTH levels + bar count
    prev_lvls = None               # finished previous day's (H,L,C)

    def flush():
        nonlocal disp_bars
        if cur_date is not None and disp_bars:
            disp_bars.sort(key=lambda b: b["ts"])
            out[cur_date] = tf_for_day(disp_bars, lbs, min_abs, min_pct, ls, le, prev_lvls)
        disp_bars = []

    with open(path) as f:
        header = f.readline()      # skip header
        for line in f:
            c0 = line.find(",")
            if c0 < 0:
                continue
            ts = datetime.fromisoformat(line[:c0])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if cutoff is not None and ts < cutoff:
                continue
            ny = ts.astimezone(NY)
            d = ny.date()
            if d != cur_date:
                flush()
                if cur_date is not None and cur_cl is not None and cur_rth_n >= 20:   # nur echte RTH-Sessions als prev-Level (keine duennen Halb-/DST-Tage)
                    prev_lvls = (cur_hi, cur_lo, cur_cl)
                cur_date = d
                cur_hi, cur_lo, cur_cl, cur_rth_n = -1e18, 1e18, None, 0
            parts = line.rstrip("\n").split(",")
            o, h, l, cl = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
            nt = ny.time()
            if RTH_OPEN <= nt <= RTH_CLOSE:
                cur_hi = max(cur_hi, h); cur_lo = min(cur_lo, l); cur_cl = cl; cur_rth_n += 1
            be = ts.astimezone(BERLIN)
            if ds <= be.time() <= de:
                disp_bars.append({"ts": ts, "t": nt, "tmin": be.hour * 60 + be.minute,
                                  "o": o, "h": h, "l": l, "c": cl})
    flush()
    return out


def build_dataset(f1m, f5m, lb1, lb5, min_abs, min_pct, ds, de, ls, le, cutoff, last_n, min_bars=200):
    d1 = build_tf_stream(f1m, lb1, min_abs, min_pct, ds, de, ls, le, cutoff)
    d5 = build_tf_stream(f5m, lb5, min_abs, min_pct, ds, de, ls, le, cutoff)

    # a day qualifies only if BOTH timeframes are real trading days: a full bar
    # count (drops DST-transition Sundays etc. that leave 1 stray bar -> giant
    # single-candle artifact) AND the 09:30 NY open bar exists.
    common = sorted(d for d in (set(d1) & set(d5))
                    if len(d1[d]["bars"]) >= min_bars and len(d5[d]["bars"]) >= min_bars // 5
                    and d1[d]["open_idx"] >= 0 and d5[d]["open_idx"] >= 0)
    if last_n:
        common = common[-last_n:]
    return [{"date": d.isoformat(), "tf": {"1m": d1[d], "5m": d5[d]}} for d in common]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ftmo-1m", required=True)
    ap.add_argument("--ftmo-5m", required=True)
    ap.add_argument("--cme-1m", required=True)
    ap.add_argument("--cme-5m", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ftmo-last-n", type=int, default=80)
    ap.add_argument("--cme-start", default="2021-03-13")   # 5yr before data end 2026-03-13
    ap.add_argument("--cme-last-n", type=int, default=0)   # 0 = keep all since cme-start
    ap.add_argument("--min-abs", type=float, default=8.0)   # 2026-06-29: 20->8; the 20pt floor killed 59/124 of his hand-drawn legs
    ap.add_argument("--min-pct", type=float, default=0.10)
    ap.add_argument("--disp-start", default="06:00")
    ap.add_argument("--disp-end", default="23:00")
    ap.add_argument("--leg-start", default="08:00")
    ap.add_argument("--leg-end", default="09:30")
    ap.add_argument("--bot-pine", default="/mnt/c/Users/nader/Documents/Claude-memories/trading bot/v25_engine.pine")   # echter v25 -> Bot-Leg/Box-Overlay
    ap.add_argument("--bot-cme", action="store_true")   # CME-Bot-Overlay (langsam: v25 ueber 5yr 1m)
    a = ap.parse_args()

    ds, de = L.hhmm(a.disp_start), L.hhmm(a.disp_end)
    ls, le = L.hhmm(a.leg_start), L.hhmm(a.leg_end)
    cme_cut = datetime.fromisoformat(a.cme_start + "T00:00:00").replace(tzinfo=UTC)

    print("building FTMO dataset ...", flush=True)
    ftmo = build_dataset(a.ftmo_1m, a.ftmo_5m, [2, 3, 5], [2, 3], a.min_abs, a.min_pct,   # 1m lookbacks +2 (finer pivots) — 2026-06-29
                         ds, de, ls, le, None, a.ftmo_last_n)
    print(f"  ftmo days={len(ftmo)}", flush=True)

    if a.bot_pine and os.path.exists(a.bot_pine):   # echten v25 laufen lassen -> Bot-Leg/Box pro Tag
        from bot_overlay import bot_overlays
        print("  running real v25 for FTMO bot-overlay ...", flush=True)
        bm = bot_overlays(a.bot_pine, a.ftmo_1m)
        for day in ftmo: day["bot"] = bm.get(day["date"])
        print(f"  ftmo bot-overlays: {sum(1 for d in ftmo if d.get('bot'))}/{len(ftmo)}", flush=True)

    print("building CME dataset (streaming 5yr) ...", flush=True)
    cme = build_dataset(a.cme_1m, a.cme_5m, [2, 3, 5], [2, 3], a.min_abs, a.min_pct,   # 1m lookbacks +2 (finer pivots) — 2026-06-29
                        ds, de, ls, le, cme_cut, a.cme_last_n)
    print(f"  cme days={len(cme)}", flush=True)

    if a.bot_pine and a.bot_cme and os.path.exists(a.bot_pine):
        from bot_overlay import bot_overlays
        print("  running real v25 for CME bot-overlay (slow) ...", flush=True)
        bm = bot_overlays(a.bot_pine, a.cme_1m, a.cme_start)
        for day in cme: day["bot"] = bm.get(day["date"])
        print(f"  cme bot-overlays: {sum(1 for d in cme if d.get('bot'))}/{len(cme)}", flush=True)

    payload = {
        "ftmo": {"label": f"FTMO US100 — letzte {len(ftmo)} Tage (1m+5m)", "days": ftmo},
        "cme": {"label": f"CME NQ Futures — {len(cme)} Tage / 5 Jahre (1m+5m)", "days": cme},
    }
    tmpl = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "visual_template.html"), encoding="utf-8").read()
    html = tmpl.replace("__DATA__", json.dumps(payload, separators=(",", ":")))
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(html)
    c_ft = sum(len(x["tf"]["1m"]["cands"]) + len(x["tf"]["5m"]["cands"]) for x in ftmo)
    c_cme = sum(len(x["tf"]["1m"]["cands"]) + len(x["tf"]["5m"]["cands"]) for x in cme)
    print(f"DONE ftmo_days={len(ftmo)} ({c_ft} cands) cme_days={len(cme)} ({c_cme} cands) "
          f"-> {a.out} ({len(html)//1024} KB)")


if __name__ == "__main__":
    main()
