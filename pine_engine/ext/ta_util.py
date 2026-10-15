"""P3 — ta.*-Hilfsfunktionen und Oszillatoren (Pine v5, TradingView-Semantik).

Alle Funktionen fuehren ihre eigene History je Aufrufstelle (``state``), sind
also unabhaengig davon, ob das Argument eine Series oder ein Ausdruck ist.
Wie in Pine zaehlt die History nur Bars, auf denen die Aufrufstelle
tatsaechlich ausgefuehrt wurde.

Fenster-Funktionen liefern ``na``, solange noch keine ``length`` Werte
vorliegen (bzw. ``length + 1`` bei rising/falling/percentrank);
rising/falling liefern dann ``false``.
"""

from __future__ import annotations

import math

from pine_engine.runtime.ext import builtin, cur, hist
from pine_engine.runtime.na import NA, is_na


# ── Hilfen ────────────────────────────────────────────────────────────────

def _truthy(x) -> bool:
    x = cur(x)
    if is_na(x):
        return False
    return bool(x)


def _num(x):
    x = cur(x)
    if x is None:
        return NA
    if isinstance(x, bool):
        return float(x)
    return x


def _len(length) -> int:
    n = int(cur(length))
    if n < 1:
        raise ValueError(f'length muss >= 1 sein, ist {n}')
    return n


def _window(state, key, value, n):
    """Letzte n Werte (aeltester zuerst) oder None bei zu wenig History."""
    buf = hist(state, key, value, maxlen=max(5000, n + 1))
    if len(buf) < n:
        return None
    return buf[-n:]


def _step(state, compute):
    """Inkrementeller Zustand mit Pine-Semantik (ein Commit pro Bar).

    ``compute(prev)`` bekommt den festgeschriebenen Zustand der Vorbar und
    liefert (neuer_zustand, rueckgabewert). Mehrfachaufruf in derselben Bar
    rechnet wieder von ``prev`` aus.
    """
    idx = state.get('_bar_idx')
    if state.get('#bar') != idx:
        state['#prev'] = state.get('#cur')
        state['#bar'] = idx
    new, out = compute(state.get('#prev'))
    state['#cur'] = new
    return out


def _nan_to_na(x):
    return NA if (isinstance(x, float) and (math.isnan(x) or math.isinf(x))) else x


# ── 1. ta.barssince ──────────────────────────────────────────────────────

@builtin('ta.barssince')
def ta_barssince(ctx, state, condition):
    """Bars seit der letzten Bar mit condition == true (0 = diese Bar), sonst na."""
    c = _truthy(condition)

    def f(prev):
        if c:
            return 0, 0
        if prev is None:
            return None, NA
        return prev + 1, prev + 1
    return _step(state, f)


# ── 2. ta.valuewhen ──────────────────────────────────────────────────────

@builtin('ta.valuewhen')
def ta_valuewhen(ctx, state, condition, source, occurrence=0):
    """Wert von source an der occurrence-t juengsten Bar mit condition == true."""
    c = _truthy(condition)
    v = cur(source)
    occ = int(cur(occurrence))

    def f(prev):
        vals = list(prev) if prev else []
        if c:
            vals.append(v)
            if len(vals) > 5000:
                del vals[0]
        out = vals[-1 - occ] if 0 <= occ < len(vals) else NA
        return vals, out
    return _step(state, f)


# ── 3. ta.cum ────────────────────────────────────────────────────────────

@builtin('ta.cum')
def ta_cum(ctx, state, source):
    """Laufende Summe von source ueber alle Bars (na-Werte zaehlen als 0)."""
    v = _num(source)

    def f(prev):
        s = 0.0 if prev is None else prev
        if not is_na(v):
            s = s + v
        return s, s
    return _step(state, f)


# ── 4. ta.cross ──────────────────────────────────────────────────────────

