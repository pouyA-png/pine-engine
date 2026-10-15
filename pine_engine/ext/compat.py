"""Kleine Pine-Kompatibilitaetskonstanten ohne eigenes Paket."""

from pine_engine.runtime.ext import constant

# request.security(..., lookahead=barmerge.lookahead_off) — nq_htf lehnt 'on' ab.
constant('barmerge.lookahead_off', 'off')
constant('barmerge.lookahead_on', 'on')
constant('barmerge.gaps_off', 'gaps_off')
constant('barmerge.gaps_on', 'gaps_on')
