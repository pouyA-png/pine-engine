#!/usr/bin/env python3
"""PILOT-Auswertung — liest die geteilte labels.json (vom VPS) und rechnet die
4 Kennzahlen, die entscheiden ob/wie der grosse Bau Sinn hat:

  1) Detector-Miss-Rate   — wie oft ist Pouyas Leg gar kein Kandidat?
  2) Feature-Validitaet    — korreliert der Chip 'clean-pivot' mit dem clean-Feature?
                             + WARUM weicht er vom groessten Leg ab (Chip-Verteilung)?
  3) Test-Retest           — wie konsistent ist Pouya mit sich selbst (Decke)?
  4) Geld-Tie (Teil A)     — schlaegt Pouyas Pick das 'groesste Leg' in R? (optional, braucht Daten-CSV)

Nutzung:
  curl -s -u <user>:<pw> https://leglab.factbinger.com/api/state > labels.json
  python3 pilot_analyze.py labels.json [--ftmo US100_M1_FTMO_utc.csv] [--cme NQ_continuous_1m.csv]
"""
import sys, json, csv, statistics, argparse
from datetime import datetime, time
from zoneinfo import ZoneInfo
from collections import Counter
NY = ZoneInfo("America/New_York"); UTC = ZoneInfo("UTC")

def gridlevels(s, e):
    r = s - e
    return {'n140': e-1.40*r, 'n078': e-0.78*r, 'l000': e, 'l050': e+0.5*r, 'l100': s, 'l178': e+1.78*r, 'l254': e+2.54*r}

def orders_for(s, e, dow):
    g = gridlevels(s, e); up = e > s; sl = 12.5 if dow in (2,3) else 11.25; eA, tA = 2.0, 5.0
    core = dow in (1,4); pL078, pL140, pS178, pS254 = core, core or dow==3, core or dow==2, core
    o = []
    if up:
        if pS178: x=g['n078']-eA; o.append(('S',x,x+sl,g['l100']+tA))
        if pS254: x=g['n140']-eA; o.append(('S',x,x+sl,g['l050']))
    else:
        if pL078: x=g['n078']+eA; o.append(('L',x,x-sl,g['l100']-tA))
        if pL140: x=g['n140']+eA; o.append(('L',x,x-sl,g['l050']))
        if pS178: x=g['l178']-eA; o.append(('S',x,x+sl,g['l000']+tA))
        if pS254: x=g['l254']-eA; o.append(('S',x,x+sl,g['l050']))
    return o, sl

def sim_day(orders, sl, post):
    cutoff = time(10,0); locked = 0; trades = []
    pend = [{'side':s,'e':e,'sl':slp,'tp':tp,'fill':False,'done':False,'fb':-1} for (s,e,slp,tp) in orders]
    for bi, b in enumerate(post):
        for od in pend:
            if od['done']: continue
            side = 1 if od['side']=='L' else -1
            if not od['fill']:
                if b['t'] >= cutoff: continue
                if locked != 0 and side != locked: od['done']=True; continue
                if (od['side']=='L' and b['l']<=od['e']) or (od['side']=='S' and b['h']>=od['e']):
                    od['fill']=True; od['fb']=bi; locked=side
                    for o2 in pend:
                        if not o2['fill'] and not o2['done'] and (1 if o2['side']=='L' else -1)!=locked: o2['done']=True
                continue   # KEIN Exit-Check am Fill-Bar (sonst Look-ahead: TP/SL vom selben Bar)
            if bi > od['fb']:   # SL/TP erst ab dem Bar NACH dem Fill
                if od['side']=='L': hSL,hTP = b['l']<=od['sl'], b['h']>=od['tp']
                else: hSL,hTP = b['h']>=od['sl'], b['l']<=od['tp']
                if hSL: trades.append(-1.0); od['done']=True
                elif hTP: trades.append(abs(od['tp']-od['e'])/sl); od['done']=True
    if post:
        lc = post[-1]['c']
        for od in pend:
            if od['fill'] and not od['done']:
                trades.append(((lc-od['e']) if od['side']=='L' else (od['e']-lc))/sl); od['done']=True
    return sum(trades)

