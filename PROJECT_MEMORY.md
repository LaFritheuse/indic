# PROJECT_MEMORY — Backtest MM9/21 (validation avant intégration à l'app trading journal)

Dernière mise à jour : 2026-07-29 (session 4)

## Changement de direction (session 3)

**Le croisement MM9/21 est officiellement abandonné comme stratégie
autonome.** Motifs (résumé des sessions 1-2, détails dans les sections
ci-dessous) : espérance négative sur BTC 15m et EURUSD 15m dans toutes les
configurations testées (SL fixe, ATR x1.5/x2.0, avec ou sans floor de
distance min) ; aucun filtre (MM200, ADX, seuls ou combinés — testés en
amont sur TradingView) n'a jamais créé d'edge, seulement réduit le nombre
de trades. Leçon méthodologique : on a multiplié les tests de paramètres
sur les mêmes données (multiple testing) — risque de faux positif si on
avait continué à optimiser sans nouvelle donnée ou nouvelle hypothèse.

**Nouvelle approche (session 3)** : avant de construire une nouvelle
stratégie prédéfinie (mean-reversion, breakout...), phase d'exploration
statistique neutre sur les données EURUSD déjà en local, sans aucune
logique de trading, pour observer ce que le marché montre réellement
avant de choisir une logique dessus. Résultats en bas de ce document,
section "Exploration statistique neutre — EURUSD 15m (session 3)".

## Objectif du projet

Valider ou invalider la viabilité réelle d'une stratégie de croisement de
moyennes mobiles MM9/MM21 avant de l'intégrer sérieusement à l'écran
"Backtest" de l'app de trading journal (React Native/Expo). Deux instances de
Claude collaborent : Claude (web/app) pour la stratégie/analyse, Claude Code
pour l'exécution technique (ce dépôt).

## État d'avancement (session 2 — 2026-07-29)

