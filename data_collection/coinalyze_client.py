"""
Fonctions partagées pour interroger l'API Coinalyze (clé API
COINALIZE_API_KEY -- voir data_collection/collect_liquidations.py pour
l'historique de ce nom de secret, rate limit 40 req/min). Utilisé par
collect_liquidations.py et collect_long_short_ratio.py, qui partagent la
même mécanique (résolution de symboles Binance, appel paginé par
fenêtre temporelle, gestion 429/timeout).
"""

import logging
import os
import time
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / "vps_deploy" / ".env")
except ImportError:
    pass

logger = logging.getLogger("coinalyze_client")

COINALYZE_API_KEY = os.environ.get("COINALIZE_API_KEY")
COINALYZE_BASE_URL = "https://api.coinalyze.net/v1"
BINANCE_EXCHANGE_CODE = "A"  # confirmé via /exchanges (Binance -> "A")

REQUEST_TIMEOUT_SECONDS = 20
MAX_ATTEMPTS = 4


def coinalyze_get(path: str, params: dict) -> list:
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


def resolve_symbols(targets: dict) -> dict:
    """base_asset (ex: BTC/SOL) -> symbole Coinalyze exact (ex:
    BTCUSDT_PERP.A). Résolu dynamiquement via /future-markets plutôt que
    codé en dur, pour rester robuste si Coinalyze change un jour son
    format de symbole. `targets` : dict base_asset -> libellé Supabase."""
    markets = coinalyze_get("future-markets", {})
    resolved = {}
    for m in markets:
        if (
            m.get("exchange") == BINANCE_EXCHANGE_CODE
            and m.get("quote_asset") == "USDT"
            and m.get("is_perpetual")
            and m.get("base_asset") in targets
        ):
            resolved[m["base_asset"]] = m["symbol"]
    return resolved
