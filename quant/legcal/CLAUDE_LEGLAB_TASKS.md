# TASKS — leglab "claude account" + auto-trade-draw + magnet + new bot

GOAL: Neuer Leg-Selektions-Bot aus Claudes per-Tag Best-Leg-Picks (CME, visuell nach Pattern).
Plus 2 leglab-Features (Auto-Trade-Zeichnen wie TradingView + schwacher Magnet) + 3. Konto "claude".
"Beides" (Q1): hardcoded Best-Leg-Decke + Vor-Open-Regel walk-forward validiert.

## INVARIANTEN (hart)
- Cristianos CME-Labels (258, by:cristiano in labels.json cme/ftmo) NIE überschreiben.
  -> claude schreibt in SEPARATE Stores: ftmo_claude / cme_claude. ftmo/cme bleiben unberührt.
- progress_notes.md nur append. backup_debug.txt hands-off. Trading-Files brauchen PW 9090Gucci.
- Optimierung/Backtests nur letztes 1 Jahr (feedback_backtest_last_year).

## TRADE-MODELL (verifiziert aus scratchpad/bot_lastyear.pine, kein PW nötig)
Levels: range=startP-endP (endP=pivot=0.00, startP=1.00)
 n140=endP-1.40r · n078=endP-0.78r · 000=endP · 050=endP+0.5r · 100=startP · 178=endP+1.78r · 254=endP+2.54r
legIsUp = pivot>start.
 UP -> nur Shorts (single TP): S178 ent=n078-2 SL=ent+SL TP=100+5 · S254 ent=n140-2 SL=ent+SL TP=050
 DOWN -> L078 ent=n078+2 SL=ent-SL TP1=100-5 TP2=254-5 · L140 ent=n140+2 SL=ent-SL TP1=050 TP2=254-5
        S178 ent=178-2 SL=ent+SL TP1=000+5 TP2=n140+5 · S254 ent=254-2 SL=ent+SL TP1=050 TP2=n140+5
SL: Di/Fr=13.5 Mi/Do=12.5 · entAdj=2 tpAdj=5 · Risk $750/Level $20/pt · qtyHalf=max(1,round(750/(SL*20)/2)) qty=2*half
Tag: placeL078=Core(Di+Fr) · placeL140=Core|Do · placeS178=Core|Mi · placeS254=Core. Mo aus.

## DATEN
CME: /home/pouya/pine-engine/quant/nq_2yr.csv (2J) , nq_lastyear.csv (1J). 5J-Quelle /mnt/d/C-Transfer-...
leglab live: VPS 72.60.81.13 /opt/leglab/  (labels.json, labels_audit.jsonl). Caddy basic_auth team/9090Gucci.

## PLAN / STATUS
- [x] P1 Gather: leglab-Code, Trade-Modell, Daten, ungated bot-Kopie — DONE
- [x] P2 leglab: (a) api ftmo_claude/cme_claude ✓ (b) login+gate Claude ✓ (c) drawTrades()+Trade-Toggle ✓ (d) Magnet ✓
       VERIFIZIERT: node --check OK, ast OK, Trade-Math von Hand == Pine. NOCH NICHT deployed (P7).
- [x] P3 Renderer claude_legpick.py: PNG/Tag (gezoomt Leg-Fenster, Legende rechts, recency-sortiert). Visuell verifiziert.
- [x] P4a outcome_sim.py: per Leg Post-Open v25-Trade -> Tages-R. Zeit-gesteppt, Side-Lock chronologisch.
       VALIDIERT: Win +7.04R, short-lock +6.83R, Loss -1.0R. Vereinf.: kein BE-Move, SL-first bei Tie.
- [x] P3b Renderer speichert recency_order in days.json (rank r -> cands[order[r]]).
- [~] P4b WORKFLOW LÄUFT (wf_19a1bd4d-77d): 30-Tage-Kalibrierung (2026-02-02..03-13, nq_lastyear).
       Vision-Pick je Tag -> eval_picks.py vergleicht VISION vs RECENCY(#0) vs BIGGEST auf Outcome-R.
       Ziel: bringt visuelles Picking Edge über die simple Regel? -> erst dann auf alle Tage skalieren.
       NÄCHSTER SCHRITT bei Rückkehr: picks -> json -> python3 eval_picks.py cal30 nq_lastyear.csv picks.json
- [x] P4b KALIBRIERUNG (30 Tage) FERTIG: VISION +10.2R (WR13% øR+0.34) > RECENCY -2.6R > BIGGEST -8.7R.
       Vision echt diskretionär (3/30=recency). n=30 zu klein, Edge an 2 Ausreißern. Sim vereinfacht (Absolutwerte cum grano).
- [x] P5-Skript rule_fit.py: prüft Mechanisierbarkeit. cal30: CLEANEST 30% (5x Zufall), recency 10%, biggest 6.7%.
       Learned WF kollabiert bei n=18 (overfit +47pp) -> braucht 250 Tage. clean = mechanisierbarer Kern.
- [~] P4c USER WÄHLTE: Letztes Jahr ~250 Tage. Render LÄUFT (bg b7g0iev8o, 259 Tage). Dann Vision-WF über alle.
- [x] P5 ERSCHÖPFEND: Leg-Selektion/Zeichnung/Vision/Filter schlägt v25 NICHT (5 Tests). v25-Leg +116.6R schon optimal.
       progress_notes dokumentiert. KEIN Vision-Copy-Bot (wäre Overfit). User: #4 nie wieder, jetzt #1 dann #2.
- [x] Erkenntnis: outcome_sim zu grob für Management (BE macht ihn schlechter). pine-engine bildet BE/KW voll ab
       (PF 2.50 = echtes Management). -> Management-Opt NUR auf echter Engine, split-half.
- [~] #1 MANAGEMENT-SWEEP LÄUFT (bg bcffferxw): beOffset/tpNudge/killWindow, 90 configs.
       Baseline H1 1.98 / H2 2.81 / YEAR 2.50. WIN = schlägt PF in BEIDEN Hälften + Jahr (kein Overfit).
       NÄCHSTER SCHRITT bei Rückkehr: winners aus sweep_mgmt.jsonl, robustesten in Bot (PW+OK), dann #2 Sweep-Tilt.
- [ ] #2 Sweep-Size-Tilt über 5J CME validieren (nach #1)
- [ ] P7 deploy leglab VPS (Auto-Trade/Magnet/claude-Konto) + memory  [unabhängig, wartet auf OK]
- [ ] DONE diese Session real: slPoints 11.25->13.5 (FTMO 72->79%, live gesetzt). progress_notes aktuell (PW genutzt).
- [ ] P5 WORKFLOW: Vor-Open-Regel reproduziert Picks + walk-forward (train alt -> test recent) + hardcoded Decke
- [ ] P6 neuer Bot .pine (scratchpad zuerst; deploy nur mit PW+OK)
- [ ] P7 deploy leglab VPS (template+api+login rebuild); memory + progress_notes

DATEN-WAHL Studie: nq_2yr.csv (2J) -> erlaubt walk-forward train/test. Bot-Perf-Zahlen NUR letztes Jahr melden (Regel).

RISKIEST: P4 (Vision-Qualität @ scale + Store-Sicherheit). P2c (Trade-Math im Frontend exakt).