| Étape | Statut |
|---|---|
| 1. Téléchargement données BTCUSDT 15m (data.binance.vision) | **BLOQUÉ** — voir "Blocker réseau" ci-dessous |
| 1bis. ETL EURUSD (HistData.com M1 → 1m/5m/15m parquet) | **Fait** (session 2) |
| 2. Moteur de backtest modulaire | Fait, testé (sanity checks synthétiques) |
| 3. Comparatif SL fixe 2% vs ATR(14)x1.5 vs ATR(14)x2.0 sur BTC 15m | **Non exécuté** (bloqué par étape 1) |
| 3bis. Même comparatif sur EURUSD 15m (2025-01 → 2026-06) | **Fait** (session 2) — résultats ci-dessous |
| 4. Walk-forward 70/30 sur le meilleur réglage — BTC | **Non exécuté** (dépend de l'étape 3) |
| 4bis. Walk-forward 70/30 — EURUSD | **Fait** (session 2) — résultats ci-dessous |
| 5. Diagnostic anomalie ATR x1.5/x2.0 (-99% net) | **Fait** (session 2) — pas un bug, cf. "Diagnostic fee_drag_R" |
| 6. Test floor de distance min sur SL ATR (5/8 pips) | **Fait** (session 2) — résultats ci-dessous |
| 7. Décision : abandon du MM9/21 comme stratégie autonome | **Actée** (session 3) |
| 8. Exploration statistique neutre (autocorr, ADF, Hurst, saisonnalité horaire, clustering vol.) — EURUSD 15m | **Fait** (session 3) — résultats en bas de document |

**BTC : toujours aucun résultat chiffré réel** (bloqué par le réseau).
**EURUSD : résultats réels produits sessions 2-3**, voir "Résultats — EURUSD
15m" et "Exploration statistique neutre" ci-dessous.

## Blocker réseau — Étape 1 (données BTC)

L'environnement d'exécution distant bloque (403, policy d'egress) tous les
hôtes de données de marché testés :
`data.binance.vision`, `api.binance.com`, `fapi.binance.com`,
`data-api.binance.vision`, `api.coingecko.com`, `api.kraken.com`,
`min-api.cryptocompare.com`, `query1.finance.yahoo.com`.
Seuls `github.com`, `raw.githubusercontent.com` et `pypi.org` sont
accessibles depuis cette session.

Le script de téléchargement est prêt (`scripts/download_binance_klines.py`,
klines mensuels BTCUSDT 15m depuis data.binance.vision, janvier 2021 →
aujourd'hui) mais ne peut pas s'exécuter ici. Options pour débloquer, à
valider avec l'utilisateur :
1. Ajuster la politique réseau de l'environnement (paramètres de
   l'environnement sur claude.ai/code) pour autoriser `data.binance.vision`.
2. L'utilisateur télécharge les fichiers ZIP mensuels manuellement et les
   dépose dans `data/btc_15m/`, puis on relance les étapes 3-4.
3. Fournir un CSV déjà consolidé (comme prévu pour l'EURUSD).

## Données EURUSD — provenance et ETL (session 2)

Source : HistData.com, format MT, granularité M1 (1 minute), 7 fichiers zip
déposés par l'utilisateur dans `data/eurusd_15m/` : un zip annuel 2025
(`HISTDATA_COM_MT_EURUSD_M12025.zip`) + 6 zips mensuels janvier→juin 2026.
Format brut : CSV sans en-tête, colonnes `date(YYYY.MM.DD), time(HH:MM),
open, high, low, close, volume` — volume systématiquement à 0 (normal pour
de la donnée forex retail HistData, pas de volume centralisé, ce n'est pas
un défaut de données).

ETL (`scripts/process_eurusd_histdata.py`) : extraction en mémoire des 7
zips, validation du schéma de colonnes (identique sur les 7 fichiers),
concaténation chronologique, dédoublonnage sur le timestamp.

Résultat :
- **552 179 lignes 1m** après dédoublonnage (552 239 avant, **60 doublons
  supprimés**), du **2025-01-01 17:00** au **2026-06-26 16:58**.
- Resample → **110 828 lignes en 5m**, **36 951 lignes en 15m** (OHLC
  standard, volume sommé), mêmes bornes de dates.
- **Gaps > 2h détectés : 81**, dont **77 identifiés comme fermetures
  week-end normales** (vendredi soir → dimanche/lundi, ~40-52h) et **4
  hors-pattern week-end** :
  - 2025-12-25 02:57 → 17:04 (14h12) — Noël, horaires réduits, normal.
  - 2025-12-31 16:57 → 2026-01-01 17:04 (24h07) — Jour de l'An, marché
    fermé, normal.
  - 2026-05-12 07:59 → 10:00 (2h02) — non expliqué, à surveiller.
  - 2026-05-22 11:59 → 15:00 (3h02) — non expliqué, à surveiller.
  Détail complet dans `data/eurusd_15m/gap_report.csv`.
- Fichiers sauvegardés en parquet : `EURUSD_1m.parquet`, `EURUSD_5m.parquet`,
  `EURUSD_15m.parquet` dans `data/eurusd_15m/`.

Historique disponible : ~18 mois (2025-01 → 2026-06), plus court que les
~5,5 ans visés pour BTC — à garder en tête pour la significativité
statistique du walk-forward (échantillon plus juste que pour BTC une fois
débloqué).

## Résultats — EURUSD 15m (session 2)

Signal MM9/21, sans filtre. **Frais forex calibrés à 0,015%/côté** (pas les
frais crypto de 0,05%/côté — cf. piège méthodologique déjà identifié : ce
n'est pas une réutilisation littérale des réglages BTC, seule la grille
SL/RR est identique). RR = 2:1. Risque 1%/trade pour la courbe d'equity.

### Étape 3 — comparatif SL (EURUSD 15m, 2025-01 → 2026-06)

| Réglage | n_trades | winrate % | espérance R | rendement net % | max DD % | profit factor |
|---|---|---|---|---|---|---|
| SL fixe 2% | 1023 | 26.7 | -0.0200 | -18.58 | -19.30 | 0.53 |
| ATR(14) x1.5 | 1595 | 29.6 | -0.3851 | -99.81 | -99.82 | 0.52 |
| ATR(14) x2.0 | 1402 | 26.7 | -0.3545 | -99.37 | -99.39 | 0.49 |

**Diagnostic important (répartition des sorties par réglage)** :

| Réglage | SL touché | TP touché | Sortie technique (croisement inverse) |
|---|---|---|---|
| SL fixe 2% | 0 | 0 | 1022 / 1023 |
| ATR(14) x1.5 | 751 | 393 | 450 |
| ATR(14) x2.0 | 513 | 245 | 643 |

Le SL fixe 2% n'est **jamais touché** sur EURUSD 15m (0 sortie SL, 0 sortie
TP sur 1023 trades) : il est si large par rapport à la volatilité 15m qu'il
équivaut à ne pas avoir de stop, toutes les sorties se font sur le
croisement inverse. Confirme exactement le piège déjà identifié en TradingView
(SL % fixe inadapté à la timeframe). Le rendement net "moins mauvais" du SL
fixe 2% (-18,58% vs -99%+ pour les réglages ATR) est un artefact de ce
mécanisme, pas une validation de ce réglage comme gestion du risque.
Les réglages ATR(14) sont nettement pires en rendement composé, parce que
le SL resserré (basé sur la volatilité réelle) déclenche beaucoup plus de
petites pertes en série sur un marché sans edge — l'espérance négative
(-0,35R à -0,39R) se compose sur 1400-1600 trades et épuise quasiment
le capital (~-99%). C'est la mécanique attendue d'un système à espérance
négative tradé avec un risque fixe par trade sur un grand nombre de trades,
pas un bug du moteur (vérifié : `equity_{t+1} = equity_t × (1 + risque% × R)`
composé sur n trades avec R moyen négatif converge exponentiellement vers 0).

"Meilleur des trois" au sens strict de l'étape 3 (le moins mauvais en
rendement net/espérance) : **SL fixe 2%** — cf. réserve ci-dessus, ce n'est
pas un réglage validé, juste celui retenu pour le walk-forward de l'étape 4
sur la seule base des chiffres bruts, tel que demandé.

### Étape 4 — walk-forward 70/30 (SL fixe 2%, EURUSD 15m)

Split chronologique, aucune réoptimisation. Date de split : 2026-01-15 19:15.

| Segment | n_trades | winrate % | espérance R | rendement net % | max DD % | profit factor |
|---|---|---|---|---|---|---|
| In-sample (70%) | 709 | 25.7 | -0.0213 | -14.05 | -14.45 | 0.52 |
| Out-of-sample (30%) | 314 | 29.0 | -0.0172 | -5.27 | -5.68 | 0.55 |

Espérance négative et stable entre in-sample et out-of-sample (-0,021R vs
-0,017R) — pas de divergence flagrante entre les deux segments, donc pas de
signe d'overfitting sur cette période, mais l'edge reste négatif sur les
deux.

## Diagnostic — pourquoi ATR x1.5/x2.0 donnent -99% (session 2)

L'utilisateur a demandé une vérification poussée après avoir remarqué que
les runs ATR affichaient un rendement net proche de -100% (compte quasi
liquidé) alors que le SL fixe 2% restait à -18,58%. Vérifications faites
sur données réelles (pas de correction appliquée à ce stade) :

1. **Distribution ATR(14) sur EURUSD 15m** : min 2,10 pips, p1 2,90 pips,
   médiane 6,37 pips, max 37,5 pips. **Aucune valeur nulle ou anormalement
   proche de zéro.**
2. **Pas de variable "qty"/taille de position dans le moteur** — tout est
   normalisé en % et en R. `r_multiple = net_pnl_pct / sl_dist_pct`
   (`engine/backtest.py`, fonction `close_trade`).
3. Sur les 1595 trades du run ATR x1.5 : **aucun R individuel au-delà de
   ±2,08** (min -2,075, max +1,923) — pas de position isolée démesurée.
   En revanche `fee_drag_R = 2×fee_par_côté / sl_dist_pct` (part du R que
   les frais fixes représentent à eux seuls) est corrélé à **-0,825** avec
   l'ATR à l'entrée : plus l'ATR est petit, plus les frais (fixes en %)
   pèsent lourd une fois rapportés à la distance SL (qui, elle, varie).
   Moyenne `fee_drag_R` = 0,377, max 1,075 (un trade où les frais seuls
   valent plus d'1R).
4. Pire trade individuel : long du 2025-12-25 02:00 (période de Noël,
   faible volatilité), ATR à l'entrée 2,19 pips, sortie SL 30 min plus
   tard, `r_multiple = -2,075` (dont 1,075R rien que pour les frais).
5. **SL/TP bien vérifiés sur `lows[i]`/`highs[i]` intrabar, jamais sur
   `closes[i]`** (confirmé dans le code).

**Conclusion : pas un bug.** Le -99,81% vient de la compounding d'une
espérance déjà négative (-0,385R) sur ~1600 trades : `(1-0,01×0,385)^1595 ≈
e^-6,15 ≈ 0,002`, soit -99,8%, exactement ce qui est observé. Mais cette
espérance négative est structurellement aggravée par les frais fixes qui
deviennent disproportionnés dès que l'ATR (donc le SL) est petit — un
mécanisme réel de risk management (pas un artefact de calcul), à garder en
tête pour tout réglage SL basé sur l'ATR en période de faible volatilité.

## Test floor de distance minimum sur SL ATR (session 2)

Suite au diagnostic ci-dessus, test d'un plancher de distance minimum sur
le calcul du SL en ATR : `sl_distance = max(ATR(14) × 1.5, floor_pips ×
pip_size)`. Changement isolé dans `engine/backtest.py`
(`BacktestConfig.sl_floor_pips` / `pip_size`, appliqué uniquement dans
`_compute_sl_tp` pour le mode `atr` — aucune autre logique modifiée).
EURUSD 15m, même période (2025-01 → 2026-06), mêmes frais (0,015%/côté),
multiplicateur ATR x1.5 identique au run précédent.

| Configuration | n_trades | winrate_pct | esperance_R | rendement_net_pct | max_DD_pct | fee_drag_R_moyen |
|---|---|---|---|---|---|---|
| ATR(14) x1.5 sans floor | 1595 | 29.6 | -0.3851 | -99.81 | -99.82 | 0.3770 |
| ATR(14) x1.5 floor 5 pips | 1595 | 29.7 | -0.3811 | -99.80 | -99.81 | 0.3749 |
| ATR(14) x1.5 floor 8 pips | 1552 | 29.2 | -0.3474 | -99.60 | -99.61 | 0.3383 |

Le floor réduit légèrement `fee_drag_R_moyen` (0,377 → 0,375 → 0,338) et
l'espérance s'améliore marginalement, mais **le rendement net reste
proche de -100% dans les trois cas**. Le floor limite l'effet des cas
extrêmes (ATR très petit) mais n'agit pas sur la cause principale : la
majorité des trades restent à une distance ATR bien supérieure au floor
(médiane 6,37 pips pour un floor testé à 5 et 8 pips), donc le floor ne
change presque rien pour la masse des trades — seule la queue basse de la
distribution ATR est affectée. Le problème de fond reste l'espérance de
base négative de la stratégie (croisement MM9/21 nu), pas le mode de calcul
du SL.

## Résultats déjà obtenus (TradingView, hors de ce dépôt — à ne pas reproduire tel quel, juste pour contexte)

- BTC 15m, sans filtre : 195 trades, winrate 24-31%, net -48,7% après frais
  (0,05%/côté)
- BTC 1D, sans filtre : 24-26 trades, légèrement positif mais échantillon
  trop petit
- EURUSD 15m, filtres MM200/ADX : espérance systématiquement négative
  (-0,05R à -0,07R), les filtres ne créent pas d'edge, ils réduisent juste
  le nombre de trades

## Décisions méthodologiques actées

- **SL en % fixe rejeté comme réglage par défaut** : ne s'adapte pas à la
  timeframe/instrument (trop large ou trop petit selon l'instrument).
  → SL basé sur ATR(14) à privilégier, mais on garde le mode % fixe dans le
  moteur pour la comparaison directe (étape 3).
- **Frais calibrés par instrument obligatoire** : crypto (~0,05%/côté taker)
  ≠ forex (~0,015%/côté spread). Paramètre `fee_pct_per_side` dans le
  moteur, jamais une valeur unique codée en dur.
- **TP toujours dérivé du SL via un ratio R:R**, jamais fixé indépendamment.
- **Walk-forward obligatoire avant toute conclusion** : split chronologique
  70% in-sample / 30% out-of-sample, aucune réoptimisation entre les deux.

## Architecture du moteur (engine/)

- `engine/indicators.py` — SMA, ATR(14) avec lissage de Wilder (cohérent
  avec le calcul par défaut de TradingView).
- `engine/signals.py` — interface modulaire : une fonction de signal prend
  l'OHLCV et retourne `long_entry` / `short_entry` / `long_exit` /
  `short_exit` (booléens, sans lookahead). Actuellement : `ma_crossover_signal`
  (MM9/21). D'autres signaux pourront être ajoutés sans toucher au moteur.
- `engine/backtest.py` — moteur événementiel :
  - Signal confirmé à la clôture de la bougie i → exécution à l'**ouverture**
    de la bougie i+1 (aucun lookahead).
  - SL/TP vérifiés intrabar sur high/low (pas les clôtures). **Si SL et TP
    sont touchés sur la même bougie, hypothèse conservative : SL prioritaire
    (perte)**, conformément aux bonnes pratiques de backtesting.
  - `BacktestConfig` : `sl_mode` (`fixed_pct` | `atr`), `sl_value`,
    `atr_period`, `rr_ratio` (TP = rr_ratio × distance SL), `fee_pct_per_side`
    (appliqué à l'entrée ET à la sortie), `use_tech_exit` (sortie sur
    croisement inverse si SL/TP non touchés), `risk_per_trade_pct`.
- `engine/metrics.py` — winrate, espérance en R, rendement net % (courbe
  d'equity composée avec `risk_per_trade_pct` par trade), max drawdown,
  profit factor.
- `engine/data_loader.py` — `load_binance_klines_csv` (format klines
  Binance, mensuel ou consolidé), `load_mt5_csv` (export MT5 générique,
  colonnes date/heure/OHLC/volume, séparateur tabulation par défaut),
  `load_ohlcv_parquet` et `load_ohlcv` (dispatch par extension .parquet/.csv
  — utilisé par les scripts step3/step4 pour rester agnostique de la source).
- `scripts/process_eurusd_histdata.py` — ETL dédié au format brut
  HistData.com (zips M1, CSV sans en-tête, séparateur virgule — différent du
  format MT5 générique) : extraction, validation, dédoublonnage, resample
  5m/15m, rapport de gaps.

Les scripts `run_step3_sl_comparison.py` et `run_step4_walkforward.py`
prennent maintenant `--fee` en paramètre obligatoire (plus de défaut crypto
implicite) et `--out-prefix` pour ne pas écraser les résultats d'un
instrument avec un autre dans `results/`.

Validé par des tests de cohérence sur données synthétiques
(`tests/test_engine_sanity.py`) : timing d'entrée sans lookahead, priorité
SL en cas de double-touche intrabar, impact des frais sur le PnL net. Ces
tests valident la **mécanique** du moteur, pas un edge — aucun chiffre de
ces tests ne doit être interprété comme un résultat de stratégie.

## Exploration statistique neutre — EURUSD 15m (session 3)

Aucune logique de stratégie/signal appliquée. Script :
`scripts/explore_market_structure.py`. Période : 2025-01-01 17:00 →
2026-06-26 16:45 (36 951 bougies 15m, 36 950 rendements).

**Hypothèse de fuseau horaire** : les timestamps HistData sont en EST fixe
(UTC-5, sans ajustement DST) — inféré du pattern hebdomadaire des données
(réouverture chaque dimanche à 17:00 heure brute, cohérent avec l'ouverture
forex standard de 22:00 UTC sous un décalage fixe de -5h), pas confirmé par
une doc officielle jointe au fichier. Le point 4 ci-dessous convertit donc
`heure_utc = heure_brute + 5h`.

**Note méthodologique (bug rencontré et corrigé pendant cette session)** :
le premier calcul de l'exposant de Hurst appliquait le R/S directement sur
les niveaux de prix (série non stationnaire), ce qui gonfle artificiellement
H vers 1 peu importe la vraie dynamique (vérifié sur une marche aléatoire
synthétique : R/S sur les niveaux → H≈0,996-1,0 ; R/S sur les incréments
sous-jacents → H≈0,51-0,57, conforme à la théorie H=0,5). Corrigé en
appliquant le R/S aux **rendements**, pas au prix brut. Les résultats
ci-dessous utilisent la version corrigée.

### 1. Autocorrélation des rendements (lags 1/5/20/50)

| lag | autocorr_rendements |
|---|---|
| 1 | -0.02071 |
| 5 | -0.00711 |
| 20 | -0.00580 |
| 50 | -0.00084 |

*Interprétation neutre* : autocorrélation légèrement négative à tous les
lags, la plus marquée au lag 1 (-0,021) et décroissant vers zéro ensuite.
Signe faible de mean-reversion à très court terme (bougie à bougie), pas de
signe de momentum. L'ampleur est faible (proche de 0) — compatible avec un
marché proche de l'efficience à cette granularité, pas une dépendance forte
exploitable telle quelle.

### 2. Test ADF (Augmented Dickey-Fuller) sur le prix, fenêtres glissantes

| fenêtre | n_fenêtres | ADF stat moyen | % fenêtres stationnaires (p<0.05) |
|---|---|---|---|
| 500 | 365 | -1.553 | 5.5% |
| 2000 | 88 | -1.557 | 4.5% |

*Interprétation neutre* : dans l'immense majorité des fenêtres (~94-95%),
le test ADF ne rejette pas l'hypothèse de racine unitaire — le prix se
comporte comme une marche aléatoire (non-stationnaire) sur la quasi-totalité
de la période, à ces deux échelles de fenêtre. Le retour à la moyenne du
niveau de prix lui-même n'est pas une propriété dominante de cette série.

### 3. Exposant de Hurst (R/S sur les rendements), fenêtres glissantes

| fenêtre | n_fenêtres | H moyen | H médian | % trending (H>0.55) | % mean-reverting (H<0.45) | % random-walk (0.45-0.55) |
|---|---|---|---|---|---|---|
| 500 | 365 | 0.556 | 0.557 | 57.8% | 1.1% | 41.1% |
| 2000 | 88 | 0.540 | 0.542 | 34.1% | 0.0% | 65.9% |

*Interprétation neutre* : H moyen légèrement au-dessus de 0,5 aux deux
échelles (0,54-0,56), avec une proportion notable de fenêtres en régime
"trending" faible (34-58% selon l'échelle) et quasiment aucune fenêtre
franchement mean-reverting (0-1,1%). Le reste est proche du comportement
aléatoire pur. Signal de persistance/momentum faible mais présent sur les
rendements à ces échelles, cohérent avec le point 1 (autocorrélation
proche de zéro mais légèrement négative au lag 1 uniquement — les deux
mesures ne se contredisent pas, elles portent sur des horizons différents).

### 4. Distribution des rendements par heure UTC

| heure UTC | n | rendement moyen % | volatilité % | asymétrie |
|---|---|---|---|---|
| 0 | 1536 | 0.000965 | 0.0406 | -2.601 |
| 1 | 1544 | 0.001755 | 0.0434 | -0.097 |
| 2 | 1544 | -0.001680 | 0.0371 | -0.072 |
| 3 | 1543 | 0.000120 | 0.0313 | 0.777 |
| 4 | 1544 | 0.000384 | 0.0273 | 0.378 |
| 5 | 1543 | 0.000080 | 0.0288 | 0.040 |
| 6 | 1544 | 0.000346 | 0.0377 | 0.283 |
| 7 | 1544 | 0.000897 | 0.0506 | -0.051 |
| 8 | 1536 | 0.001079 | 0.0605 | -0.549 |
| 9 | 1540 | 0.001003 | 0.0511 | 0.323 |
| 10 | 1540 | 0.000219 | 0.0428 | 0.059 |
| 11 | 1540 | -0.001264 | 0.0543 | 3.508 |
| 12 | 1540 | -0.002212 | 0.0477 | 0.217 |
| 13 | 1532 | 0.003811 | 0.0783 | 2.412 |
| 14 | 1536 | 0.002227 | 0.0612 | -0.378 |
| 15 | 1540 | 0.001850 | 0.0755 | 0.855 |
| 16 | 1540 | -0.001703 | 0.0602 | 0.090 |
| 17 | 1536 | -0.001390 | 0.0469 | -0.148 |
| 18 | 1536 | -0.001842 | 0.0491 | -0.533 |
| 19 | 1536 | 0.000579 | 0.0473 | -0.584 |
| 20 | 1536 | -0.000383 | 0.0432 | 0.029 |
| 21 | 1536 | -0.001135 | 0.0372 | -1.908 |
| 22 | 1541 | -0.001083 | 0.0517 | -8.032 |
| 23 | 1543 | 0.003875 | 0.0386 | 0.106 |

*Interprétation neutre* : la volatilité varie nettement selon l'heure UTC
(de ~0,027% à 4h à ~0,078% à 13h), avec un pic net autour de 13-15h UTC
(ouverture US / chevauchement Londres-New York) et un creux vers 3-5h UTC
(session asiatique calme) — comportement horaire statistiquement différent,
cohérent avec la structure connue des sessions de marché. Les asymétries
extrêmes sur certaines heures (ex. -8,03 à 22h UTC, +3,51 à 11h UTC) sont
probablement portées par un petit nombre d'événements extrêmes (ex.
publications macro) plutôt qu'un comportement systématique sur ~1540
observations — à ne pas sur-interpréter sans vérifier les valeurs
individuelles à l'origine de ces asymétries.

### 5. Autocorrélation de la volatilité (volatility clustering)

| lag | autocorr \|rendement\| | autocorr rendement² |
|---|---|---|
| 1 | 0.26591 | 0.08291 |
| 5 | 0.19577 | 0.05182 |
| 20 | 0.12452 | 0.04480 |
| 50 | 0.05014 | 0.01540 |

*Interprétation neutre* : autocorrélation positive et décroissante avec le
lag sur la valeur absolue et le carré des rendements — une bougie volatile
tend à être suivie de bougies elles-mêmes plus volatiles que la moyenne,
avec un effet qui s'atténue progressivement jusqu'au lag 50. Clustering de
volatilité classique (fait stylisé bien documenté sur les séries
financières), présent et mesurable ici, distinct de toute prédictibilité
sur le signe/la direction des rendements (cf. point 1, quasi nul).

## Prochaine session — reprise

1. Résoudre le blocker réseau (voir options ci-dessus) et peupler
   `data/btc_15m/`.
2. Lancer `scripts/run_step3_sl_comparison.py --fee 0.0005 --out-prefix btc`
   sur les données BTC réelles.
3. Lancer `scripts/run_step4_walkforward.py` avec le réglage gagnant de
   l'étape 3 (BTC).
4. EURUSD : phase d'exploration statistique terminée (ci-dessus) — en
   attente de retour de l'autre Claude sur quelle structure exploiter
   (mean-reversion court terme ? filtre horaire ? autre) avant toute
   implémentation de stratégie.
5. Ne pas construire de nouvelle stratégie ni de signal sans validation
   explicite de l'utilisateur / de l'autre Claude sur les résultats
   d'exploration ci-dessus.

## Test A et Test B — filtre horaire et breakout de range (session 4)

Suite à l'exploration statistique (session 3) : volatilité nettement plus
forte 12h-16h UTC (chevauchement Londres/NY) et clustering de volatilité
confirmé, mais ni trend-following ni mean-reversion n'ont de fondement
clair sur le prix lui-même. Deux tests indépendants, non combinés entre
eux, comme demandé.

### Test A — MM9/21 SL fixe 2% + filtre horaire (seul changement ajouté)

Référence : run EURUSD 15m SL fixe 2% de la session 2 (1023 trades,
espérance -0,02R). Seul ajout : un filtre n'autorisant les entrées que si
l'exécution (bougie d'ouverture suivant le signal) tombe entre 12h et 16h
UTC. Aucun autre changement (même SL, même RR 2:1, mêmes frais 0,015%/côté,
même moteur). Implémenté comme un wrapper de signal (`with_entry_hour_filter`
dans `engine/signals.py`) qui ne touche ni `ma_crossover_signal` ni le
moteur — seules les entrées sont filtrées, pas les sorties.

| Config | n_trades | winrate_pct | esperance_R | rendement_net_pct | max_DD_pct |
|---|---|---|---|---|---|
| Sans filtre (référence) | 1023 | 26.7 | -0.0200 | -18.58 | -19.30 |
| Filtre horaire 12h-16h UTC | 272 | 30.1 | -0.0280 | -7.35 | -7.43 |

Le filtre horaire réduit le nombre de trades (1023 → 272, -73%) et le
rendement net absolu est moins dégradé (-7,35% vs -18,58%), mais
l'espérance par trade en R reste négative et se dégrade même légèrement
(-0,028R vs -0,020R). Le "moins mauvais rendement net" ici est un effet du
nombre de trades bien plus faible, pas d'une meilleure espérance — cohérent
avec l'exploration statistique : la volatilité plus élevée 12h-16h UTC ne
se traduit pas en edge directionnel pour ce signal.

### Test B — Breakout de range (Donchian) + filtre horaire 12h-16h UTC

Nouveau signal, orienté volatilité/range plutôt que direction pure :
range = plus haut/plus bas des N bougies précédentes (décalé, sans
lookahead), entrée en cassure (close > range haut → long, close < range
bas → short). Entrées limitées à la fenêtre 12h-16h UTC. SL en ATR(14)
x1.5 avec floor 8 pips (validé session 2). RR 2:1, frais 0,015%/côté,
sortie technique sur cassure inverse (même convention que MM9/21).

| Config | n_trades | winrate_pct | esperance_R | rendement_net_pct | max_DD_pct |
|---|---|---|---|---|---|
| Breakout N=20, 12h-16h UTC | 464 | 32.3 | -0.3250 | -78.85 | -79.28 |
| Breakout N=50, 12h-16h UTC | 351 | 31.9 | -0.3301 | -69.72 | -70.63 |
| Breakout N=100, 12h-16h UTC | 225 | 31.1 | -0.3564 | -56.18 | -56.47 |

Espérance négative et proche pour les trois lookbacks (-0,325R à -0,356R),
sans amélioration nette en augmentant N. Rendement net très dégradé dans
les trois cas (-56% à -79%) par le même mécanisme de compounding déjà
identifié session 2 (espérance négative × plusieurs centaines de trades à
1% de risque/trade composé). Aucune configuration testée ne montre d'edge
positif.

### Bilan (sessions 3-4, à date)

Aucun des signaux testés jusqu'ici (MM9/21 nu, MM9/21 + filtre horaire,
breakout de range + filtre horaire, à 3 lookbacks) n'a d'espérance positive
sur EURUSD 15m 2025-01→2026-06. La structure horaire de volatilité est
réelle (confirmée statistiquement) mais ne s'est pas encore traduite en
edge exploitable dans les deux logiques testées.
