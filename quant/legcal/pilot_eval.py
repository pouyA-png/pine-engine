#!/usr/bin/env python3
"""PILOT-EVAL — quantitative Auswertungs-Pipeline fuer die Leg-Labels.
Fundament fuer spaetere STRESS-TESTS und PARAMETER-STABILITAETS-TESTS.

Architektur (entkoppelt, damit jeder Test darauf aufsetzen kann):
  1) build_dataset()  labels.json (+Daten-CSV) -> EINE eingefrorene Tabelle:
       pro gelabeltem Tag: alle Kandidaten-Features (snap), gewaehlter idx, groesster idx,
       chips/gate/conf, Detector-Miss, Regime-Tags (Jahr/Wochentag/Vol-Bucket),
       UND pnl_per_cand[] = Teil-A-Tages-R fuer JEDEN Kandidaten (einmal gerechnet, dann reused).
  2) Selektoren (austauschbar): size | recency | weighted(w) | cascade(thetas) | <neue Features>
  3) STABILITAET: Bootstrap-Parameter-CI, k-Fold-OOS, Walk-Forward, Perturbations-Sensitivitaet
  4) STRESS:      Regime-Split, OOS-Transfer (FTMO<->CME), Kosten-Leiter, Monte-Carlo (PF/MaxDD/Breach)
  Alles -> JSON (reproduzierbar/vergleichbar ueber Laeufe) + lesbare Zusammenfassung.

Nutzung:
  curl -s -u <user>:<pw> https://leglab.factbinger.com/api/state > labels.json
  python3 pilot_eval.py --labels labels.json --ftmo US100_M1_FTMO_utc.csv --cme NQ_continuous_1m.csv --out eval.json
  # ohne echte Labels — Pipeline mit Synth-Daten validieren:
  python3 pilot_eval.py --synth 120 --ftmo US100_M1_FTMO_utc.csv --out eval_synth.json
"""
import sys, os, json, csv, math, statistics, argparse, random
from datetime import datetime, time
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pilot_analyze import orders_for, sim_day, load_postbars   # Teil-A-Sim 1:1 v25
import leg_candidates as L
NY = ZoneInfo("America/New_York"); UTC = ZoneInfo("UTC")
random.seed(13)

FEATS = ["size", "recency", "sweep", "wick", "clean", "disp", "distlvl", "round"]

# ───────────────────────── Feature-Normierung (pro Tag, fuer Selektoren) ─────────────────────────
def featvec(cands, c):
    sizes = [x["size"] for x in cands]; mx = max(sizes + [c["size"]]) or 1
    mins = [x["minopen"] for x in cands]; mn = min(mins); span = (max(mins) - mn) or 1
    dmax = max([x["disp"] for x in cands]) or 1
    dl = [x["distlvl"] for x in cands if x["distlvl"] is not None]
    dlo = min(dl + [1e9]); dls = (max(dl + [0]) - dlo) or 1
    rd = [x["round"] for x in cands]; rlo = min(rd); rls = (max(rd) - rlo) or 1
    return {"size": c["size"]/mx, "recency": 1-(c["minopen"]-mn)/span, "sweep": 1.0 if c["sweep"] else 0.0,
            "wick": 1.0 if c["wick"] else 0.0, "clean": (c["clean"]-1)/4,
            "disp": c["disp"]/dmax, "distlvl": 0.0 if c["distlvl"] is None else 1-(c["distlvl"]-dlo)/dls,
            "round": 1-(c["round"]-rlo)/rls}

# ───────────────────────── Selektoren (row-basiert, nutzen vorberechnete row["fv"]) ─────────────────────────
def argmax_w(row, wv):
    best = -1e18; bi = 0
    for i, fv in enumerate(row["fv"]):
        s = 0.0
        for j in range(8): s += wv[j]*fv[j]
        if s > best: best = s; bi = i
    return bi
def sel_weighted(w):
    wv = [w.get(k, 0) for k in FEATS]
    return lambda row: argmax_w(row, wv)
def sel_size(): return sel_weighted({"size": 1})
def sel_recency(): return sel_weighted({"recency": 1})

