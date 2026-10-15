"""ta.* — gleitende Durchschnitte und Volatilitaet (Paket P2).

Pine-v5-Semantik, Zustand je Aufrufstelle (eigene History via ``hist``), damit
auch Ausdruecke (``ta.ema(high-low, 3)``) als Quelle funktionieren und die
300-Bar-Grenze der Quell-Series keine Rolle spielt.

Anlauf/Seed (TradingView-Builtins):
  - sma/wma/stdev/dev/change/mom/roc: na, bis genug Werte da sind.
  - ema: na fuer die ersten length-1 Bars, erster Wert = SMA der ersten
    length Werte, danach alpha = 2/(length+1).
  - rma: wie ema, alpha = 1/length (Pine-Doku: ``na(sum[1]) ? ta.sma(src,
    length) : alpha*src + (1-alpha)*nz(sum[1])``).
  - na in der Quelle: Fensterfunktionen liefern na, solange ein na im Fenster
    liegt; ema/rma liefern bei na-Quelle na und behalten ihren Zustand.
Kein Volumen in den Bars -> ta.vwma wird bewusst nicht angeboten.
"""

from __future__ import annotations
import math

from pine_engine.runtime.ext import builtin, variable, cur, hist
from pine_engine.runtime.na import NA, is_na


# ── Helfer ──────────────────────────────────────────────────────────────

def _len(length) -> int:
    n = cur(length)
    if is_na(n):
        raise ValueError('ta: length ist na')
    n = int(n)
    if n < 1:
        raise ValueError(f'ta: length muss >= 1 sein, ist {n}')
    return n


def _val(x):
    v = cur(x)
    return NA if v is None else v


def _window(state, key, src, n, extra=0):
    """Haengt src an die eigene History und liefert die letzten n(+extra) Werte
    (aeltester zuerst) oder None, wenn noch zu wenig oder na im Fenster."""
    buf = hist(state, key, _val(src), maxlen=n + extra + 1)
    if len(buf) < n + extra:
        return None
    w = buf[-(n + extra):]
    for v in w:
        if is_na(v):
            return None
    return w


def _sma(state, key, src, n):
    w = _window(state, key, src, n)
    return NA if w is None else sum(w) / n


def _wma(state, key, src, n):
    w = _window(state, key, src, n)
    if w is None:
        return NA
    # w[-1] = aktueller Wert, Gewicht n; aeltester Gewicht 1
    num = sum(v * (i + 1) for i, v in enumerate(w))
    return num / (n * (n + 1) / 2)


def _smoothed(state, key, src, n, alpha):
    """ema/rma: SMA-Seed ueber die ersten n gueltigen Werte, dann Rekursion.
    Mehrfachaufruf in derselben Bar rechnet vom Stand der Vorbar."""
    idx = state.get('_bar_idx')
    st = state.setdefault(key, {'prev': NA, 'seed': [], 'bar': None,
                                'prev_before': NA, 'seed_before': []})
    if st['bar'] == idx:                     # gleiche Bar erneut -> zurueckrollen
        st['prev'] = st['prev_before']
        st['seed'] = list(st['seed_before'])
    else:
        st['prev_before'] = st['prev']
        st['seed_before'] = list(st['seed'])
        st['bar'] = idx
    v = _val(src)
    if is_na(v):
        return NA
    if is_na(st['prev']):
        st['seed'].append(v)
        if len(st['seed']) > n:
            del st['seed'][0]
        if len(st['seed']) < n:
            return NA
        st['prev'] = sum(st['seed']) / n
        st['seed'] = []
        return st['prev']
    st['prev'] = alpha * v + (1.0 - alpha) * st['prev']
    return st['prev']


def _tr(ctx, handle_na: bool):
    h, l = ctx.bar_high, ctx.bar_low
    pc = ctx.close[1]
    if is_na(pc):
        return (h - l) if handle_na else NA
    return max(h - l, abs(h - pc), abs(l - pc))


# ── Durchschnitte ───────────────────────────────────────────────────────

@builtin('ta.sma', series_args=(0,))
def ta_sma(ctx, state, source, length):
    """Einfacher Durchschnitt der letzten length Werte."""
    return _sma(state, 'src', source, _len(length))


