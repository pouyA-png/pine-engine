"""Series type — the core of Pine Script's execution model.

Every variable in Pine is implicitly a time-series. series[0] is the
current bar's value, series[1] is the previous bar, series[N] is N bars ago.

This implementation uses a simple list as a ring buffer with a configurable
max lookback to bound memory usage.
"""

from pine_engine.runtime.na import NA, is_na


class Series:
    """Time-series with Pine Script history access semantics.

    Append one value per bar. Access via [offset]:
      series[0] = current bar (most recent append)
      series[1] = previous bar
      series[N] = N bars ago
    Out-of-bounds returns NA.
    """

    __slots__ = ('_data', '_max_lookback')

    def __init__(self, max_lookback: int = 500):
        self._data: list = []
        self._max_lookback = max_lookback

    def append(self, value):
        """Add the current bar's value to the series."""
        self._data.append(value)
        if len(self._data) > self._max_lookback:
            self._data.pop(0)

    def __getitem__(self, offset: int):
        """Pine-style history access: series[0]=current, series[1]=prev, etc."""
        if offset < 0:
            return NA
        idx = len(self._data) - 1 - offset
        if idx < 0:
            return NA
        return self._data[idx]

    def __setitem__(self, offset: int, value):
        """Allow overwriting the current bar value (offset=0)."""
        if offset == 0 and len(self._data) > 0:
            self._data[-1] = value
        elif offset > 0:
            idx = len(self._data) - 1 - offset
            if 0 <= idx < len(self._data):
                self._data[idx] = value

    @property
    def current(self):
        """Shortcut for series[0]."""
        return self._data[-1] if self._data else NA

    def __len__(self):
        return len(self._data)

    def __repr__(self):
        if len(self._data) == 0:
            return "Series(empty)"
        return f"Series(current={self.current}, len={len(self._data)})"

    def highest(self, length: int):
        """ta.highest equivalent — max of last `length` values."""
        result = NA
        for i in range(length):
            v = self[i]
            if is_na(v):
                continue
            if is_na(result) or v > result:
                result = v
        return result

    def lowest(self, length: int):
        """ta.lowest equivalent — min of last `length` values."""
        result = NA
        for i in range(length):
            v = self[i]
            if is_na(v):
                continue
            if is_na(result) or v < result:
                result = v
        return result
