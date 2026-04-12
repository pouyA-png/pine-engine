"""Parameter grid generation for batch sweeps."""

from __future__ import annotations
from typing import Dict, List, Any
from itertools import product


def generate_grid(param_ranges: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
    """Generate all combinations of parameter values.

    Args:
        param_ranges: Dict of param_name → list of values
            e.g., {"slPoints": [8.0, 10.5, 13.0], "pivotLeft": [1, 2, 3]}

    Returns:
        List of parameter dictionaries, one per combination
    """
    keys = list(param_ranges.keys())
    values = list(param_ranges.values())
    combos = list(product(*values))
    return [dict(zip(keys, combo)) for combo in combos]


def generate_range(start: float, end: float, step: float) -> List[float]:
    """Generate a range of float values (inclusive of end if reached)."""
    values = []
    v = start
    while v <= end + step * 0.001:  # Small epsilon for float comparison
        values.append(round(v, 6))
        v += step
    return values


def estimate_grid_size(param_ranges: Dict[str, List[Any]]) -> int:
    """Estimate total number of parameter combinations."""
    total = 1
    for values in param_ranges.values():
        total *= len(values)
    return total
