"""Erweiterungs-Registry fuer Pine-Builtins und Broker-Plugins.

Neue Funktionen kommen als eigenes Modul nach ``pine_engine/ext/`` und
registrieren sich dort per Dekorator — codegen.py und broker.py muessen dafuer
nicht angefasst werden.

    from pine_engine.runtime.ext import builtin, variable, constant, cur

    @builtin('ta.ema', series_args=(0,))
    def ta_ema(ctx, state, source, length):
        ...                     # state: dict, eigener Zustand je Aufrufstelle

    @variable('ta.tr')
    def ta_tr(ctx, state): ...  # Pine-Identifier ohne Klammern

    constant('nq.point_value', 20.0)

Aufruf-Semantik:
  - Jede Aufrufstelle im Pine-Code bekommt einen eigenen ``state``-Dict
    (Pine-Semantik: ta.ema(close, 9) an zwei Stellen = zwei unabhaengige EMAs).
  - Argumente an Positionen in ``series_args`` kommen als Series, wenn im
    Pine-Code dort ein Built-in-Series-Name (open/high/low/close/time/bar_index)
    oder eine History-Variable steht, sonst als Einzelwert. ``cur(x)`` liefert
    in beiden Faellen den aktuellen Wert.
  - ``ctx`` ist der RuntimeContext: ctx.bar_open/high/low/close/bar_ts_ms/bar_idx,
    ctx.open/high/low/close (Series), ctx.strategy (StrategyAPI),
    ctx.strategy.broker (BrokerEmulator).

Broker-Plugins (Hooks) haengen sich per ``ctx.strategy.broker.add_hook(obj)``
ein, siehe broker.py (``BrokerHook``).
"""

from __future__ import annotations
import importlib
import pkgutil
from dataclasses import dataclass
from typing import Callable, Dict, Tuple, Any

from pine_engine.runtime.na import NA, is_na
from pine_engine.runtime.series import Series


@dataclass
class Spec:
    fn: Callable
    series_args: Tuple[int, ...] = ()


REGISTRY: Dict[str, Spec] = {}      # Pine-Funktionsname -> Spec
VARIABLES: Dict[str, Callable] = {}  # Pine-Identifier -> fn(ctx, state)
CONSTANTS: Dict[str, Any] = {}       # Pine-Identifier -> Python-Literal


def builtin(name: str, series_args: Tuple[int, ...] = ()):
    def deco(fn):
        if name in REGISTRY:
            raise ValueError(f'ext builtin {name!r} doppelt registriert')
        REGISTRY[name] = Spec(fn, tuple(series_args))
        return fn
    return deco


def variable(name: str):
    def deco(fn):
        if name in VARIABLES:
            raise ValueError(f'ext variable {name!r} doppelt registriert')
        VARIABLES[name] = fn
        return fn
    return deco


def constant(name: str, value):
    if name in CONSTANTS:
        raise ValueError(f'ext constant {name!r} doppelt registriert')
    CONSTANTS[name] = value


def cur(x):
    """Aktueller Wert — egal ob Series oder Einzelwert."""
    return x[0] if isinstance(x, Series) else x


def hist(state: dict, key: str, value, maxlen: int = 5000) -> list:
    """Eigene History je Aufrufstelle (neuester Wert zuletzt), 1x pro Bar.

    Rueckgabe: die Liste. Mehrfachaufruf in derselben Bar ueberschreibt den
    letzten Eintrag statt anzuhaengen (Pine: ein Wert pro Bar).
    """
    buf = state.setdefault(key, [])
    bar = state.get(key + '#bar')
    idx = state.get('_bar_idx')
    if bar is not None and bar == idx and buf:
        buf[-1] = value
    else:
        buf.append(value)
        if len(buf) > maxlen:
            del buf[0]
    state[key + '#bar'] = idx
    return buf


def call(ctx, name: str, site: int, *args, **kwargs):
    st = ctx.ext_states.get(site)
    if st is None:
        st = ctx.ext_states[site] = {}
    st['_bar_idx'] = ctx.bar_idx
    return REGISTRY[name].fn(ctx, st, *args, **kwargs)


def get_var(ctx, name: str, site: int):
    st = ctx.ext_states.get(site)
    if st is None:
        st = ctx.ext_states[site] = {}
    st['_bar_idx'] = ctx.bar_idx
    return VARIABLES[name](ctx, st)


_loaded = False


def load_all():
    """Importiert alle Module unter pine_engine/ext/ (idempotent)."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    import pine_engine.ext as pkg
    for mod in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda m: m.name):
        if not mod.name.startswith('_'):
            importlib.import_module(f'pine_engine.ext.{mod.name}')
