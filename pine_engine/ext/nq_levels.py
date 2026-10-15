"""P11 — Leg-/Level-Geometrie fuer die NQ-Leg-Strategie (Namensraum ``nq.lvl_*``).

Reine, deterministische Rechenfunktionen ohne Zustand und ohne Lookahead
(sie lesen keine Bar-Daten). Alle Preise und Abstaende in NQ-Punkten.
Jedes na-Argument liefert na (Pine-Semantik).

Leg-Konvention (notes/spec.md §6): ``price(level) = endP + level * (startP - endP)``.
In den Helfern heisst ``a`` der Preis bei Ratio 0,00 (= Leg-Ende ``endP``) und
``b`` der Preis bei Ratio 1,00 (= Leg-Start ``startP``). Damit ist
``nq.lvl_fib(endP, startP, r)`` exakt ``lvl_r`` des Bots, fuer DOWN- und UP-Legs.

Nudge-Richtung (spec §7/§8): Entry-Nudge Richtung 0,50 = "leichtere/fruehere
Fuellung". Long-Limit liegt unter dem Markt -> +pts, Short-Limit darueber -> -pts.
Fuer ein TP-Limit (Gegenrichtung) ruft man ``nq.lvl_nudge(tp, not is_long, pts)``:
Long-TP ``lvl_100 - tpNudge``, Short-TP ``lvl_000 + tpNudge`` wie spec §9.
"""

from __future__ import annotations

import math

from pine_engine.runtime.ext import builtin, cur
from pine_engine.runtime.na import NA, is_na

_EPS = 1e-9          # wie ceil05() im Bot: math.ceil(x / 0.5 - 0.000000001) * 0.5
TICK = 0.25          # NQ-Tickgroesse in Punkten


def _v(x):
    x = cur(x)
    if x is None:
        return NA
    if isinstance(x, bool):
        return float(x)
    return x


def _any_na(*xs) -> bool:
    return any(is_na(x) for x in xs)


def _b(x) -> bool:
    x = cur(x)
    return False if is_na(x) else bool(x)


# ── 1. nq.lvl_fib ────────────────────────────────────────────────────────

@builtin('nq.lvl_fib')
def lvl_fib(ctx, state, a, b, ratio):
    """Preis auf dem Leg: a + ratio * (b - a)  (a = Ratio 0, b = Ratio 1)."""
    a, b, r = _v(a), _v(b), _v(ratio)
    if _any_na(a, b, r):
        return NA
    return a + r * (b - a)


# ── 2. nq.lvl_ratio ──────────────────────────────────────────────────────

@builtin('nq.lvl_ratio')
def lvl_ratio(ctx, state, a, b, price):
    """Position eines Preises im Leg: (price - a) / (b - a); na bei a == b."""
    a, b, p = _v(a), _v(b), _v(price)
    if _any_na(a, b, p) or b == a:
        return NA
    return (p - a) / (b - a)


# ── 3. nq.lvl_min_target ─────────────────────────────────────────────────

@builtin('nq.lvl_min_target')
def lvl_min_target(ctx, state, entry, tp_geo, is_long, min_pts=150.0):
    """Endziel mit Mindestlauf: Long max(tp, entry+min), Short min(tp, entry-min).

    ``entry`` ist der tatsaechliche Einstieg inkl. Nudge (CLAUDE.md). Ist
    ``tp_geo`` na, wird nur der Mindestlauf zurueckgegeben.
    """
    e, t, m = _v(entry), _v(tp_geo), _v(min_pts)
    if _any_na(e, m):
        return NA
    if _b(is_long):
        floor_tp = e + m
        return floor_tp if is_na(t) else max(t, floor_tp)
    floor_tp = e - m
    return floor_tp if is_na(t) else min(t, floor_tp)


# ── 4. nq.lvl_half_neighbor_stop ─────────────────────────────────────────

@builtin('nq.lvl_half_neighbor_stop')
def lvl_half_neighbor_stop(ctx, state, level, neighbor_level, is_long, factor=0.5):
    """Stoppreis ab LEVEL geankert (spec §8): factor * |level - neighbor| hinter dem Level.

    Long: level - d, Short: level + d. Die Seite folgt is_long, nicht der Lage
    des Nachbarlevels (der Nachbar liefert nur den Abstand).
    """
    lv, nb, f = _v(level), _v(neighbor_level), _v(factor)
    if _any_na(lv, nb, f):
        return NA
    d = abs(lv - nb) * f
    return lv - d if _b(is_long) else lv + d


