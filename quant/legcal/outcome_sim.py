#!/usr/bin/env python3
"""Outcome of the v25cris-LIMITS trade IF the bot had used a GIVEN leg, per NY day.
Deterministic (no agent). Used to score Claude's visual leg-picks -> win rate.

Trade model verified against bot_lastyear.pine (see CLAUDE_LEGLAB_TASKS.md):
  levels from leg (start=1.00, pivot=0.00); UP-leg -> shorts only; DOWN -> longs+shorts.
  SL Di/Fr 13.5, Mi/Do 12.5; entAdj 2, tpAdj 5; risk $750/level $20/pt.

SIMPLIFIED FILL MODEL (documented limitations):
  - each half order has its own entry-limit / SL / TP1|TP2 (no break-even move after TP1).
  - side-lock: first order that fills locks the side; opposite-side pendings are cancelled.
  - if a bar touches both SL and TP, SL is assumed first (conservative).
  - R is expressed in units of LEVEL risk (1.0R = the $750 risk of one full level).
Returns per-day total R (sum over filled levels) + per-order detail.
"""
from datetime import time
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
ENT_ADJ, TP_ADJ, NQ_PTVAL, RISK = 2.0, 5.0, 20.0, 750.0
RTH_OPEN, RTH_END = time(9, 30), time(16, 0)


def levels_from_leg(startP, pivot):
    r = startP - pivot
    return {"n140": pivot - 1.40 * r, "n078": pivot - 0.78 * r, "l000": pivot,
            "l050": pivot + 0.50 * r, "l100": startP, "l178": pivot + 1.78 * r,
            "l254": pivot + 2.54 * r}


def orders_for(startP, pivot, dow):
    """dow: 0=Mon..6=Sun (python weekday()). Returns (orders, SL) or ([],SL)."""
    Lv = levels_from_leg(startP, pivot)
    up = pivot > startP
    isTue, isWed, isThu, isFri = dow == 1, dow == 2, dow == 3, dow == 4
    core = isTue or isFri
    SL = 12.5 if (isWed or isThu) else 13.5
    if dow == 0 or dow >= 5:            # Monday off, weekend none
        return [], SL
    pL078, pL140, pS178, pS254 = core, core or isThu, core or isWed, core
    O = []
    if up:
        if pS178: O.append(("S178", "short", Lv["n078"] - ENT_ADJ, [Lv["l100"] + TP_ADJ]))
        if pS254: O.append(("S254", "short", Lv["n140"] - ENT_ADJ, [Lv["l050"]]))
    else:
        if pL078: O.append(("L078", "long", Lv["n078"] + ENT_ADJ, [Lv["l100"] - TP_ADJ, Lv["l254"] - TP_ADJ]))
        if pL140: O.append(("L140", "long", Lv["n140"] + ENT_ADJ, [Lv["l050"], Lv["l254"] - TP_ADJ]))
        if pS178: O.append(("S178", "short", Lv["l178"] - ENT_ADJ, [Lv["l000"] + TP_ADJ, Lv["n140"] + TP_ADJ]))
        if pS254: O.append(("S254", "short", Lv["l254"] - ENT_ADJ, [Lv["l050"], Lv["n140"] + TP_ADJ]))
    return O, SL