@builtin('ta.cross')
def ta_cross(ctx, state, source1, source2):
    """true, wenn source1 source2 in dieser Bar nach oben ODER unten kreuzt."""
    a0, b0 = _num(source1), _num(source2)
    ha = hist(state, 'a', a0)
    hb = hist(state, 'b', b0)
    if len(ha) < 2:
        return False
    a1, b1 = ha[-2], hb[-2]
    if any(is_na(x) for x in (a0, a1, b0, b1)):
        return False
    return (a0 > b0 and a1 <= b1) or (a0 < b0 and a1 >= b1)


@builtin('ta.crossover')
def ta_crossover(ctx, state, source1, source2):
    """true, wenn source1 source2 in dieser Bar nach oben kreuzt (a0 > b0, a1 <= b1)."""
    a0, b0 = _num(source1), _num(source2)
    ha = hist(state, 'a', a0)
    hb = hist(state, 'b', b0)
    if len(ha) < 2:
        return False
    a1, b1 = ha[-2], hb[-2]
    if any(is_na(x) for x in (a0, a1, b0, b1)):
        return False
    return a0 > b0 and a1 <= b1


@builtin('ta.crossunder')
def ta_crossunder(ctx, state, source1, source2):
    """true, wenn source1 source2 in dieser Bar nach unten kreuzt (a0 < b0, a1 >= b1)."""
    a0, b0 = _num(source1), _num(source2)
    ha = hist(state, 'a', a0)
    hb = hist(state, 'b', b0)
    if len(ha) < 2:
        return False
    a1, b1 = ha[-2], hb[-2]
    if any(is_na(x) for x in (a0, a1, b0, b1)):
        return False
    return a0 < b0 and a1 >= b1


# ── 5. ta.rising / ta.falling ────────────────────────────────────────────

def _rise_fall(state, source, length, rising):
    n = _len(length)
    w = _window(state, 's', _num(source), n + 1)
    if w is None:
        return False
    v = w[-1]
    if is_na(v):
        return False
    for p in w[:-1]:
        if is_na(p):
            return False
        if rising and not v > p:
            return False
        if not rising and not v < p:
            return False
    return True


@builtin('ta.rising')
def ta_rising(ctx, state, source, length):
    """true, wenn source jetzt groesser ist als jeder Wert der letzten length Bars."""
    return _rise_fall(state, source, length, True)


@builtin('ta.falling')
def ta_falling(ctx, state, source, length):
    """true, wenn source jetzt kleiner ist als jeder Wert der letzten length Bars."""
    return _rise_fall(state, source, length, False)


# ── 6. ta.highestbars / ta.lowestbars ────────────────────────────────────

def _extreme_bars(state, source, length, highest):
    n = _len(length)
    w = _window(state, 's', _num(source), n)
    if w is None:
        return NA
    best, off = NA, NA
    # Von aktueller Bar rueckwaerts; bei Gleichstand gewinnt die juengste Bar.
    for k in range(n):
        x = w[-1 - k]
        if is_na(x):
            continue
        if is_na(best) or (x > best if highest else x < best):
            best, off = x, -k
    return off


@builtin('ta.highestbars')
def ta_highestbars(ctx, state, source, length):
    """Versatz (<= 0) zur Bar mit dem hoechsten Wert der letzten length Bars."""
    return _extreme_bars(state, source, length, True)


@builtin('ta.lowestbars')
def ta_lowestbars(ctx, state, source, length):
    """Versatz (<= 0) zur Bar mit dem tiefsten Wert der letzten length Bars."""
    return _extreme_bars(state, source, length, False)


# ── 7. ta.range / ta.median / ta.percentrank ─────────────────────────────

def _clean(w):
    return [x for x in w if not is_na(x)]


@builtin('ta.range')
def ta_range(ctx, state, source, length):
    """Hoechster minus tiefster Wert der letzten length Bars (Einheit von source)."""
    n = _len(length)
    w = _window(state, 's', _num(source), n)
    if w is None:
        return NA
    c = _clean(w)
    return max(c) - min(c) if c else NA