# ── 5. nq.lvl_nudge ──────────────────────────────────────────────────────

@builtin('nq.lvl_nudge')
def lvl_nudge(ctx, state, price, is_long, pts):
    """Limit Richtung fruehere Fuellung schieben: Long +pts, Short -pts."""
    p, n = _v(price), _v(pts)
    if _any_na(p, n):
        return NA
    return p + n if _b(is_long) else p - n


# ── 6. nq.lvl_round_tick ─────────────────────────────────────────────────

@builtin('nq.lvl_round_tick')
def lvl_round_tick(ctx, state, price, mode='near', tick=TICK):
    """Auf Tickraster runden. mode: "near" (Gleichstand nach oben), "up", "down".

    Toleranz 1e-9 Ticks wie ceil05() im Bot, damit 12.5000000001 nicht auf 12.75
    springt. Mit tick=0.5 und mode="up" entspricht es ceil05().
    """
    p, t = _v(price), _v(tick)
    m = cur(mode)
    if _any_na(p, t) or t <= 0:
        return NA
    x = p / t
    if m == 'up':
        k = math.ceil(x - _EPS)
    elif m == 'down':
        k = math.floor(x + _EPS)
    elif m == 'near':
        k = math.floor(x + 0.5 + _EPS)
    else:
        raise ValueError(f'nq.lvl_round_tick: mode {m!r} unbekannt (near/up/down)')
    return k * t


# ── 7. nq.lvl_r_multiple ─────────────────────────────────────────────────

@builtin('nq.lvl_r_multiple')
def lvl_r_multiple(ctx, state, entry, stop, price, is_long):
    """Gewinn bis price in R, R = |entry - stop| (vor Kosten). na bei Risiko 0."""
    e, s, p = _v(entry), _v(stop), _v(price)
    if _any_na(e, s, p):
        return NA
    risk = abs(e - s)
    if risk == 0:
        return NA
    return (p - e) / risk if _b(is_long) else (e - p) / risk


# ── 8. nq.lvl_qty_split ──────────────────────────────────────────────────

@builtin('nq.lvl_qty_split')
def lvl_qty_split(ctx, state, total, parts, index):
    """Ganzzahlige Menge fuer Teilposition index (0-basiert); Rest auf index 0.

    Beispiel 7 auf 3 Teile -> [3, 2, 2]. na bei ungueltigem index/parts.
    """
    tot, n, i = _v(total), _v(parts), _v(index)
    if _any_na(tot, n, i):
        return NA
    tot, n, i = int(tot), int(n), int(i)
    if n < 1 or i < 0 or i >= n or tot < 0:
        return NA
    base, rest = divmod(tot, n)
    return base + rest if i == 0 else base


# ── 9. nq.lvl_nearest ────────────────────────────────────────────────────

@builtin('nq.lvl_nearest')
def lvl_nearest(ctx, state, price, step, anchor=0.0):
    """Naechstes Level des Rasters anchor + k*step (Gleichstand nach oben)."""
    p, st, an = _v(price), _v(step), _v(anchor)
    if _any_na(p, st, an) or st <= 0:
        return NA
    k = math.floor((p - an) / st + 0.5 + _EPS)
    return an + k * st


# ── 10. nq.lvl_leg_size / nq.lvl_tp1_mid ─────────────────────────────────

@builtin('nq.lvl_leg_size')
def lvl_leg_size(ctx, state, a, b):
    """Leggroesse |b - a| in Punkten."""
    a, b = _v(a), _v(b)
    if _any_na(a, b):
        return NA
    return abs(b - a)


@builtin('nq.lvl_tp1_mid')
def lvl_tp1_mid(ctx, state, a, b, is_outer, is_long):
    """Geometrisches TP1 (CLAUDE.md "Geometrie vor Tagesauswahl", spec §9).

    Aeusserer Entry (-1,40 / 2,54) -> Mitte 0,50. Innerer Entry (-0,78 / 1,78)
    -> gegenueberliegender Anker: Long max(a, b), Short min(a, b). Das
    reproduziert Long_078 -> lvl_100 und Short_178 -> lvl_000 im DOWN-Leg sowie
    UP-Leg-Short (an -0,78) -> lvl_100. tpNudge nicht enthalten (spec: 0,50 ohne
    Nudge; Anker-TP per nq.lvl_nudge(tp, not is_long, tpNudge)).
    """
    a, b = _v(a), _v(b)
    if _any_na(a, b):
        return NA
    if _b(is_outer):
        return (a + b) / 2.0
    return max(a, b) if _b(is_long) else min(a, b)
