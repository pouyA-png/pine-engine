"""P10 — Excursion-Tracking: MFE/MAE je Position (Pine: ``nq.track_excursion()``).

Aufruf im Pine-Skript (z. B. einmal oben, jede Bar ist unschaedlich):

    nq.track_excursion()

registriert einen BrokerHook (key ``p10_excursion``). Ab der naechsten Bar
fuehrt er je offener Position das guenstigste und unguenstigste Preisniveau
seit der Fuellung und schreibt beim (Teil-)Schliessen in ``ClosedTrade.extra``:

    extra['mfe']  maximale guenstige Bewegung  in Punkten (>= 0, je Kontrakt)
    extra['mae']  maximale unguenstige Bewegung in Punkten (>= 0, je Kontrakt)

Konservative Regeln (nur Preise, die NACHWEISLICH nach der Fuellung und vor dem
Ausstieg lagen — kein Ueberzeichnen durch unbekannte Reihenfolge in der Bar):
  - Fuellbar: nur Fuellpreis; ihr Hoch/Tief wird AUSGESCHLOSSEN (Reihenfolge
    Fuellung vs. Hoch/Tief unbekannt). Ihr Schlusskurs zaehlt erst, wenn die
    Position die Bar ueberlebt hat (dann zu Beginn der Folgebar).
  - Volle Bars zwischen Fuellung und Ausstieg: Hoch und Tief.
  - Ausstiegsbar: Eroeffnungskurs + Ausstiegspreis (Hoch/Tief der Ausstiegsbar
    NICHT, ausser die Position ueberlebt die Stop/Ziel-Pruefung dieser Bar und
    wird erst per strategy.close/close_all zum Schlusskurs geschlossen — dann
    lag die ganze Bar in der Position).
  - Positionen, die vor der Registrierung schon offen waren, starten beim
    Einstiegspreis ab Registrierung (fruehere Bars fehlen).
Ohne Aufruf aendert sich nichts (kein Hook, byte-identisch).
"""

from __future__ import annotations

from pine_engine.runtime.broker import BrokerHook
from pine_engine.runtime.ext import builtin

_KEY = 'p10_excursion'


def _init(trade):
    ex = trade.extra
    if '_exc_best' not in ex:
        ex['_exc_best'] = trade.entry_price
        ex['_exc_worst'] = trade.entry_price


def _see(trade, px):
    """Preis px lag nachweislich in der Position — Extremwerte aktualisieren."""
    _init(trade)
    ex = trade.extra
    if trade.side == 'long':
        if px > ex['_exc_best']:
            ex['_exc_best'] = px
        if px < ex['_exc_worst']:
            ex['_exc_worst'] = px
    else:
        if px < ex['_exc_best']:
            ex['_exc_best'] = px
        if px > ex['_exc_worst']:
            ex['_exc_worst'] = px


def _mfe_mae(trade):
    _init(trade)
    ex = trade.extra
    e = trade.entry_price
    if trade.side == 'long':
        return max(0.0, ex['_exc_best'] - e), max(0.0, e - ex['_exc_worst'])
    return max(0.0, e - ex['_exc_best']), max(0.0, ex['_exc_worst'] - e)


class ExcursionHook(BrokerHook):
    key = _KEY

    def __init__(self):
        self._prev_close = None
        self._bar_idx = None

    def on_bar_start(self, broker, bar):
        # Alles, was jetzt noch offen ist, hat die Vorbar ueberlebt:
        # deren Schlusskurs (relevant fuer Fuellbars) und die Eroeffnung jetzt.
        for t in broker.open_trades.values():
            if self._prev_close is not None:
                _see(t, self._prev_close)
            _see(t, bar.open)
        self._bar_idx = bar.bar_index

    def on_fill(self, broker, trade, bar):
        trade.extra['_exc_fill_idx'] = bar.bar_index
        _see(trade, trade.entry_price)

    def after_exits(self, broker, bar):
        # Nach der Stop/Ziel-Pruefung noch offen -> ganze Bar lag in der Position,
        # ausser es ist die Fuellbar (Reihenfolge unbekannt).
        for t in broker.open_trades.values():
            if t.extra.get('_exc_fill_idx') == bar.bar_index:
                continue
            _see(t, bar.high)
            _see(t, bar.low)
        self._prev_close = bar.close

    def on_close(self, broker, ct):
        trade = broker.open_trades.get(ct.entry_id)
        if trade is None:          # sollte nicht vorkommen — nur Ausstiegspreis
            best = worst = ct.exit_price
            if ct.side == 'long':
                mfe = max(0.0, best - ct.entry_price)
                mae = max(0.0, ct.entry_price - worst)
            else:
                mfe = max(0.0, ct.entry_price - best)
                mae = max(0.0, worst - ct.entry_price)
        else:
            _see(trade, ct.exit_price)
            mfe, mae = _mfe_mae(trade)
        ct.extra['mfe'] = mfe
        ct.extra['mae'] = mae


@builtin('nq.track_excursion')
def nq_track_excursion(ctx, state):
    """Registriert das MFE/MAE-Tracking (idempotent). Rueckgabe: true."""
    broker = ctx.strategy.broker
    if broker.get_hook(_KEY) is None:
        h = ExcursionHook()
        # Registrierung passiert waehrend der Skriptausfuehrung der Bar:
        # ihr Schlusskurs gilt fuer die Folgebar als "ueberlebt".
        h._prev_close = ctx.bar_close
        broker.add_hook(h)
    return True
