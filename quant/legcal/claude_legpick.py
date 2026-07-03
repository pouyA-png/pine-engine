#!/usr/bin/env python3
"""Render pre-open candidate-leg charts per NY day so Claude can VISUALLY pick the
best leg (Q2: visuell nach Pattern), then later compute the trade outcome.

Reuses export_dashboard.build_tf_stream for the exact same candidate detection the
live leglab dashboard uses (lookbacks [2,3,5], min_abs 8, min_pct .10, leg win 08:00-09:30 NY).

  python3 claude_legpick.py --data <bars.csv> --outdir <pngdir> [--start D --end D] [--limit N]

Output: one <date>.png per day (pre-open candles + numbered candidate legs) + days.json
(per-day candidate features) for the outcome step. NO browser, pure matplotlib.
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import leg_candidates as L
from export_dashboard import build_tf_stream

UP, DN = "#2F8F66", "#CB4B41"


def _hhmm(tf, i):
    t = tf["tmin"][i] if 0 <= i < len(tf["tmin"]) else None
    return f"{t//60:02d}:{t%60:02d}" if t is not None else "?"


def render_day(date, tf, outpath, context=150):
    """tf = {open_idx, tmin, bars:[[o,h,l,c]...], cands:[...]}. Pre-open only, ZOOMED to the
    leg window so pivots are readable. Distinct colour + number per candidate, compact legend."""
    bars, oi = tf["bars"], tf["open_idx"]
    end = oi if oi and oi > 0 else len(bars)
    end = min(end, len(bars))
    cands = [c for c in tf["cands"] if c["i0"] < end and c["i1"] < end]
    # zoom: show `context` bars before open (covers ~07:00-09:30), but include earliest candidate
    lo = max(0, end - context)
    if cands:
        lo = min(lo, min(c["i0"] for c in cands) - 3)
    lo = max(0, lo)
    xs = list(range(lo, end))

    fig, (ax, axl) = plt.subplots(1, 2, figsize=(16, 7.5), dpi=95,
                                  gridspec_kw={"width_ratios": [4, 1.25]})
    axl.axis("off")
    cw = 0.6
    pr_lo, pr_hi = 1e18, -1e18
    for i in xs:
        o, h, l, c = bars[i]
        col = UP if c >= o else DN
        ax.plot([i, i], [l, h], color=col, lw=0.8, zorder=1)
        ax.add_patch(plt.Rectangle((i - cw / 2, min(o, c)), cw, max(abs(c - o), 0.1), color=col, zorder=2))
        pr_lo, pr_hi = min(pr_lo, l), max(pr_hi, h)

    # candidates sorted by recency (minopen asc) so #0 = most recent pivot — same key signal as the selector
    order = sorted(range(len(cands)), key=lambda k: cands[k]["minopen"])
    palette = plt.get_cmap("tab20")
    legend_lines = []
    for rank, k in enumerate(order):
        c = cands[k]
        col = palette(rank % 20)
        ax.plot([c["i0"], c["i1"]], [c["start"], c["pivot"]], color=col, lw=1.8, zorder=4, alpha=0.85)
        ax.scatter([c["i1"]], [c["pivot"]], color=col, s=46, zorder=6, edgecolor="white", lw=0.7)
        ax.annotate(f"{rank}", (c["i1"], c["pivot"]), color="white", fontsize=8, fontweight="bold",
                    zorder=7, ha="center", va="center")
        arrow = "^" if c["dir"] == "up" else "v"
        legend_lines.append((rank, col,
            f"#{rank:<2d}{arrow} {c['start']:.0f}>{c['pivot']:.0f} {c['size']:.0f}pt "
            f"{c['minopen']}m cl{c['clean']} {'SW' if c['sweep'] else '  '}"))

    ax.axvline(end - 0.5, color="#666", ls="--", lw=1.2)
    ax.annotate("09:30 Open", (end - 0.5, pr_hi), color="#666", fontsize=9, ha="right", va="bottom")
    # legend list in its own right panel (no overlap with candles)
    axl.annotate("Kandidaten (nach Recency)\n#0 = jüngster Pivot vor Open\n", (0.0, 1.0),
                 xycoords="axes fraction", va="top", fontsize=9, family="monospace", color="#333")
    for rank, col, txt in legend_lines:
        axl.annotate(txt, (0.0, 0.93 - rank * 0.052), xycoords="axes fraction",
                     va="top", fontsize=8.5, family="monospace", color=col, fontweight="bold")
    ax.set_xlim(lo - 1, end + max(3, context // 12))
    ax.set_ylim(pr_lo - (pr_hi - pr_lo) * 0.05, pr_hi + (pr_hi - pr_lo) * 0.08)
    ax.set_title(f"{date}  ·  Leg-Fenster 08:00-09:30 NY  ·  {len(cands)} Kandidaten  "
                 f"(#0 = jüngster Pivot vor Open)", fontsize=12)
    ax.set_xlabel("Bar"); ax.set_ylabel("Preis")
    ax.grid(True, alpha=0.15)
    fig.tight_layout()
    fig.savefig(outpath, facecolor="white")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--limit", type=int, default=0, help="render only the last N days (0=all)")
    ap.add_argument("--min-abs", type=float, default=8.0)
    ap.add_argument("--min-pct", type=float, default=0.10)
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    ds, de = L.hhmm("06:00"), L.hhmm("23:00")       # display window (Berlin)
    ls, le = L.hhmm("08:00"), L.hhmm("09:30")       # leg detection window (NY)
    from datetime import datetime
    from zoneinfo import ZoneInfo
    cutoff = None
    if a.start:
        cutoff = datetime.fromisoformat(a.start + "T00:00:00").replace(tzinfo=ZoneInfo("UTC"))

    print("streaming candidates ...", flush=True)
    d1 = build_tf_stream(a.data, [2, 3, 5], a.min_abs, a.min_pct, ds, de, ls, le, cutoff)
    days = sorted(d for d in d1 if len(d1[d]["bars"]) >= 200 and d1[d]["open_idx"] >= 0)
    if a.end:
        days = [d for d in days if d.isoformat() <= a.end]
    if a.limit:
        days = days[-a.limit:]
    print(f"{len(days)} days to render", flush=True)

    meta = {}
    for d in days:
        ds_iso = d.isoformat()
        render_day(ds_iso, d1[d], os.path.join(a.outdir, ds_iso + ".png"))
        cands = [c for c in d1[d]["cands"]]
        order = sorted(range(len(cands)), key=lambda k: cands[k]["minopen"])   # recency rank -> orig idx
        meta[ds_iso] = {"open_idx": d1[d]["open_idx"],
                        "cands": cands, "recency_order": order}   # rank r -> cands[order[r]]
    json.dump(meta, open(os.path.join(a.outdir, "days.json"), "w"))
    print(f"DONE {len(days)} pngs + days.json -> {a.outdir}", flush=True)


if __name__ == "__main__":
    main()