@builtin('ta.median')
def ta_median(ctx, state, source, length):
    """Median der letzten length Werte (gerade Anzahl: Mittel der beiden mittleren)."""
    n = _len(length)
    w = _window(state, 's', _num(source), n)
    if w is None:
        return NA
    c = sorted(_clean(w))
    if not c:
        return NA
    m = len(c) // 2
    return c[m] if len(c) % 2 else (c[m - 1] + c[m]) / 2.0


@builtin('ta.percentrank')
def ta_percentrank(ctx, state, source, length):
    """Prozent (0..100) der vorherigen length Werte, die <= dem aktuellen Wert sind."""
    n = _len(length)
    w = _window(state, 's', _num(source), n + 1)
    if w is None:
        return NA
    v = w[-1]
    if is_na(v):
        return NA
    cnt = sum(1 for p in w[:-1] if not is_na(p) and p <= v)
    return 100.0 * cnt / n


# ── 8. ta.stoch ──────────────────────────────────────────────────────────

@builtin('ta.stoch')
def ta_stoch(ctx, state, source, high, low, length):
    """100 * (source - lowest(low, n)) / (highest(high, n) - lowest(low, n))."""
    n = _len(length)
    s = _num(source)
    wh = _window(state, 'h', _num(high), n)
    wl = _window(state, 'l', _num(low), n)
    if wh is None or is_na(s):
        return NA
    ch, cl = _clean(wh), _clean(wl)
    if not ch or not cl:
        return NA
    hh, ll = max(ch), min(cl)
    if hh == ll:
        return NA          # Pine: Division durch 0 -> na
    return 100.0 * (s - ll) / (hh - ll)


# ── 9. ta.cci ────────────────────────────────────────────────────────────

@builtin('ta.cci')
def ta_cci(ctx, state, source, length):
    """(source - sma) / (0.015 * mittlere absolute Abweichung), je length Bars."""
    n = _len(length)
    w = _window(state, 's', _num(source), n)
    if w is None or any(is_na(x) for x in w):
        return NA
    mean = sum(w) / n
    dev = sum(abs(x - mean) for x in w) / n
    if dev == 0:
        return NA          # Pine: Division durch 0 -> na
    return (w[-1] - mean) / (0.015 * dev)


# ── 10. ta.linreg ────────────────────────────────────────────────────────

@builtin('ta.linreg')
def ta_linreg(ctx, state, source, length, offset=0):
    """Kleinste-Quadrate-Gerade ueber length Bars: intercept + slope*(length-1-offset)."""
    n = _len(length)
    off = int(cur(offset))
    w = _window(state, 's', _num(source), n)
    if w is None or any(is_na(x) for x in w):
        return NA
    # x = 0 (aelteste Bar) .. n-1 (aktuelle Bar)
    sx = n * (n - 1) / 2.0
    sxx = (n - 1) * n * (2 * n - 1) / 6.0
    sy = sum(w)
    sxy = sum(i * y for i, y in enumerate(w))
    den = n * sxx - sx * sx
    slope = 0.0 if den == 0 else (n * sxy - sx * sy) / den
    intercept = (sy - slope * sx) / n
    return intercept + slope * (n - 1 - off)


# ── 11. ta.correlation ───────────────────────────────────────────────────

@builtin('ta.correlation')
def ta_correlation(ctx, state, source1, source2, length):
    """Pearson-Korrelation (-1..1) von source1 und source2 ueber length Bars."""
    n = _len(length)
    wa = _window(state, 'a', _num(source1), n)
    wb = _window(state, 'b', _num(source2), n)
    if wa is None or any(is_na(x) for x in wa) or any(is_na(x) for x in wb):
        return NA
    ma, mb = sum(wa) / n, sum(wb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(wa, wb))
    va = sum((x - ma) ** 2 for x in wa)
    vb = sum((y - mb) ** 2 for y in wb)
    if va == 0 or vb == 0:
        return NA
    return _nan_to_na(cov / math.sqrt(va * vb))
