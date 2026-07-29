# PROJECT_MEMORY — Backtest MM9/21 (validation avant intégration à l'app trading journal)

Dernière mise à jour : 2026-07-29 (session 1)

## Objectif du projet

Valider ou invalider la viabilité réelle d'une stratégie de croisement de
moyennes mobiles MM9/MM21 avant de l'intégrer sérieusement à l'écran
"Backtest" de l'app de trading journal (React Native/Expo). Deux instances de
Claude collaborent : Claude (web/app) pour la stratégie/analyse, Claude Code
pour l'exécution technique (ce dépôt).

## État d'avancement (session 1 — 2026-07-29)

| Étape | Statut |
|---|---|
| 1. Téléchargement données BTCUSDT 15m (data.binance.vision) | **BLOQUÉ** — voir "Blocker réseau" ci-dessous |
| 1bis. Loader CSV format MT5 pour EURUSD | Fait, prêt à l'emploi, en attente du fichier |
| 2. Moteur de backtest modulaire | Fait, testé (sanity checks synthétiques) |
| 3. Comparatif SL fixe 2% vs ATR(14)x1.5 vs ATR(14)x2.0 sur BTC 15m | **Non exécuté** (bloqué par étape 1) |
| 4. Walk-forward 70/30 sur le meilleur réglage de l'étape 3 | **Non exécuté** (dépend de l'étape 3) |

**Aucun résultat chiffré sur données réelles n'a encore été produit dans ce
dépôt.** Tout chiffre venant d'une session précédente sur TradingView (voir
section "Résultats déjà obtenus (TradingView, hors de ce dépôt)") reste la
seule base connue à ce stade.

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
  Binance, mensuel ou consolidé) et `load_mt5_csv` (format export MT5,
  colonnes date/heure/OHLC/volume, séparateur tabulation par défaut).

Validé par des tests de cohérence sur données synthétiques
(`tests/test_engine_sanity.py`) : timing d'entrée sans lookahead, priorité
SL en cas de double-touche intrabar, impact des frais sur le PnL net. Ces
tests valident la **mécanique** du moteur, pas un edge — aucun chiffre de
ces tests ne doit être interprété comme un résultat de stratégie.

## Prochaine session — reprise

1. Résoudre le blocker réseau (voir options ci-dessus) et peupler
   `data/btc_15m/`.
2. Lancer `scripts/run_step3_sl_comparison.py` sur les données réelles.
3. Lancer `scripts/run_step4_walkforward.py` avec le réglage gagnant de
   l'étape 3.
4. Ne pas optimiser ni ajouter de filtre sans validation explicite de
   l'utilisateur / de l'autre Claude.
