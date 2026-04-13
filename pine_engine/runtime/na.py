"""NA (not available) sentinel matching Pine Script's `na` semantics.

Pine's `na` is a null value that propagates through arithmetic:
  na + 5 = na, na > 3 = false (not na), na == na = na (falsy)

We use float('nan') as the sentinel. Python's NaN propagation handles
arithmetic automatically. For boolean/comparison contexts we provide
explicit helper functions.
"""

import math

NA = float('nan')


def is_na(value) -> bool:
    """Pine's na() — check if value is na/None."""
    if value is None:
        return True
    if isinstance(value, float):
        return math.isnan(value)
    return False


def na_default(value, default):
    """Return value if not na, else default. Equivalent to Pine's nz()."""
    return default if is_na(value) else value


# ── NA-aware arithmetic ──

def pine_add(a, b):
    if is_na(a) or is_na(b):
        return NA
    return a + b


def pine_sub(a, b):
    if is_na(a) or is_na(b):
        return NA
    return a - b


def pine_mul(a, b):
    if is_na(a) or is_na(b):
        return NA
    return a * b


def pine_div(a, b):
    if is_na(a) or is_na(b) or b == 0:
        return NA
    return a / b


# ── NA-aware comparison (Pine comparisons with na return false, not na) ──

def pine_eq(a, b):
    if is_na(a) or is_na(b):
        return False
    return a == b


def pine_neq(a, b):
    if is_na(a) or is_na(b):
        return False
    return a != b


def pine_lt(a, b):
    if is_na(a) or is_na(b):
        return False
    return a < b


def pine_gt(a, b):
    if is_na(a) or is_na(b):
        return False
    return a > b


def pine_lte(a, b):
    if is_na(a) or is_na(b):
        return False
    return a <= b


def pine_gte(a, b):
    if is_na(a) or is_na(b):
        return False
    return a >= b


# ── NA-aware boolean logic ──
# Pine: `na and true` → na (falsy), `na or true` → true
# Python: `float('nan') and True` → True (WRONG)
# So we must wrap these.

def pine_and(a, b):
    """Pine's `and` — if either operand is na/falsy, return false."""
    if is_na(a):
        return False
    if not a:
        return False
    if is_na(b):
        return False
    return bool(b)


def pine_or(a, b):
    """Pine's `or` — if first is truthy return true, else check second."""
    if not is_na(a) and a:
        return True
    if not is_na(b) and b:
        return True
    return False


def pine_not(a):
    """Pine's `not` — na → true (since na is falsy), else normal not."""
    if is_na(a):
        return True
    return not a


# ── NA-aware math wrappers ──

def pine_abs(a):
    if is_na(a):
        return NA
    return abs(a)


def pine_min(a, b):
    if is_na(a):
        return b
    if is_na(b):
        return a
    return min(a, b)


def pine_max(a, b):
    if is_na(a):
        return b
    if is_na(b):
        return a
    return max(a, b)


def pine_round(a, precision=0):
    """Pine's math.round — half-away-from-zero (not banker's rounding)."""
    if is_na(a):
        return NA
    factor = 10 ** precision
    scaled = a * factor
    if scaled >= 0:
        return math.floor(scaled + 0.5) / factor
    return -math.floor(-scaled + 0.5) / factor


def pine_floor(a):
    if is_na(a):
        return NA
    return math.floor(a)
