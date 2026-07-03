#!/usr/bin/env python3
"""Diverse, principled leg-detection families. Each: detect(bars,tmin,oi) -> (start,pivot) or None.
bars[i]=[o,h,l,c], tmin=berlin minutes, oi=open_idx. Pivot should sit near the open (recent).
Low-parameter, market-mechanism-motivated — NOT random param soup.
"""

def _win(tmin, oi, lo_m, hi_m):
    ot = tmin[oi]
    return [i for i in range(oi) if lo_m <= ot - tmin[i] <= hi_m]

def _hl(bars, idxs):
    """leg = window high<->low, chronological (pivot = the more-recent extreme)."""
    if len(idxs) < 3: return None
    hi = max(idxs, key=lambda i: bars[i][1]); lo = min(idxs, key=lambda i: bars[i][2])
    if hi == lo: return None
    return (bars[hi][1], bars[lo][2]) if hi <= lo else (bars[lo][2], bars[hi][1])

def _ok(leg):
    return leg if (leg and abs(leg[0] - leg[1]) >= 5) else None

# --- Family 1: recent sub-move window (Cristiano-style) ---
def recent(R):
    def f(b, t, oi): return _ok(_hl(b, _win(t, oi, 0, R)))
    return f

# --- Family 2: full leg window (≈ v25 raw) ---
def fullwin(b, t, oi): return _ok(_hl(b, _win(t, oi, 0, 90)))
def midwin(b, t, oi):  return _ok(_hl(b, _win(t, oi, 0, 45)))

# --- Family 3: sweep-anchored (liquidity grab of a reference range) ---
def sweep(reflo, refhi):
    def f(b, t, oi):
        ri = _win(t, oi, reflo, refhi); wi = _win(t, oi, 0, 90)
        if len(ri) < 3 or len(wi) < 3: return None
        rhi = max(b[i][1] for i in ri); rlo = min(b[i][2] for i in ri)
        up = max(wi, key=lambda i: b[i][1]); dn = min(wi, key=lambda i: b[i][2])
        over = b[up][1] - rhi; under = rlo - b[dn][2]
        if over <= 0 and under <= 0: return _ok(_hl(b, wi))
        if over >= under:
            aft = [i for i in wi if i >= up]; piv = min(aft, key=lambda i: b[i][2]) if aft else up
            return _ok((b[up][1], b[piv][2]))
        aft = [i for i in wi if i >= dn]; piv = max(aft, key=lambda i: b[i][1]) if aft else dn
        return _ok((b[dn][2], b[piv][1]))
    return f

# --- Family 4: displacement origin (biggest-body impulse) ---
def disp_origin(R):
    def f(b, t, oi):
        wi = _win(t, oi, 0, R)
        if len(wi) < 3: return None
        big = max(wi, key=lambda i: abs(b[i][3] - b[i][0]))
        # leg = from the displacement bar's origin to the most-recent opposite extreme
        up = b[big][3] >= b[big][0]
        aft = [i for i in wi if i >= big]
        if not aft: return None
        if up:   # impulse up -> pivot = recent high, start = its low origin
            piv = max(aft, key=lambda i: b[i][1]); return _ok((b[big][2], b[piv][1]))
        piv = min(aft, key=lambda i: b[i][2]); return _ok((b[big][1], b[piv][2]))
    return f

# --- Family 5: close-to-open extreme (pivot in last P min, start opposite in prior S min) ---
def close_open(P, S):
    def f(b, t, oi):
        piv_w = _win(t, oi, 0, P); st_w = _win(t, oi, P, P + S)
        if len(piv_w) < 1 or len(st_w) < 1: return None
        ot = t[oi]
        pv = min(piv_w, key=lambda i: ot - t[i])  # closest to open
        # pivot = the extreme of piv_w that is furthest from start zone; pick by which extreme is more pronounced
        ph = max(piv_w, key=lambda i: b[i][1]); pl = min(piv_w, key=lambda i: b[i][2])
        sh = max(st_w, key=lambda i: b[i][1]); sl = min(st_w, key=lambda i: b[i][2])
        # leg direction: if start-zone high is the extreme -> down leg to recent low
        if (b[sh][1] - b[pl][2]) >= (b[ph][1] - b[sl][2]):
            return _ok((b[sh][1], b[pl][2]))
        return _ok((b[sl][2], b[ph][1]))
    return f

# --- Family 6: largest recent swing (biggest sub-move in last R min) ---
def largest_swing(R):
    def f(b, t, oi):
        wi = _win(t, oi, 0, R)
        if len(wi) < 4: return None
        hi = max(wi, key=lambda i: b[i][1]); lo = min(wi, key=lambda i: b[i][2])
        if hi == lo: return None
        return _ok((b[hi][1], b[lo][2]) if hi <= lo else (b[lo][2], b[hi][1]))
    return f

# --- Family 7: vol-scaled window (R scales with recent range) ---
def vol_window(base, k):
    def f(b, t, oi):
        ref = _win(t, oi, 0, 30)
        if len(ref) < 5: return _ok(_hl(b, _win(t, oi, 0, base)))
        rng = max(b[i][1] for i in ref) - min(b[i][2] for i in ref)
        R = int(max(8, min(40, base + k * (rng / 20.0))))   # wider when volatile
        return _ok(_hl(b, _win(t, oi, 0, R)))
    return f

DETECTORS = {
    "recent_8": recent(8), "recent_10": recent(10), "recent_12": recent(12),
    "recent_15": recent(15), "recent_20": recent(20), "recent_25": recent(25), "recent_30": recent(30),
    "fullwin": fullwin, "midwin": midwin,
    "sweep_overnight": sweep(90, 570), "sweep_preopen": sweep(90, 180), "sweep_asia": sweep(180, 480),
    "disp_origin_15": disp_origin(15), "disp_origin_25": disp_origin(25), "disp_origin_40": disp_origin(40),
    "close_open_3_12": close_open(3, 12), "close_open_5_15": close_open(5, 15), "close_open_5_25": close_open(5, 25),
    "largest_20": largest_swing(20), "largest_30": largest_swing(30), "largest_45": largest_swing(45),
    "vol_10_1": vol_window(10, 1.0), "vol_12_2": vol_window(12, 2.0),
}

if __name__ == "__main__":
    print(f"{len(DETECTORS)} detector hypotheses:", list(DETECTORS))
