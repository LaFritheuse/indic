# PROJECT_MEMORY — Backtest MM9/21 (validation avant intégration à l'app trading journal)

Dernière mise à jour : 2026-07-29 (session 2)

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

**BTC : toujours aucun résultat chiffré réel** (bloqué par le réseau).
**EURUSD : résultats réels produits cette session**, voir "Résultats — EURUSD
15m (session 2)" ci-dessous.

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

## Prochaine session — reprise

1. Résoudre le blocker réseau (voir options ci-dessus) et peupler
   `data/btc_15m/`.
2. Lancer `scripts/run_step3_sl_comparison.py --fee 0.0005 --out-prefix btc`
   sur les données BTC réelles.
3. Lancer `scripts/run_step4_walkforward.py` avec le réglage gagnant de
   l'étape 3 (BTC).
4. EURUSD : résultats déjà produits (voir ci-dessus) — en attente de retour
   de l'autre Claude avant toute suite (filtre, autre signal, autre
   instrument).
5. Ne pas optimiser ni ajouter de filtre sans validation explicite de
   l'utilisateur / de l'autre Claude.