def _hit_w(rows, wv): return sum(1 for r in rows if argmax_w(r, wv) == r["picked"])
def fit_weighted(rows, vals=(0, 1, 2), rounds=4):
    """Coordinate-Ascent statt 3^8-Grid (schnell, gut genug fuer Stabilitaets-Resampling)."""
    w = {f: 0 for f in FEATS}; w["size"] = 1
    cur = _hit_w(rows, [w[k] for k in FEATS])
    for _ in range(rounds):
        improved = False
        for f in FEATS:
            bestv = w[f]; bh = cur
            for v in vals:
                w[f] = v; h = _hit_w(rows, [w[k] for k in FEATS])
                if h > bh: bh = h; bestv = v
            w[f] = bestv
            if bh > cur: cur = bh; improved = True
        if not improved: break
    if not any(w.values()): w["size"] = 1
    return w

# ───────────────────────── Dataset-Builder (eingefroren) ─────────────────────────
def volbucket(cands):
    return max((c["size"] for c in cands), default=0.0)

def build_rows(labels_ds, postpath):
    cand_lbl = {k: v for k, v in labels_ds.items() if not k.endswith("__retest") and v.get("type") == "cand" and v.get("snap")}
    post = load_postbars(postpath, set(cand_lbl)) if postpath else {}
    rows = []
    for k, v in cand_lbl.items():
        cands = v["snap"].get(v.get("tf"), [])
        if not cands or not isinstance(v.get("idx"), int) or not (0 <= v["idx"] < len(cands)):
            continue
        dow = post[k][0]["dow"] if k in post else datetime.fromisoformat(k).weekday()
        pnl = []
        for c in cands:
            if k in post:
                o, sl = orders_for(c["start"], c["pivot"], dow); pnl.append(sim_day(o, sl, post[k]))
            else:
                pnl.append(0.0)
        big = max(range(len(cands)), key=lambda i: cands[i]["size"])
        fv = [[featvec(cands, c)[k] for k in FEATS] for c in cands]   # einmal vorberechnen
        rows.append({"date": k, "dow": dow, "year": int(k[:4]), "vol": volbucket(cands),
                     "cands": cands, "fv": fv, "picked": v["idx"], "biggest": big,
                     "chips": v.get("chips", []), "gate": v.get("gate", ""), "conf": v.get("conf", 0),
                     "pnl": pnl})
    return rows

# ───────────────────────── PnL-Helfer ─────────────────────────
def day_R(rows, selector): return [r["pnl"][selector(r)] for r in rows]
def pf(Rs):
    w = sum(x for x in Rs if x > 0); l = -sum(x for x in Rs if x < 0)
    return (w/l) if l > 0 else (float("inf") if w > 0 else 0.0)
def maxdd(Rs):
    eq = 0.0; peak = 0.0; dd = 0.0
    for x in Rs:
        eq += x; peak = max(peak, eq); dd = min(dd, eq - peak)
    return dd
def hitrate(rows, selector): return sum(1 for r in rows if selector(r) == r["picked"]) / max(1, len(rows))
def block_sample(seq, bl=5):
    """Circular Block-Bootstrap: resamplet zusammenhaengende Bloecke -> erhaelt serielle Korrelation
    (i.i.d. unterschaetzt Drawdown-Clustering/Breach)."""
    n = len(seq)
    if n == 0: return []
    out = []
    while len(out) < n:
        s = random.randrange(n)
        out.extend(seq[i % n] for i in range(s, s + bl))
    return out[:n]

