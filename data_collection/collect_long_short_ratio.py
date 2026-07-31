"""
Collecte le ratio long/short (comptes) BTC/SOL sur Binance, via l'API
Coinalyze (endpoint long-short-ratio-history), et pousse les résultats
vers Supabase (table long_short_ratio_data, voir
supabase/migrations/20260731210500_long_short_ratio_data.sql).

Champs bruts renvoyés par Coinalyze (confirmés via le code source du
wrapper ivarurdalen/coinalyze, HistoryEndpoint.LSRATIO) :
  r -> ratio    (ratio long/short en nombre de comptes, ex: 1.19 =
                 1.19x plus de comptes en position long qu'en short)
  l -> longpct  (% de comptes en position long)
  s -> shortpct (% de comptes en position short)

IMPORTANT -- ce ratio porte sur le NOMBRE de comptes, pas sur les
volumes ou l'exposition en dollars : un petit nombre de gros comptes
peut peser autant qu'un grand nombre de petits comptes. A garder en
tête pour toute interprétation (ne pas confondre avec un ratio pondéré
par la taille des positions).

Même mécanique que collect_liquidations.py (résolution dynamique des
symboles Binance via /future-markets, fenêtre de lookback large 3h +
upsert idempotent on_conflict symbol+timestamp pour rattraper les creux
du cron GitHub Actions, irrégulier -- voir collect_liquidations.py pour
le détail). La logique d'appel Coinalyze commune est dans
coinalyze_client.py. Rate limit Coinalyze 40 req/min : ce script fait 2
appels par run (résolution symboles + historique groupé), comme
collect_liquidations.py -- largement sous la limite même si les deux
scripts tournent dans le même run du workflow.
"""

import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

import coinalyze_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("collect_long_short_ratio")

# base_asset Coinalyze -> libellé stocké dans Supabase
TARGETS = {"BTC": "BTCUSDT", "SOL": "SOLUSDT"}

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SUPABASE_TABLE = "long_short_ratio_data"

INTERVAL = "5min"  # 1min essayé initialement -> réponse vide (le ratio
                   # long/short est probablement calculé côté Binance à
                   # une granularité plus grossière que les liquidations,
                   # qui elles sont pilotées par un flux d'événements
                   # temps réel). Non confirmé formellement (pas d'accès
                   # direct à la doc Coinalyze), mais premier test simple.
LOOKBACK_HOURS = 3


def fetch_long_short_ratio_history(coinalyze_symbols: list) -> list:
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=LOOKBACK_HOURS)
    params = {
        "symbols": ",".join(coinalyze_symbols),
        "interval": INTERVAL,
        "from": int(start.timestamp()),
        "to": int(now.timestamp()),
    }
    return coinalyze_client.coinalyze_get("long-short-ratio-history", params)


def push_to_supabase(rows: list) -> bool:
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.error("SUPABASE_URL / SUPABASE_KEY manquants -- insertion annulée.")
        return False

    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{SUPABASE_TABLE}?on_conflict=symbol,timestamp"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        # merge-duplicates : upsert idempotent sur (symbol, timestamp) --
        # nécessaire puisqu'on refetch une fenêtre large à chaque run.
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    try:
        resp = requests.post(url, headers=headers, json=rows, timeout=30)
        resp.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Echec de l'upsert Supabase : {e}")
        return False


def main() -> int:
    if not coinalyze_client.COINALYZE_API_KEY:
        logger.error("COINALIZE_API_KEY manquant -- collecte annulée.")
        return 0

    symbol_map = coinalyze_client.resolve_symbols(TARGETS)
    missing = [base for base in TARGETS if base not in symbol_map]
    if missing:
        logger.error(f"Symboles introuvables sur Binance via Coinalyze : {missing}")
    if not symbol_map:
        logger.error("Aucun symbole résolu -- rien à collecter ce cycle.")
        return 0

    response = fetch_long_short_ratio_history(list(symbol_map.values()))
    label_by_coinalyze_symbol = {v: TARGETS[k] for k, v in symbol_map.items()}

    rows = []
    for market in response:
        label = label_by_coinalyze_symbol.get(market.get("symbol"))
        if not label:
            continue
        history = market.get("history", [])
        for bucket in history:
            rows.append({
                "timestamp": datetime.fromtimestamp(bucket["t"], tz=timezone.utc).isoformat(),
                "symbol": label,
                "interval": INTERVAL,
                "ratio": bucket.get("r"),
                "longpct": bucket.get("l"),
                "shortpct": bucket.get("s"),
            })
        logger.info(f"{label}: {len(history)} buckets {INTERVAL} récupérés (fenêtre {LOOKBACK_HOURS}h)")

    if not rows:
        logger.error("Aucune donnée de ratio long/short collectée ce cycle.")
        return 0

    if push_to_supabase(rows):
        logger.info(f"{len(rows)} ligne(s) upsertées dans Supabase (dédoublonnage sur symbol+timestamp).")
    else:
        logger.error(f"{len(rows)} ligne(s) collectée(s) mais NON insérée(s) dans Supabase.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
