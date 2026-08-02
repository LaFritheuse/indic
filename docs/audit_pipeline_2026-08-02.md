# Audit complet du pipeline de collecte crypto (BTC/SOL) — 2026-08-02

## Contexte et objectif

Le pipeline collecte, via GitHub Actions vers Supabase, 5 tables pour BTC et SOL (perpetuals OKX + sources tierces) :

- `funding_oi_data` — funding rate + open interest (OKX, via ccxt)
- `liquidations_data` — liquidations (flux public Binance, via l'API Coinalyze)
- `long_short_ratio_data` — ratio de comptes long/short (Binance, via Coinalyze)
- `ohlcv_indicators` — bougies OHLCV 5m (OKX) + VWAP/CVD calculés
- `whale_trades_data` — trades individuels dépassant un seuil de notionnel (OKX, tape publique)

**Objectif final déclaré** : une cadence de collecte fiable toutes les 5-15 minutes, sans perte de données entre deux runs.

Cet objectif recouvre en réalité **deux problèmes distincts**, qu'il faut traiter séparément :

1. **« Sans perte de données entre deux runs »** — entièrement soluble côté code : il suffit que chaque collecteur récupère, à chaque exécution, une fenêtre glissante couvrant *au moins* le temps écoulé depuis le run précédent (plutôt qu'un instantané ponctuel), combinée à un upsert idempotent pour ne pas dupliquer les recouvrements. C'est déjà le modèle utilisé par `liquidations_data`.
2. **« Cadence fiable 5-15 minutes »** — **ce point ne dépend pas de nos scripts**. Le déclencheur est un cron GitHub Actions (`*/15 * * * *`), et il est déjà documenté (sessions précédentes) que GitHub Actions n'honore pas cette cadence de façon fiable sur des repos avec un usage modeste — la cadence réelle observée oscille entre ~15 minutes et plusieurs heures selon la charge des runners partagés. **Cet audit le reconfirme empiriquement** (voir plus bas : intervalle réel médian de 80.5 min sur `funding_oi_data`, alors que le cron est configuré à 15 min). Aucune correction de la logique de collecte ne peut compenser un déclencheur qui ne se déclenche pas — la seule vraie solution à ce volet est soit d'accepter la cadence irrégulière (et compter sur des fenêtres de rattrapage larges pour ne rien perdre malgré tout), soit de migrer vers un hôte auto-géré avec un vrai cron système (déjà exploré et mis en pause plus tôt dans le projet, voir `data_collection/vps_deploy/`).

Ce document ne traite donc à fond que le point 1 (rattrapage / zéro perte), et documente le point 2 comme une limite de plateforme externe, pas un défaut de nos collecteurs.

## Méthodologie

- Script d'audit dédié : `data_collection/audit_pipeline.py` (lecture seule, aucune écriture).
- Exécuté deux fois via un workflow GitHub Actions temporaire (`.github/workflows/audit_pipeline.yml`), le second run après correction d'un bug de pagination (voir ci-dessous).
- Pour chaque table : récupération de **toutes** les lignes (paginé), triées par timestamp, puis calcul :
  - des doublons exacts sur la clé d'unicité de la table,
  - des intervalles réels entre points consécutifs (médiane, moyenne, p90, max) par symbole,
  - de la cohérence des unités (ratios croisés entre colonnes monétaires),
  - de la présence systématique d'un offset UTC explicite sur les timestamps,
  - pour les whale trades : du taux d'observation par minute, extrapolé à des fenêtres de 5 et 15 minutes.

### Bug découvert et corrigé pendant l'audit : plafond silencieux à 1000 lignes

Le premier run affichait exactement **1000 lignes** pour `long_short_ratio_data`, `ohlcv_indicators` et `whale_trades_data` — un chiffre rond suspect. Cause : PostgREST (l'API REST de Supabase) plafonne toute réponse à 1000 lignes par défaut, **quel que soit le `limit` demandé côté client**, sauf pagination explicite via l'en-tête HTTP `Range`. Le script a été corrigé pour paginer par blocs de 1000 via `Range: 0-999`, `1000-1999`, etc. jusqu'à récupérer la totalité.

Impact du bug (avant/après correction) :

| Table | Compte affiché (run 1, tronqué) | Compte réel (run 2, corrigé) |
|---|---|---|
| `long_short_ratio_data` | 1000 | **1110** |
| `ohlcv_indicators` | 1000 | **2240** |
| `whale_trades_data` | 1000 | **1750** |

Cela signifie que les statistiques de fréquence des whale trades données plus bas (issues du run 2) sont fiables ; celles d'un premier passage auraient sous-estimé le volume réel de trades captés et la durée réellement couverte.

---

## 1. `funding_oi_data`

**Fichier** : `data_collection/collect_funding_oi.py` · **Schéma** : `supabase/migrations/20260728120000_funding_oi_data.sql`, `supabase/migrations/20260731210000_funding_oi_add_oi_usd.sql`

### 1.1 Continuité temporelle — ❌ À corriger

Le script fait un unique appel `fetch_funding_rate()` / `fetch_open_interest()` par symbole à chaque run, avec `timestamp = now()`. Il n'existe **aucune fenêtre de rattrapage** : si le cron ne se déclenche pas pendant 3 heures, ces 3 heures de funding rate / open interest sont perdues sans recours, contrairement à `liquidations_data` qui refetch une fenêtre de 3h à chaque run.

Un garde-fou anti-doublon existe (`DEDUP_THRESHOLD_MINUTES = 10`, saute le cycle si le dernier point a moins de 10 min) mais ne résout pas la continuité — il protège seulement contre un double-déclenchement rapproché.

### 1.2 Granularité réelle vs voulue — Mixte, à trancher

- **`open_interest` / `oi_usd`** : OKX expose un endpoint d'historique d'open interest (`fetchOpenInterestHistory` dans ccxt, granularité 5m/1h/1d), **mais il est scopé par devise** (paramètre `ccy`, ex. `BTC`), pas par instrument précis. Il agrège donc l'open interest sur **l'ensemble des produits dérivés BTC d'OKX** (perpetuals + futures + options confondus), alors que notre collecte actuelle (`fetch_open_interest("BTC/USDT:USDT")`) porte spécifiquement sur le perpetual USDT-margé. **Basculer sur cet endpoint changerait la métrique mesurée** et romprait la continuité/comparabilité avec l'historique déjà collecté. Ce n'est pas un simple correctif — c'est un changement de définition de la donnée, qui nécessite une décision explicite.
- **`funding_rate`** : OKX expose bien un historique **par instrument** (`fetchFundingRateHistory`, `instId` précis), fiable pour du rattrapage. Mais il donne le taux **réglé** (settlement, typiquement toutes les 8h sur OKX), pas le taux **prédictif en continu** qu'on capture aujourd'hui à chaque poll (qui varie en continu entre deux règlements). Basculer changerait aussi la sémantique de la donnée, même si le rattrapage lui-même serait techniquement robuste.

### 1.3 Doublons — ✅ OK

0 doublon exact sur `(symbol, timestamp)` parmi 114 lignes (57 BTC + 57 SOL). Point de vigilance : **aucune contrainte UNIQUE n'existe en base** sur cette table (contrairement aux 4 autres) — l'absence de doublon aujourd'hui tient à la précision au microseconde de `now()` à l'insertion, pas à une garantie structurelle.

### 1.4 Gaps temporels anormaux — ✅ OK (sous le seuil actuel, mais révélateur)

| Symbole | n | Intervalle médian | Moyenne | p90 | Max |
|---|---|---|---|---|---|
| BTC | 57 | 80.5 min | 95.9 min | 164.1 min | 225.4 min |
| SOL | 57 | 80.5 min | 95.9 min | 164.1 min | 225.4 min |

0 gap détecté au-delà de 3x la médiane (seuil arbitraire utilisé par le script). Mais ces chiffres, à eux seuls, confirment que le cron configuré à 15 min tourne en réalité 5 à 15x plus lentement en médiane — c'est la preuve empirique la plus directe du problème de plateforme évoqué en introduction.

### 1.5 Cohérence des unités — ✅ OK, vérifié empiriquement

Le ratio `oi_usd / open_interest` (qui doit approximer *prix × taille de contrat*, donc rester stable à court terme puisque le prix ne varie pas de plusieurs ordres de grandeur) est très cohérent par symbole :

| Symbole | Moyenne | Écart-type | Min | Max | `oi_usd` renseigné |
|---|---|---|---|---|---|
| BTC | 630.06 | 2.44 | 624.00 | 634.70 | 33/57 |
| SOL | 72.73 | 0.63 | 71.21 | 73.55 | 33/57 |

L'écart-type très faible (moins de 1% de la moyenne) confirme l'absence de bug d'unité entre les deux colonnes. `oi_usd` n'est renseigné que sur 33/57 lignes par symbole — normal, la colonne a été ajoutée après le début de la collecte (migration du 31/07).

`funding_rate == 0` : 0 occurrence (pas d'anomalie de collecte figée).

### 1.6 Fuseau horaire — ✅ OK

114/114 timestamps portent un offset UTC explicite (`+00:00`).

### Corrections proposées pour `funding_oi_data` (non appliquées)

1. **Décision à prendre** : pour `funding_rate`, basculer sur `fetchFundingRateHistory` (rattrapage fiable, mais donnée = taux réglé et non plus taux live/prédictif) ou garder le comportement actuel (instantané, trous acceptés) ?
2. **Pas de correctif simple recommandé** pour `open_interest`/`oi_usd` : le seul historique disponible via OKX change le périmètre de la métrique (devise entière vs instrument). À db attre si acceptable.
3. Ajouter une contrainte `UNIQUE (symbol, timestamp)` en base, par cohérence avec les 4 autres tables et pour transformer la protection anti-doublon actuelle (applicative) en garantie structurelle.

---

## 2. `liquidations_data`

**Fichier** : `data_collection/collect_liquidations.py` · **Schéma** : `supabase/migrations/20260729120000_liquidations_data.sql`

### 2.1 Continuité temporelle — ✅ OK (modèle de référence)

Fenêtre `LOOKBACK_HOURS = 3` refetchée à chaque run + upsert idempotent sur `(symbol, timestamp)` avec `Prefer: resolution=merge-duplicates`. C'est le modèle que l'objectif final cite explicitement comme référence.

### 2.2 Granularité réelle vs voulue — ✅ OK

Buckets natifs de **1 minute** côté Coinalyze (`INTERVAL = "1min"`) — c'est la vraie résolution source, pas une limitation introduite par nous.

### 2.3 Doublons — ✅ OK

0 doublon exact sur `(symbol, timestamp)` parmi 577 lignes (372 BTC + 205 SOL).

### 2.4 Gaps temporels anormaux — ⚠️ À surveiller (risque structurel identifié)

| Symbole | n | Span couvert | Intervalle médian | Max |
|---|---|---|---|---|
| BTC | 372 | 2j 02h39 | 3.0 min | **83.0 min** |
| SOL | 205 | 2j 02h07 | 4.0 min | **139.0 min** |

Un intervalle de 3-4 min en médiane (au lieu de 1 min) est normal : Coinalyze ne renvoie un bucket que pour les minutes où une liquidation a effectivement eu lieu, pas pour chaque minute. En revanche, les gaps maximums (83 et 139 minutes) sont **indiscernables entre deux explications** :
- un marché réellement calme pendant cette durée (aucune liquidation), ou
- un angle mort : si le cron a sauté plus de 180 minutes (la fenêtre `LOOKBACK_HOURS`), les liquidations tombées avant cette fenêtre au run suivant sont perdues silencieusement — le run ne les demande même pas, donc rien n'indique leur absence dans les données récupérées.

Or l'audit de `funding_oi_data` montre un max réel de 225 minutes entre deux runs du même workflow — **supérieur à la fenêtre de 180 minutes de `liquidations_data`**. Le risque de perte silencieuse est donc réel, pas hypothétique.

### 2.5 Cohérence des unités — ⚠️ Découvert, non documenté jusqu'ici

`longvolume` / `shortvolume` sont en **unités natives (BTC, SOL)**, pas en dollars notionnels :

| Symbole | longvolume (min/max/moyenne) | shortvolume (min/max/moyenne) |
|---|---|---|
| BTC | 0.0000 / 84.599 / 0.617 | 0.0000 / 10.985 / 0.278 |
| SOL | 0.0000 / 16 338.65 / 419.12 | 0.0000 / 6 431.97 / 87.80 |

Ces ordres de grandeur n'ont de sens qu'en unités natives (0.6 $ de liquidations en moyenne par bucket n'aurait aucun sens ; 0.6 BTC ≈ 39 000 $ à 65 000 $/BTC est parfaitement plausible). Cette lecture est cohérente avec la documentation du wrapper Coinalyze (`ivarurdalen/coinalyze`), dont les exemples journaliers affichent des volumes de l'ordre de 18 à 120 (unités natives, pas des millions de dollars).

**Conséquence pratique** : `longvolume`/`shortvolume` ne sont **pas directement comparables** à `oi_usd` (`funding_oi_data`) ni à `notional_usd` (`whale_trades_data`), qui sont eux en dollars. Toute analyse croisée (ex. "le volume de liquidations représente quelle part de l'open interest") doit d'abord convertir en multipliant par le prix au moment du bucket.

### 2.6 Fuseau horaire — ✅ OK

577/577 timestamps UTC.

### Corrections proposées pour `liquidations_data` (non appliquées)

1. Augmenter `LOOKBACK_HOURS` de 3 à 5-6h pour absorber les gaps de cron observés jusqu'à 225 min, avec marge de sécurité.
2. Documenter explicitement l'unité (native, pas $) dans le docstring du module et dans le commentaire de la migration SQL.
3. Optionnel (plus lourd) : ajouter des colonnes calculées `longvolume_usd`/`shortvolume_usd` en joignant au prix OHLCV le plus proche au moment du bucket, pour rendre la table directement comparable aux autres sans conversion manuelle à chaque analyse.

---

## 3. `long_short_ratio_data`

**Fichier** : `data_collection/collect_long_short_ratio.py` · **Schéma** : `supabase/migrations/20260731210500_long_short_ratio_data.sql`

### 3.1 Continuité temporelle — ✅ OK

Même modèle que `liquidations_data` : fenêtre 3h + upsert idempotent sur `(symbol, timestamp)`.

### 3.2 Granularité réelle vs voulue — ✅ OK, confirmé par un test antérieur

`INTERVAL` a été testé à `"1min"` en premier lieu (choix initial), ce qui renvoyait systématiquement une réponse vide côté Coinalyze — confirmant empiriquement que cette granularité n'est pas disponible pour cet endpoint. Passé à `"5min"`, la collecte fonctionne (confirmé sur deux runs réels). 5 minutes satisfait l'objectif de cadence 5-15 minutes.

### 3.3 Doublons — ✅ OK

0 doublon exact sur `(symbol, timestamp)` parmi **1110 lignes réelles** (561 BTC + 549 SOL — le premier run, tronqué à 1000, en montrait faussement moins).

### 3.4 Gaps temporels anormaux — ⚠️ Même risque structurel que liquidations

| Symbole | n | Intervalle médian | Max |
|---|---|---|---|
| BTC | 561 | 5.0 min | 55.0 min |
| SOL | 549 | 5.0 min | 50.0 min |

Gaps maximum sous la fenêtre de 3h — pas de perte détectée sur l'historique observé, mais soumis au même risque structurel que `liquidations_data` si un cron venait à sauter plus de 180 minutes.

### 3.5 Cohérence des unités — ✅ OK

`ratio` est sans dimension (nombre de comptes long / nombre de comptes short). Vérification `longpct + shortpct ≈ 100` : **0 écart supérieur à 0.5** sur les 1110 lignes — cohérence totale.

| Symbole | ratio min | ratio max | ratio moyen |
|---|---|---|---|
| BTC | 1.880 | 2.245 | 2.095 |
| SOL | 2.418 | 2.905 | 2.715 |

### 3.6 Fuseau horaire — ✅ OK

1110/1110 timestamps UTC.

### Corrections proposées pour `long_short_ratio_data` (non appliquées)

1. Augmenter `LOOKBACK_HOURS` de 3 à 5-6h, par cohérence et sécurité avec `liquidations_data` (même raisonnement, même risque).

---

## 4. `ohlcv_indicators`

**Fichier** : `data_collection/collect_ohlcv_indicators.py` · **Schéma** : `supabase/migrations/20260731211000_ohlcv_indicators.sql`

### 4.1 Continuité temporelle — ✅ OK

Fenêtre `LOOKBACK_HOURS = 48` (volontairement large pour couvrir toute la journée UTC en cours, nécessaire au calcul VWAP/CVD ancré à minuit) + upsert idempotent sur `(symbol, timestamp, interval)`. Recalcul complet et déterministe à chaque run — le résultat pour une bougie donnée ne dépend jamais du moment ou du nombre de fois où le script tourne.

### 4.2 Granularité réelle vs voulue — ✅ OK

5 minutes natif OKX — vraie donnée de marché (bougies), aucune approximation de notre part sur ce point.

### 4.3 Doublons — ✅ OK

0 doublon exact sur `(symbol, timestamp, interval)` parmi **2240 lignes réelles** (1120 BTC + 1120 SOL — le premier run tronqué à 1000 masquait plus de la moitié des données réelles).

### 4.4 Gaps temporels anormaux — ✅ OK, excellent

**0 gap supérieur à 10 minutes** sur l'intégralité des 2240 lignes réelles (intervalle médian et max tous deux à exactement 5.0 min). C'est la table la plus saine du pipeline — logique, puisqu'il s'agit d'une vraie série temporelle exchange (bougies), pas d'un polling d'un état instantané.

### 4.5 Cohérence des unités — ✅ OK

Prix et volumes en unités standard. `high < low` ou autres incohérences OHLC : **0 occurrence** sur les 2240 lignes. VWAP/CVD : logique de reset à minuit UTC déjà validée sur données réelles lors d'un audit précédent (voir session du 31/07).

### 4.6 Fuseau horaire — ✅ OK

2240/2240 timestamps UTC.

### Corrections proposées pour `ohlcv_indicators`

**Aucune.** Cette table ne nécessite aucune correction.

---

## 5. `whale_trades_data`

**Fichier** : `data_collection/collect_whale_trades.py` · **Schéma** : `supabase/migrations/20260731224500_whale_trades_data.sql`

### 5.1 Continuité temporelle — ⚠️ Partiellement à corriger (déjà en partie traité)

Fenêtre `LOOKBACK_HOURS = 3` + pagination sur l'endpoint OKX `history-trades` (`MAX_PAGES_PER_SYMBOL = 300`, soit jusqu'à 30 000 trades bruts examinés par symbole et par run) + upsert idempotent sur `(symbol, trade_id)`.

Un run réel du 31/07 a montré que le plafond de pages était systématiquement atteint pour BTC (couverture réelle ~85 des 180 minutes demandées, faute de pages suffisantes vu le volume de trading), alors que SOL était quasiment couvert en entier (178/180 min). Le plafond a depuis été relevé de 30 à 300 pages (dernier correctif appliqué), mais son adéquation n'a pas été re-testée sur un run à fort volume BTC depuis.

### 5.2 Granularité réelle vs voulue — N/A

Donnée événementielle (chaque trade individuel), pas de notion de granularité fixe à discuter ici.

### 5.3 Doublons — ✅ OK

0 doublon exact sur `(symbol, trade_id)` parmi **1750 lignes réelles** (1675 BTC + 75 SOL — le premier run tronqué à 1000 masquait 750 trades BTC réels).

### 5.4 Gaps temporels anormaux — N/A

Pas de notion de "gap régulier" pertinente pour un flux d'événements ponctuels et rares par nature.

### 5.5 Cohérence des unités — ✅ OK, vérifié strictement

`notional_usd == price × amount` vérifié ligne par ligne sur les 1750 lignes : **0 écart supérieur à 0.01**. Cette table est en dollars notionnels réels, cohérente avec `oi_usd` (`funding_oi_data`), directement comparable entre les deux.

### 5.6 Fuseau horaire — ✅ OK

1750/1750 timestamps UTC.

### 5.7 Pertinence du seuil de notionnel (100 000 $) — analyse chiffrée

Sur l'historique réel complet (~44.6 heures de données cumulées entre les runs de collecte) :

| | BTC | SOL |
|---|---|---|
| Trades captés (total) | 1675 | 75 |
| Taux observé | 0.625 trade/min | 0.028 trade/min |
| **Extrapolé / fenêtre 5 min** | **~3.13** | **~0.14** |
| **Extrapolé / fenêtre 15 min** | **~9.38** | **~0.42** |
| Notionnel min / max / médian | 100 001 $ / 5 176 641 $ / 133 453 $ | 100 752 $ / 1 066 668 $ / 172 641 $ |
| Répartition achat/vente | 846 achats / 829 ventes | 39 achats / 36 ventes |

**Interprétation** :
- **BTC à 100 000 $ : seuil probablement trop bas pour un usage "signal de gros trade".** ~3 trades toutes les 5 minutes, ~9 toutes les 15 minutes — à cette fréquence, ce n'est plus un événement notable/rare, c'est un flux quasi continu. Pour qu'un whale trade reste un signal exploitable en intraday (rare mais pas inexistant), un seuil de l'ordre de **250 000 $ à 500 000 $** ramènerait probablement à quelques trades par fenêtre de 15 minutes plutôt que 9.
- **SOL à 100 000 $ : plausible, voire un peu rare.** ~0.14 trade/5min, ~0.42 trade/15min — soit un trade notable toutes les ~35 minutes en moyenne. Le seuil actuel semble déjà raisonnable ; le baisser légèrement (75 000 $) augmenterait la fréquence sans le rendre non-sélectif, si plus de signal est souhaité.
- La structure du code (`NOTIONAL_THRESHOLD_USD` est déjà un dict par symbole dans `collect_whale_trades.py`) permet d'ajuster indépendamment BTC et SOL sans changement structurel — seule la valeur change.

### Corrections proposées pour `whale_trades_data` (non appliquées)

1. Ajuster `NOTIONAL_THRESHOLD_USD` — proposition : BTC 250 000-500 000 $, SOL inchangé ou légèrement abaissé (75 000-100 000 $). **Valeurs exactes à ta discrétion.**
2. Re-tester la couverture réelle de la pagination (300 pages) sur un run correspondant à une période de volume BTC élevé, pour confirmer que le relèvement du plafond (30→300) suffit désormais à couvrir les 180 minutes de la fenêtre en toutes circonstances.

---

## Synthèse transversale

### Ce qui est déjà solide (aucune action requise)
- `ohlcv_indicators` : continuité, granularité, doublons, gaps, unités, UTC — tout est vert.
- Cohérence des unités **au sein de chaque table** : partout où c'est vérifiable (funding/OI, whale trades, ratio long/short), les valeurs sont internes cohérentes.
- Fuseau horaire : 100% des timestamps sur les 5 tables sont en UTC explicite, sans exception.
- Absence de doublons : 0 doublon détecté sur les 5 tables, sur la totalité des lignes réelles (post-correction de la pagination).

### Ce qui nécessite une décision ou un correctif
1. **`funding_oi_data` est la seule table sans aucune fenêtre de rattrapage** — c'est le point qui correspond le plus directement à la demande initiale ("comme le fait déjà liquidations_data"). Contrairement aux autres tables cependant, un simple ajout de fenêtre n'est pas possible sans compromis : le rattrapage disponible côté OKX change soit la définition de la métrique (OI : scope devise vs instrument), soit sa nature (funding : réglé vs live). **Décision utilisateur nécessaire avant tout correctif ici.**
2. **`liquidations_data` et `long_short_ratio_data` partagent un risque structurel identique** : leur fenêtre de rattrapage (3h) est plus courte que le pire gap de cron observé empiriquement (225 min sur `funding_oi_data`, cette même session). Correctif simple et peu coûteux : élargir `LOOKBACK_HOURS` à 5-6h.
3. **Incohérence d'unité documentée mais pas corrigée** : `liquidations_data` est en unités natives (BTC/SOL), alors que `funding_oi_data` (`oi_usd`) et `whale_trades_data` (`notional_usd`) sont en dollars. Pas un bug — mais une source d'erreur d'interprétation si on compare ces tables sans convertir.
4. **Seuil whale trades à recalibrer**, probablement à la hausse pour BTC (250-500k$) au vu de la fréquence réelle observée (~3-9 trades/fenêtre 5-15min à 100k$ actuellement).
5. **Bug de pagination corrigé pendant cet audit** (plafond PostgREST à 1000 lignes, invisible sans vérification explicite) — sans lien direct avec la collecte elle-même, mais qui aurait faussé toute analyse future sur ces 3 tables si on avait continué à l'ignorer.

### Rappel du cadrage cadence
Aucune des corrections ci-dessus ne résout le fait que le cron GitHub Actions tourne à ~80-225 minutes d'intervalle réel plutôt que les 15 minutes configurés. Les fenêtres de rattrapage élargies rendent la collecte **complète malgré cette irrégularité** (zéro perte), mais n'accélèrent pas la cadence elle-même. Le seul levier pour une vraie cadence 5-15 min réelle reste la migration vers un hôte auto-géré avec un cron système fiable (VPS/Windows, déjà exploré puis mis en pause dans ce projet).

---

## Annexe — Détails d'exécution de l'audit

- Run 1 (avant correction pagination) : commit `28b86dd`, run GitHub Actions `30763385045`, 2026-08-02 19:26-19:27 UTC.
- Run 2 (après correction pagination) : commit `ba151dd`, run GitHub Actions `30763568912`, 2026-08-02 19:31-19:32 UTC.
- Script d'audit : `data_collection/audit_pipeline.py` (temporaire, lecture seule, à supprimer une fois l'audit exploité).
- Workflow associé : `.github/workflows/audit_pipeline.yml` (temporaire, `workflow_dispatch` uniquement).