# ───────────────────────── PARAMETER-STABILITAET ─────────────────────────
def stability(rows, B=200, K=5):
    out = {}
    # 1) Bootstrap: refit auf Resample, Verteilung der Gewichte + OOS-Hit auf nicht-gezogenen Tagen
    wcount = {f: 0 for f in FEATS}; wvals = {f: [] for f in FEATS}; oos_hits = []
    n = len(rows)
    for _ in range(B):
        idx = [random.randrange(n) for _ in range(n)]; idxset = set(idx)   # einmal, nicht je i (war O(n^2))
        train = [rows[i] for i in idx]; oob = [rows[i] for i in range(n) if i not in idxset]
        w = fit_weighted(train)
        for f in FEATS:
            wvals[f].append(w.get(f, 0))
            if w.get(f, 0) > 0: wcount[f] += 1
        if oob: oos_hits.append(hitrate(oob, sel_weighted(w)))
    out["bootstrap"] = {
        "B": B,
        "feature_selected_pct": {f: round(100*wcount[f]/B, 1) for f in FEATS},          # wie oft Feature im Fit nonzero -> Stabilitaet
        "weight_mean": {f: round(statistics.mean(wvals[f]), 2) for f in FEATS},
        "weight_std": {f: round(statistics.pstdev(wvals[f]), 2) for f in FEATS},
        "oos_hit_mean": round(statistics.mean(oos_hits), 3) if oos_hits else None,
        "oos_hit_std": round(statistics.pstdev(oos_hits), 3) if len(oos_hits) > 1 else None,
    }
    # 2) k-Fold-OOS Hitrate (gefittet ohne fold, getestet auf fold)
    sh = rows[:]; random.shuffle(sh); folds = [sh[i::K] for i in range(K)]; fh = []
    for i in range(K):
        test = folds[i]; train = [r for j in range(K) if j != i for r in folds[j]]
        if not train or not test: continue
        fh.append(hitrate(test, sel_weighted(fit_weighted(train))))
    out["kfold_oos_hit"] = {"k": K, "mean": round(statistics.mean(fh), 3) if fh else None,
                            "std": round(statistics.pstdev(fh), 3) if len(fh) > 1 else None, "folds": [round(x, 3) for x in fh]}
    # 3) Walk-Forward (chronologisch: fit erste Haelfte -> test zweite)
    sd = sorted(rows, key=lambda r: r["date"]); h = len(sd)//2
    if h >= 2:
        w = fit_weighted(sd[:h])
        out["walkforward"] = {"train_hit": round(hitrate(sd[:h], sel_weighted(w)), 3),
                              "test_hit": round(hitrate(sd[h:], sel_weighted(w)), 3),
                              "decay": round(hitrate(sd[:h], sel_weighted(w)) - hitrate(sd[h:], sel_weighted(w)), 3)}
    # 4) Perturbations-Sensitivitaet: fitte Gewichte, jitter jedes Gewicht ±1, miss Hit/PnL-Aenderung
    w0 = fit_weighted(rows); base_hit = hitrate(rows, sel_weighted(w0)); base_pf = pf(day_R(rows, sel_weighted(w0)))
    sens = {}
    for f in FEATS:
        deltas = []
        for d in (-1, 1):
            w = dict(w0); w[f] = max(0, w.get(f, 0) + d)
            deltas.append(abs(hitrate(rows, sel_weighted(w)) - base_hit))
        sens[f] = round(max(deltas), 3)               # max Hit-Aenderung bei ±1 -> hoch = fragil
    out["fitted_weights"] = w0
    out["perturbation_hit_sensitivity"] = sens
    out["base_hit"] = round(base_hit, 3); out["base_pf"] = round(base_pf, 2)
    return out