def load_postbars(path, want_dates):
    from datetime import date as _date, timedelta
    # NY-Session-Bars eines Tages koennen auf den naechsten UTC-Tag fallen -> Prefilter weiten,
    # dann EXAKT nach NY-Datum filtern (sonst Spaet-Bars verworfen + EOD-Close vom falschen Bar).
    pref = set(want_dates)
    for d in list(want_dates):
        try: pref.add((_date.fromisoformat(d) + timedelta(days=1)).isoformat())
        except Exception: pass
    days = {}
    with open(path) as f:
        r = csv.reader(f); h = next(r); ci = {n:i for i,n in enumerate(h)}; di = ci.get('datetime',0)
        for row in r:
            dt = row[di]
            if dt[:10] not in pref: continue
            ts = datetime.fromisoformat(dt)
            if ts.tzinfo is None: ts = ts.replace(tzinfo=UTC)
            ny = ts.astimezone(NY); nd = ny.date().isoformat()
            if nd not in want_dates or ny.time() < time(9,30): continue
            days.setdefault(nd, []).append({'t':ny.time(),'dow':ny.weekday(),
                'o':float(row[ci['open']]),'h':float(row[ci['high']]),'l':float(row[ci['low']]),'c':float(row[ci['close']])})
    for d in days: days[d].sort(key=lambda b:b['t'])
    return days


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("labels"); ap.add_argument("--ftmo"); ap.add_argument("--cme")
    a = ap.parse_args()
    st = json.load(open(a.labels))
    for ds in ("ftmo", "cme"):
        L = st.get(ds, {})
        base = {k: v for k, v in L.items() if not k.endswith("__retest")}
        if not base:
            print(f"\n=== {ds.upper()}: 0 Labels ==="); continue
        print(f"\n=== {ds.upper()}: {len(base)} Labels ===")
        miss = sum(1 for v in base.values() if v.get("type") == "drawn" and v.get("matched") is None)
        print(f"1) Detector-Miss: {miss}/{len(base)} = {100*miss/len(base):.0f}%  (>10-15% -> erst Detektor lockern)")
        cand = {k: v for k, v in base.items() if v.get("type") == "cand"}
        vsbig = [v.get("vsBig") for v in cand.values() if "vsBig" in v]
        if vsbig:
            tb = sum(vsbig); print(f"2) Pick = groesstes Leg: {tb}/{len(vsbig)} = {100*tb/len(vsbig):.0f}%  (Rest = Skill ueber 'groesstes')")
        cc = Counter()
        for v in cand.values():
            if v.get("vsBig") == 0:
                for ch in v.get("chips", []): cc[ch] += 1
        if cc: print(f"   Gruende fuer Abweichung vom groessten: {dict(cc.most_common())}")
        cl_yes, cl_no = [], []
        for v in cand.values():
            snap = v.get("snap", {}).get(v.get("tf"), []); idx = v.get("idx")
            if isinstance(idx, int) and 0 <= idx < len(snap):
                cv = snap[idx].get("clean")
                if cv is not None:
                    (cl_yes if "clean-pivot" in v.get("chips", []) else cl_no).append(cv)
        if cl_yes or cl_no:
            my = statistics.mean(cl_yes) if cl_yes else float('nan')
            mn = statistics.mean(cl_no) if cl_no else float('nan')
            print(f"   Feature-Validitaet 'clean': mit Chip O={my:.2f} (n={len(cl_yes)}) vs ohne O={mn:.2f} (n={len(cl_no)})")
        pairs = [(k, k+"__retest") for k in base if (k+"__retest") in L]
        if pairs:
            agree = sum(1 for a0,a1 in pairs if L[a0].get("type")==L[a1].get("type") and L[a0].get("idx")==L[a1].get("idx") and L[a0].get("gate")==L[a1].get("gate"))
            print(f"3) Test-Retest-Konsistenz: {agree}/{len(pairs)} = {100*agree/len(pairs):.0f}%  (= Decke)")
        else:
            print("3) Test-Retest: noch keine Re-Test-Paare (Re-Test-Button im Dashboard)")
        path = a.ftmo if ds == "ftmo" else a.cme
        if path:
            post = load_postbars(path, set(cand))
            beats = n = 0; dR = []
            for k, v in cand.items():
                if k not in post: continue
                snap = v.get("snap", {}).get(v.get("tf"), []); idx = v.get("idx")
                if not (isinstance(idx, int) and 0 <= idx < len(snap)): continue
                dow = post[k][0]['dow']; pk = snap[idx]
                rp = sim_day(*orders_for(pk['start'], pk['pivot'], dow), post[k])
                bi = max(range(len(snap)), key=lambda i: snap[i]['size'])
                rb = sim_day(*orders_for(snap[bi]['start'], snap[bi]['pivot'], dow), post[k])
                n += 1; dR.append(rp-rb); beats += 1 if rp > rb else 0
            if n:
                print(f"4) Geld-Tie (Pouya vs 'groesstes'): schlaegt es an {beats}/{n} Tagen; O {statistics.mean(dR):+.2f} R/Tag")
        else:
            print("4) Geld-Tie: --ftmo/--cme CSV angeben")


if __name__ == "__main__":
    main()