@builtin('ta.ema', series_args=(0,))
def ta_ema(ctx, state, source, length):
    """Exponentieller Durchschnitt, alpha = 2/(length+1), SMA-Seed."""
    n = _len(length)
    return _smoothed(state, 'ema', source, n, 2.0 / (n + 1))


@builtin('ta.rma', series_args=(0,))
def ta_rma(ctx, state, source, length):
    """Wilder-Glaettung (RMA), alpha = 1/length, SMA-Seed."""
    n = _len(length)
    return _smoothed(state, 'rma', source, n, 1.0 / n)


@builtin('ta.wma', series_args=(0,))
def ta_wma(ctx, state, source, length):
    """Linear gewichteter Durchschnitt (neuester Wert Gewicht length)."""
    return _wma(state, 'src', source, _len(length))


@builtin('ta.hma', series_args=(0,))
def ta_hma(ctx, state, source, length):
    """Hull MA: wma(2*wma(src, n/2) - wma(src, n), floor(sqrt(n)))."""
    n = _len(length)
    half = max(1, n // 2)
    sq = max(1, int(math.floor(math.sqrt(n))))
    a = _wma(state, 'half', source, half)
    b = _wma(state, 'full', source, n)
    d = NA if (is_na(a) or is_na(b)) else 2.0 * a - b
    return _wma(state, 'diff', d, sq)


# ── Volatilitaet ────────────────────────────────────────────────────────

@variable('ta.tr')
def ta_tr_var(ctx, state):
    """True Range als Variable = ta.tr(false): erste Bar na."""
    return _tr(ctx, False)


@builtin('ta.tr')
def ta_tr(ctx, state, handle_na=False):
    """True Range; handle_na=true -> erste Bar high-low statt na."""
    return _tr(ctx, bool(cur(handle_na)))


@builtin('ta.atr')
def ta_atr(ctx, state, length):
    """Average True Range = rma(tr(true), length)."""
    n = _len(length)
    return _smoothed(state, 'atr', _tr(ctx, True), n, 1.0 / n)


@builtin('ta.stdev', series_args=(0,))
def ta_stdev(ctx, state, source, length, biased=True):
    """Standardabweichung; biased=true (Default) teilt durch length, sonst length-1."""
    n = _len(length)
    w = _window(state, 'src', source, n)
    if w is None:
        return NA
    m = sum(w) / n
    ss = sum((v - m) ** 2 for v in w)
    if cur(biased):
        return math.sqrt(ss / n)
    return NA if n < 2 else math.sqrt(ss / (n - 1))


@builtin('ta.dev', series_args=(0,))
def ta_dev(ctx, state, source, length):
    """Mittlere absolute Abweichung vom SMA der letzten length Werte."""
    n = _len(length)
    w = _window(state, 'src', source, n)
    if w is None:
        return NA
    m = sum(w) / n
    return sum(abs(v - m) for v in w) / n


# ── Differenzen ─────────────────────────────────────────────────────────

def _diff(state, source, n):
    """(aktueller Wert, Wert vor n Bars) aus eigener History oder None."""
    buf = hist(state, 'src', _val(source), maxlen=n + 2)
    if len(buf) < n + 1:
        return None
    a, b = buf[-1], buf[-1 - n]
    if is_na(a) or is_na(b):
        return None
    return a, b


@builtin('ta.change', series_args=(0,))
def ta_change(ctx, state, source, length=1):
    """source - source[length] (Default length=1)."""
    n = int(cur(length))
    if n < 0:
        raise ValueError('ta.change: length muss >= 0 sein')
    p = _diff(state, source, n)
    return NA if p is None else p[0] - p[1]


@builtin('ta.mom', series_args=(0,))
def ta_mom(ctx, state, source, length):
    """Momentum = source - source[length]."""
    p = _diff(state, source, _len(length))
    return NA if p is None else p[0] - p[1]


@builtin('ta.roc', series_args=(0,))
def ta_roc(ctx, state, source, length):
    """Rate of Change in Prozent = 100*(source - source[length])/source[length]."""
    p = _diff(state, source, _len(length))
    if p is None or p[1] == 0:
        return NA
    return 100.0 * (p[0] - p[1]) / p[1]