# ───────────────────────── STRESS-TESTS ─────────────────────────
def stress(rows, selector, rows_other=None, mc=2000, dd_threshold=-30.0):
    out = {}
    Rs = day_R(rows, selector)
    # 1) Regime-Split
    def grp(keyfn):
        g = {}
        for r in rows: g.setdefault(keyfn(r), []).append(r["pnl"][selector(r)])
        return {str(k): {"n": len(v), "R": round(sum(v), 1), "PF": round(pf(v), 2)} for k, v in sorted(g.items())}
    vols = sorted(r["vol"] for r in rows); q = lambda p: vols[min(len(vols)-1, int(p*len(vols)))] if vols else 0
    lo, hi = q(0.33), q(0.66)
    out["regime"] = {
        "by_year": grp(lambda r: r["year"]),
        "by_weekday": grp(lambda r: ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][r["dow"]]),
        "by_vol": grp(lambda r: "lo" if r["vol"] <= lo else ("hi" if r["vol"] > hi else "mid")),
    }
    # 2) OOS-Transfer: fitte auf rows, evaluiere PnL auf rows_other
    if rows_other:
        w = fit_weighted(rows); s2 = sel_weighted(w)
        Ro = day_R(rows_other, s2)
        out["oos_transfer"] = {"train_PF": round(pf(Rs), 2), "transfer_PF": round(pf(Ro), 2),
                               "transfer_hit": round(hitrate(rows_other, s2), 3), "transfer_n": len(rows_other)}
    # 3) Kosten-Leiter (c Punkte Reibung pro Trade-R, in SL-Einheiten ~ c/11.25)
    ladder = {}
    for c in (0.0, 0.5, 1.0, 1.5, 2.0, 3.0):
        adj = [x - (c/11.25) for x in Rs]   # grob: c Punkte Kosten je Trade, normiert auf ~SL
        ladder[str(c)] = {"R": round(sum(adj), 1), "PF": round(pf(adj), 2)}
    out["cost_ladder_points"] = ladder
    # 4) Monte-Carlo: Trades resamplen -> Verteilung PF/MaxDD/Breach
    if Rs:
        pfs = []; dds = []; tot = []
        Rsm = [r["pnl"][selector(r)] for r in sorted(rows, key=lambda r: r["date"])]   # chronologisch -> Block-Bootstrap erhaelt Serien-Cluster
        for _ in range(mc):
            samp = block_sample(Rsm)
            pfs.append(pf(samp)); dds.append(maxdd(samp)); tot.append(sum(samp))
        pfs_f = [x for x in pfs if math.isfinite(x)]
        breach = sum(1 for d in dds if d <= dd_threshold) / len(dds)
        out["montecarlo"] = {"runs": mc, "total_R": {"p5": round(sorted(tot)[int(.05*mc)], 1), "med": round(statistics.median(tot), 1), "p95": round(sorted(tot)[int(.95*mc)], 1)},
                             "PF": {"p5": round(sorted(pfs_f)[max(0,min(len(pfs_f)-1,int(.05*len(pfs_f))))], 2) if pfs_f else None, "med": round(statistics.median(pfs_f), 2) if pfs_f else None},
                             "maxDD_R": {"med": round(statistics.median(dds), 1), "p95_worst": round(sorted(dds)[int(.05*mc)], 1)},
                             "breach_prob": round(breach, 3), "dd_threshold_R": dd_threshold}
    out["headline_PF"] = round(pf(Rs), 2); out["headline_R"] = round(sum(Rs), 1); out["n_days"] = len(rows)
    return out