def simulate_day(startP, pivot, dow, rth_bars, be_offset=None):
    """rth_bars: list of (high, low) or (open, high, low) from 09:30 onward (chronological).
    Time-stepped: all orders live simultaneously; first fill (chronological) locks the side and
    cancels opposite-side pendings.
    be_offset: if not None, model v25's BE-move — once the a-half (TP1) hits, the b-half's SL
    moves to break-even = entry + sgn*be_offset (b-half can no longer lose after TP1).
    Returns dict: total_R, side, n_filled, orders[]."""
    orders, SL = orders_for(startP, pivot, dow)
    if not orders or not rth_bars:
        return {"total_R": 0.0, "side": None, "n_filled": 0, "orders": [], "note": "no orders/bars"}

    st = []
    for nm, side, ent, tps in orders:
        sgn = 1 if side == "long" else -1
        st.append({"nm": nm, "side": side, "ent": ent, "sgn": sgn, "sl": ent - sgn * SL,
                   "cancelled": False, "tp1_done": False,
                   "halves": [{"tp": tps[0], "filled": False, "done": None, "is_a": True},
                              {"tp": tps[-1], "filled": False, "done": None, "is_a": False}]})
    locked = None

    for bar in rth_bars:
        if len(bar) == 3:
            o, h, l = bar
        else:
            (h, l), o = bar, None
        newly = []
        for s in st:
            if s["cancelled"]:
                continue
            for hf in s["halves"]:
                if not hf["filled"] and hf["done"] is None:
                    hit = (l <= s["ent"]) if s["side"] == "long" else (h >= s["ent"])
                    if hit:
                        newly.append(s)
                        break
        if newly and locked is None:
            ref = o if o is not None else (h + l) / 2
            newly.sort(key=lambda s: abs(s["ent"] - ref))
            locked = newly[0]["side"]
            for s in st:
                if s["side"] != locked and not any(hf["filled"] for hf in s["halves"]):
                    s["cancelled"] = True
        for s in st:
            if s["cancelled"]:
                continue
            if locked is not None and s["side"] != locked and not any(hf["filled"] for hf in s["halves"]):
                s["cancelled"] = True
                continue
            for hf in s["halves"]:
                if hf["done"] is not None:
                    continue
                if not hf["filled"]:
                    hit = (l <= s["ent"]) if s["side"] == "long" else (h >= s["ent"])
                    if hit:
                        hf["filled"] = True
                if hf["filled"]:
                    # effective SL: b-half uses BE after a-half TP1 (if be_offset set)
                    eff_sl = s["sl"]
                    if be_offset is not None and not hf["is_a"] and s["tp1_done"]:
                        eff_sl = s["ent"] + s["sgn"] * be_offset
                    sl_hit = (l <= eff_sl) if s["side"] == "long" else (h >= eff_sl)
                    tp_hit = (h >= hf["tp"]) if s["side"] == "long" else (l <= hf["tp"])
                    if sl_hit:
                        hf["done"] = ("BE" if (be_offset is not None and not hf["is_a"] and s["tp1_done"]) else "SL")
                        hf["exit"] = eff_sl
                    elif tp_hit:
                        hf["done"] = "TP"
                        if hf["is_a"]:
                            s["tp1_done"] = True

    results = []
    for s in st:
        if any(hf["filled"] for hf in s["halves"]):
            R = 0.0
            for hf in s["halves"]:
                if hf["done"] == "SL":
                    R += -0.5
                elif hf["done"] == "BE":
                    R += s["sgn"] * (hf["exit"] - s["ent"]) / (2.0 * SL)   # ~BE: tiny + (offset)
                elif hf["done"] == "TP":
                    R += s["sgn"] * (hf["tp"] - s["ent"]) / (2.0 * SL)
            results.append({"nm": s["nm"], "side": s["side"], "ent": round(s["ent"], 2),
                            "R": round(R, 3),
                            "halves": [hf["done"] or "OPEN" for hf in s["halves"]]})
    total = round(sum(o["R"] for o in results), 3)
    return {"total_R": total, "side": locked, "n_filled": len(results), "orders": results}


def stream_rth_by_day(path, start_date=None):
    """Stream CSV once -> {ny_date: [(high,low),...] for 09:30-16:00 NY}."""
    from datetime import datetime
    UTC = ZoneInfo("UTC")
    out, cur, buf = {}, None, []
    cut = None
    if start_date:
        cut = datetime.fromisoformat(start_date + "T00:00:00").replace(tzinfo=UTC)
    with open(path) as f:
        f.readline()
        for line in f:
            c0 = line.find(",")
            if c0 < 0:
                continue
            ts = datetime.fromisoformat(line[:c0])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if cut and ts < cut:
                continue
            ny = ts.astimezone(NY)
            d = ny.date()
            if d != cur:
                if cur is not None:
                    out[cur] = buf
                cur, buf = d, []
            if RTH_OPEN <= ny.time() <= RTH_END:
                p = line.rstrip("\n").split(",")
                buf.append((float(p[1]), float(p[2]), float(p[3])))   # open, high, low
    if cur is not None:
        out[cur] = buf
    return out


if __name__ == "__main__":
    # tiny self-test: synthetic down-leg, long fills then TP
    # leg start=21040 pivot=21000 (down), Tuesday(dow=1)
    O, SL = orders_for(21040, 21000, 1)
    print("Tue down-leg orders:", [(o[0], o[1], round(o[2], 1)) for o in O], "SL", SL)
    # bars: price drops to L078 entry then rallies to TP1/TP2
    bars = [(20990, 21000, 20965), (20980, 21010, 20960), (21050, 21100, 21030)]
    print("WIN long:", simulate_day(21040, 21000, 1, bars))
    # side-lock: price spikes UP first to short entry (S178 ~21069) -> short locks, then drops (SL)
    up_bars = [(21050, 21075, 21040), (21060, 21065, 20940)]  # hits S178 short then crashes to longs' zone
    print("short-lock then drop:", simulate_day(21040, 21000, 1, up_bars))
    # loss: long fills then SL
    loss = [(20990, 21000, 20965), (20975, 20980, 20950)]     # fill L078 then SL 20957.3
    print("LOSS long SL:", simulate_day(21040, 21000, 1, loss))
