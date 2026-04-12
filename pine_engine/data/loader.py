"""Data loader for 1-minute OHLC CSV files and tick data.

Loads bar data into a list of Bar objects for the engine to consume.
Supports the NQ continuous 1-min format from Databento/TradingView exports.
"""

from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

import csv

from pine_engine.runtime.broker import Bar

NY_TZ = ZoneInfo("America/New_York")


def load_bars_csv(filepath: str,
                  start_date: Optional[str] = None,
                  end_date: Optional[str] = None,
                  date_format: str = "auto") -> List[Bar]:
    """Load 1-minute OHLC bars from CSV.

    Expected CSV columns (flexible order via header):
      datetime/date/time, open, high, low, close [, volume, symbol]

    Args:
        filepath: Path to CSV file
        start_date: Optional filter "YYYY-MM-DD" (inclusive)
        end_date: Optional filter "YYYY-MM-DD" (inclusive)
        date_format: "auto" to detect, or strftime format string

    Returns:
        List of Bar objects sorted by timestamp
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {filepath}")

    bars: List[Bar] = []
    bar_index = 0

    # Parse date filters
    start_dt = (datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if start_date else None)
    end_dt = (datetime.strptime(end_date, "%Y-%m-%d").replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc)
              if end_date else None)

    with open(path, 'r', newline='') as f:
        reader = csv.DictReader(f)

        # Find the datetime column (flexible naming)
        dt_col = None
        for col in reader.fieldnames or []:
            if col.lower() in ('datetime', 'date', 'time', 'timestamp'):
                dt_col = col
                break
        if dt_col is None:
            raise ValueError(f"No datetime column found. Headers: {reader.fieldnames}")

        # Find OHLC columns (case-insensitive)
        header_map = {c.lower(): c for c in (reader.fieldnames or [])}
        o_col = header_map.get('open', '')
        h_col = header_map.get('high', '')
        l_col = header_map.get('low', '')
        c_col = header_map.get('close', '')

        if not all([o_col, h_col, l_col, c_col]):
            raise ValueError(f"Missing OHLC columns. Headers: {reader.fieldnames}")

        for row in reader:
            dt_str = row[dt_col].strip()

            # Auto-detect format
            try:
                if '+' in dt_str or 'Z' in dt_str:
                    # ISO format with timezone
                    dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                elif 'T' in dt_str:
                    dt = datetime.fromisoformat(dt_str)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                else:
                    # Try common formats
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                                "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M"):
                        try:
                            dt = datetime.strptime(dt_str, fmt)
                            dt = dt.replace(tzinfo=timezone.utc)
                            break
                        except ValueError:
                            continue
                    else:
                        continue  # Skip unparseable rows
            except (ValueError, TypeError):
                continue

            # Apply date filters
            if start_dt and dt < start_dt:
                continue
            if end_dt and dt > end_dt:
                continue

            try:
                bar = Bar(
                    timestamp=dt,
                    open=float(row[o_col]),
                    high=float(row[h_col]),
                    low=float(row[l_col]),
                    close=float(row[c_col]),
                    bar_index=bar_index)
                bars.append(bar)
                bar_index += 1
            except (ValueError, KeyError):
                continue

    return bars


def bar_timestamp_ms(bar: Bar) -> int:
    """Convert bar timestamp to Unix milliseconds (Pine's `time` format)."""
    return int(bar.timestamp.timestamp() * 1000)
