"""Built-in Pine Script functions — only the ~20 functions used by the trading bot.

All functions operate on Series objects and respect NA propagation.
Time functions convert Unix ms timestamps to America/New_York components.
"""

from __future__ import annotations

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

from datetime import datetime, timezone
from pine_engine.runtime.na import NA, is_na
from pine_engine.runtime.series import Series

NY_TZ = ZoneInfo("America/New_York")


def pine_str_tostring(x, fmt=None):
    """Pine str.tostring. 1-arg == plain str() (unchanged). 2-arg honors a numeric format
    string like "#.##"/"0.00" (count of '#'/'0' after the dot = fractional digits)."""
    if fmt is None:
        return str(x)
    if isinstance(fmt, str) and '.' in fmt:
        ndec = sum(1 for c in fmt.split('.', 1)[1] if c in '#0')
        try:
            return f"{float(x):.{ndec}f}"
        except (TypeError, ValueError):
            return str(x)
    if isinstance(fmt, str) and fmt.strip() in ('0', '#'):
        try:
            return f"{float(x):.0f}"
        except (TypeError, ValueError):
            return str(x)
    return str(x)


# ═══════════════════════════════════════════════════════════════════════════════
# TIME FUNCTIONS — all take Unix ms timestamp + timezone string
# ═══════════════════════════════════════════════════════════════════════════════

def _ts_to_ny(timestamp_ms) -> datetime:
    """Convert Unix ms to NY datetime. Handles NA."""
    if is_na(timestamp_ms):
        return None
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=NY_TZ)


def pine_hour(timestamp_ms, tz_str="America/New_York") -> int:
    dt = _ts_to_ny(timestamp_ms)
    return NA if dt is None else dt.hour


def pine_minute(timestamp_ms, tz_str="America/New_York") -> int:
    dt = _ts_to_ny(timestamp_ms)
    return NA if dt is None else dt.minute


def pine_dayofweek(timestamp_ms, tz_str="America/New_York") -> int:
    """Pine dayofweek: 1=Sunday, 2=Monday, ..., 7=Saturday.
    Python isoweekday: 1=Monday, ..., 7=Sunday.
    Mapping: (iso % 7) + 1
    """
    dt = _ts_to_ny(timestamp_ms)
    if dt is None:
        return NA
    iso = dt.isoweekday()  # 1=Mon, 7=Sun
    return (iso % 7) + 1   # 1=Sun, 2=Mon, ..., 7=Sat


def pine_year(timestamp_ms, tz_str="America/New_York") -> int:
    dt = _ts_to_ny(timestamp_ms)
    return NA if dt is None else dt.year


def pine_month(timestamp_ms, tz_str="America/New_York") -> int:
    dt = _ts_to_ny(timestamp_ms)
    return NA if dt is None else dt.month


def pine_dayofmonth(timestamp_ms, tz_str="America/New_York") -> int:
    dt = _ts_to_ny(timestamp_ms)
    return NA if dt is None else dt.day


# Pine constants
DAYOFWEEK_SUNDAY    = 1
DAYOFWEEK_MONDAY    = 2
DAYOFWEEK_TUESDAY   = 3
DAYOFWEEK_WEDNESDAY = 4
DAYOFWEEK_THURSDAY  = 5
DAYOFWEEK_FRIDAY    = 6
DAYOFWEEK_SATURDAY  = 7


# ═══════════════════════════════════════════════════════════════════════════════
# TECHNICAL ANALYSIS FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def ta_pivothigh(source: Series, leftbars, rightbars):
    """ta.pivothigh — detect a pivot high with confirmation delay.

    At the current bar, check if source[rightbars] (the candidate bar,
    which is `rightbars` bars ago) is >= all bars in the window
    [rightbars-leftbars .. rightbars+rightbars], excluding itself.

    Returns the pivot value if found, else NA.
    The pivot "fires" rightbars after the actual pivot bar.
    """
    leftbars = int(leftbars)
    rightbars = int(rightbars)
    if len(source) < leftbars + rightbars + 1:
        return NA

    pivot_val = source[rightbars]
    if is_na(pivot_val):
        return NA

    # Check left side: source[rightbars+1] .. source[rightbars+leftbars]
    for i in range(1, leftbars + 1):
        v = source[rightbars + i]
        if is_na(v):
            return NA
        if v > pivot_val:
            return NA

    # Check right side: source[rightbars-1] .. source[0]
    # For a HIGH pivot, the candidate must be strictly > right side
    for i in range(1, rightbars + 1):
        v = source[rightbars - i]
        if is_na(v):
            return NA
        if v >= pivot_val:
            return NA

    return pivot_val


def ta_pivotlow(source: Series, leftbars, rightbars):
    """ta.pivotlow — detect a pivot low with confirmation delay.

    Mirror of ta_pivothigh. Returns pivot value if source[rightbars]
    is <= all surrounding bars.
    """
    leftbars = int(leftbars)
    rightbars = int(rightbars)
    if len(source) < leftbars + rightbars + 1:
        return NA

    pivot_val = source[rightbars]
    if is_na(pivot_val):
        return NA

    # Check left side
    for i in range(1, leftbars + 1):
        v = source[rightbars + i]
        if is_na(v):
            return NA
        if v < pivot_val:
            return NA

    # Check right side (strictly less)
    for i in range(1, rightbars + 1):
        v = source[rightbars - i]
        if is_na(v):
            return NA
        if v <= pivot_val:
            return NA

    return pivot_val


def ta_highest(source: Series, length):
    """ta.highest — maximum value in the last `length` bars."""
    length = int(length)
    result = NA
    for i in range(length):
        v = source[i]
        if is_na(v):
            continue
        if is_na(result) or v > result:
            result = v
    return result


def ta_lowest(source: Series, length):
    """ta.lowest — minimum value in the last `length` bars."""
    length = int(length)
    result = NA
    for i in range(length):
        v = source[i]
        if is_na(v):
            continue
        if is_na(result) or v < result:
            result = v
    return result


def ta_rsi(source: Series, length: int):
    """ta.rsi — Relative Strength Index using Wilder's smoothing.

    Only needed for levels_debug.pine, not the main bot.
    """
    if len(source) < length + 1:
        return NA

    # Calculate initial average gain/loss
    gains = 0.0
    losses = 0.0
    for i in range(length):
        diff = source[i] - source[i + 1] if not is_na(source[i + 1]) else 0
        if is_na(source[i]):
            return NA
        if diff > 0:
            gains += diff
        else:
            losses += abs(diff)

    avg_gain = gains / length
    avg_loss = losses / length

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def ta_crossover(a, b) -> bool:
    """ta.crossover — true when `a` crosses above `b`."""
    # Current: a > b, Previous: a <= b
    # a and b can be Series or scalars
    a0 = a[0] if isinstance(a, Series) else a
    a1 = a[1] if isinstance(a, Series) else a
    b0 = b[0] if isinstance(b, Series) else b
    b1 = b[1] if isinstance(b, Series) else b

    if any(is_na(x) for x in [a0, a1, b0, b1]):
        return False
    return a0 > b0 and a1 <= b1


def ta_crossunder(a, b) -> bool:
    """ta.crossunder — true when `a` crosses below `b`."""
    a0 = a[0] if isinstance(a, Series) else a
    a1 = a[1] if isinstance(a, Series) else a
    b0 = b[0] if isinstance(b, Series) else b
    b1 = b[1] if isinstance(b, Series) else b

    if any(is_na(x) for x in [a0, a1, b0, b1]):
        return False
    return a0 < b0 and a1 >= b1