# ───────────────────────── SYNTH (Pipeline ohne echte Labels validieren) ─────────────────────────
def make_synth(path, ndays):
    """Erzeuge ndays Synth-Labels aus echten Kandidaten + geplanter verrauschter Regel."""
    days = {}
    with open(path) as f:
        r = csv.reader(f); h = next(r); ci = {n: i for i, n in enumerate(h)}
        for row in r:
            ts = datetime.fromisoformat(row[ci.get("datetime", 0)])
            if ts.tzinfo is None: ts = ts.replace(tzinfo=UTC)
            ny = ts.astimezone(NY)
            days.setdefault(ny.date(), []).append({"ts": ny, "t": ny.time(),
                "o": float(row[ci["open"]]), "h": float(row[ci["high"]]), "l": float(row[ci["low"]]), "c": float(row[ci["close"]])})
    out = {}
    for d in sorted(days)[-ndays*2:]:
        db = days[d]; pre = [b for b in db if time(8, 0) <= b["t"] <= time(9, 40)]
        if len(pre) < 8: continue
        cs = L.candidates_for_day(pre, [3, 5], 20.0, 0.10, time(9, 30), None, anchor_win=(time(8, 0), time(9, 30)))
        if len(cs) < 2: continue
        snap = [{"size": c["leg_size"], "clean": c["clean"], "eff": c["efficiency"], "disp": c["displacement"],
                 "sweep": c["sweep"] == "J", "wick": c["wick"] == "J", "distlvl": (c["dist_level"] if c["dist_level"] != "" else None),
                 "round": c["round_dist"], "minopen": c["min_before_open"], "dir": c["direction"],
                 "start": c["start_price"], "pivot": c["pivot_price"]} for c in cs]
        # geplante Regel: groesster + sweep, + 25% Rausch
        def score(c): return c["size"]*(1.4 if c["sweep"] else 1.0)
        if random.random() < 0.25:
            pick = random.randrange(len(snap))
        else:
            pick = max(range(len(snap)), key=lambda i: score(snap[i]))
        big = max(range(len(snap)), key=lambda i: snap[i]["size"])
        out[d.isoformat()] = {"type": "cand", "tf": "1m", "idx": pick, "by": "synth",
                              "chips": (["sweep", "groesstes"] if pick == big else ["sweep"]),
                              "gate": "1m", "conf": random.choice([1, 1, 2]), "vsBig": 1 if pick == big else 0,
                              "big": big, "snap": {"1m": snap, "5m": []}}
        if len(out) >= ndays: break
    return {"ftmo": out, "cme": {}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels"); ap.add_argument("--ftmo"); ap.add_argument("--cme")
    ap.add_argument("--synth", type=int, default=0); ap.add_argument("--out", default="eval.json")
    a = ap.parse_args()
    if a.synth:
        st = make_synth(a.ftmo, a.synth); print(f"[synth] {len(st['ftmo'])} Tage erzeugt")
    else:
        st = json.load(open(a.labels))
    result = {}
    rows_ftmo = build_rows(st.get("ftmo", {}), a.ftmo)
    rows_cme = build_rows(st.get("cme", {}), a.cme)
    print(f"Dataset: FTMO {len(rows_ftmo)} Tage, CME {len(rows_cme)} Tage")
    for name, rows, other in (("ftmo", rows_ftmo, rows_cme), ("cme", rows_cme, rows_ftmo)):
        if len(rows) < 5:
            result[name] = {"n": len(rows), "note": "zu wenige Labels fuer Stabilitaet/Stress (>=5 noetig)"}
            continue
        w = fit_weighted(rows); sel = sel_weighted(w)
        result[name] = {"n": len(rows), "stability": stability(rows), "stress": stress(rows, sel, other or None)}
    json.dump(result, open(a.out, "w"), indent=1)
    # lesbare Zusammenfassung
    for name in ("ftmo", "cme"):
        r = result.get(name, {})
        if "stability" not in r:
            print(f"\n[{name}] {r.get('note', r)}"); continue
        s, ss = r["stability"], r["stress"]
        print(f"\n========== {name.upper()} — {r['n']} Tage ==========")
        print(f"STABILITAET: base Hit {s['base_hit']}, k-Fold-OOS {s['kfold_oos_hit']['mean']}±{s['kfold_oos_hit']['std']}, "
              f"Walk-Fwd test {s.get('walkforward',{}).get('test_hit')} (decay {s.get('walkforward',{}).get('decay')})")
        print(f"  Feature-Stabilitaet (Bootstrap %selected): {s['bootstrap']['feature_selected_pct']}")
        print(f"  Perturbations-Sensitivitaet (max Hit-Δ bei ±1): {s['perturbation_hit_sensitivity']}")
        print(f"STRESS: PF {ss['headline_PF']} ({ss['headline_R']} R), "
              f"Regime/Jahr { {k: v['PF'] for k, v in ss['regime']['by_year'].items()} }")
        if "oos_transfer" in ss: print(f"  OOS-Transfer PF {ss['oos_transfer']['transfer_PF']} (hit {ss['oos_transfer']['transfer_hit']})")
        print(f"  Kosten-Leiter PF: { {k: v['PF'] for k, v in ss['cost_ladder_points'].items()} }")
        if "montecarlo" in ss: print(f"  Monte-Carlo PF med {ss['montecarlo']['PF']['med']}, MaxDD med {ss['montecarlo']['maxDD_R']['med']} R, Breach-Prob {ss['montecarlo']['breach_prob']}")
    print(f"\n-> JSON: {a.out}")


if __name__ == "__main__":
    main()
