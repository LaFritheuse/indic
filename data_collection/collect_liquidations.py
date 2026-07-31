"""
Collecte les liquidations BTC/SOL sur Binance (via l'API Coinalyze,
endpoint liquidation-history) et pousse les résultats vers Supabase
(table liquidations_data, voir liquidations_schema.sql).

IMPORTANT -- limite connue de la donnée : le flux public de liquidations
de Binance est échantillonné à 1 message/seconde maximum depuis 2021.
Lors des cascades de liquidations à fort volume, une partie des
liquidations réelles n'est donc PAS représentée : longvolume/shortvolume
sont une SOUS-ESTIMATION du volume réellement liquidé pendant les
périodes de forte volatilité, pas un décompte exhaustif. A garder en
tête pour toute interprétation future (ex: ne pas comparer directement
à l'open interest total, ne pas traiter ces chiffres comme complets).

Rate limit Coinalyze : 40 requêtes/minute par clé API (429 + en-tête
Retry-After en cas de dépassement). Ce script fait 2 appels par run
(résolution des symboles + historique liquidation pour les 2 symboles
en un seul appel groupé) -- largement sous la limite même si le cron
se déclenche plusieurs fois rapprochées.

Fenêtre de lookback volontairement large (3h, pas juste "les 15
dernières minutes") : liquidation-history renvoie des buckets datés
(pas une valeur instantanée comme funding/OI), et le cron GitHub Actions
de ce repo s'est révélé irrégulier (intervalle réel de 1h à 3h30 au lieu
des 15 min configurées). Une fenêtre large + upsert idempotent
(on_conflict symbol+timestamp) permet de rattraper automatiquement les
creux du cron sans dupliquer les lignes déjà collectées.
"""

import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / "vps_deploy" / ".env")
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("collect_liquidations")

COINALYZE_API_KEY = os.environ.get("COINALIZE_API_KEY")
COINALYZE_BASE_URL = "https://api.coinalyze.net/v1"
BINANCE_EXCHANGE_CODE = "A"  # confirmé via /exchanges (Binance -> "A")

# base_asset Coinalyze -> libellé stocké dans Supabase
TARGETS = {"BTC": "BTCUSDT", "SOL": "SOLUSDT"}

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SUPABASE_TABLE = "liquidations_data"

INTERVAL = "1min"
LOOKBACK_HOURS = 3
REQUEST_TIMEOUT_SECONDS = 20
MAX_ATTEMPTS = 4


def _coinalyze_get(path: str, params: dict) -> list:
    """GET sur l'API Coinalyze avec gestion du rate limit (429 + Retry-After)
    et des timeouts. Ne lève jamais d'exception -- retourne [] en cas
    d'échec définitif, à l'appelant de logger le contexte."""
    headers = {"api_key": COINALYZE_API_KEY}
    url = f"{COINALYZE_BASE_URL}/{path}"

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.exceptions.Timeout:
            logger.error(f"Timeout Coinalyze sur {path} (tentative {attempt}/{MAX_ATTEMPTS})")
            time.sleep(2 * attempt)
            continue
        except requests.exceptions.RequestException as e:
            logger.error(f"Erreur réseau Coinalyze sur {path} : {e}")
            return []

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "5"))
            logger.error(f"Rate limit Coinalyze (429) sur {path}, retry dans {retry_after}s (tentative {attempt}/{MAX_ATTEMPTS})")
            time.sleep(retry_after)
            continue

        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            logger.error(f"Erreur HTTP Coinalyze sur {path} : {e}")
            return []

        return resp.json()

    logger.error(f"Echec définitif sur {path} après {MAX_ATTEMPTS} tentatives.")
    return []


def resolve_symbols() -> dict:
    """base_asset (BTC/SOL) -> symbole Coinalyze exact (ex: BTCUSDT_PERP.A).
    Résolu dynamiquement via /future-markets plutôt que codé en dur, pour
    rester robuste si Coinalyze change un jour son format de symbole."""
    markets = _coinalyze_get("future-markets", {})
    resolved = {}
    for m in markets:
        if (
            m.get("exchange") == BINANCE_EXCHANGE_CODE
            and m.get("quote_asset") == "USDT"
            and m.get("is_perpetual")
            and m.get("base_asset") in TARGETS
        ):
            resolved[m["base_asset"]] = m["symbol"]
    return resolved


def fetch_liquidation_history(coinalyze_symbols: list) -> list:
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=LOOKBACK_HOURS)
    params = {
        "symbols": ",".join(coinalyze_symbols),
        "interval": INTERVAL,
        "from": int(start.timestamp()),
        "to": int(now.timestamp()),
    }
    return _coinalyze_get("liquidation-history", params)


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
    if not COINALYZE_API_KEY:
        logger.error("COINALIZE_API_KEY manquant -- collecte annulée.")
        return 0

    symbol_map = resolve_symbols()
    missing = [base for base in TARGETS if base not in symbol_map]
    if missing:
        logger.error(f"Symboles introuvables sur Binance via Coinalyze : {missing}")
    if not symbol_map:
        logger.error("Aucun symbole résolu -- rien à collecter ce cycle.")
        return 0

    response = fetch_liquidation_history(list(symbol_map.values()))
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
                "longvolume": bucket.get("l"),
                "shortvolume": bucket.get("s"),
            })
        logger.info(f"{label}: {len(history)} buckets {INTERVAL} récupérés (fenêtre {LOOKBACK_HOURS}h)")

    if not rows:
        logger.error("Aucune donnée de liquidation collectée ce cycle.")
        return 0

    if push_to_supabase(rows):
        logger.info(f"{len(rows)} ligne(s) upsertées dans Supabase (dédoublonnage sur symbol+timestamp).")
    else:
        logger.error(f"{len(rows)} ligne(s) collectée(s) mais NON insérée(s) dans Supabase.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
