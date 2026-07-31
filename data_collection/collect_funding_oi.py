"""
Collecte le funding rate et l'open interest de contrats perpetual OKX (via
ccxt) et pousse les résultats vers Supabase (table funding_oi_data, voir
supabase_schema.sql).

Binance a été écarté : son API renvoie une 451 "restricted location"
depuis les runners GitHub Actions hébergés (IP US), confirmé en pratique
(voir data_collection/diagnose_exchanges.py, supprimé depuis -- OKX,
Bitget, KuCoin Futures et HTX passaient, seul Bybit était aussi bloqué).
OKX a été retenu comme le plus liquide des quatre candidats valides.

Conçu pour tourner toutes les 15 minutes, via GitHub Actions
(.github/workflows/collect_data.yml) ou un hôte auto-géré (voir
data_collection/vps_deploy/ -- systemd sous Linux, tâche planifiée sous
Windows). Chaque cycle est indépendant : aucun état n'est conservé entre
deux runs. Chaque run fait un seul appel API par symbole pour la valeur
*actuelle* (pas d'historique, pas d'agrégation sur les 15 minutes) --
résultat : un instantané toutes les 15 minutes dans Supabase, pas une
collecte continue.

Anti-doublon : avant de collecter, vérifie le dernier timestamp déjà
enregistré pour chaque symbole -- si moins de DEDUP_THRESHOLD_MINUTES
(10 min), le cycle est sauté pour ce symbole. Protège contre un
double-déclenchement rapproché (dispatch manuel juste après/avant un run
planifié) sans risquer de sauter un cycle légitime (la cadence réelle
observée est de 70+ minutes entre deux runs).

Gestion d'erreurs : toute erreur réseau/API (OKX ou Supabase) est loggée
et n'interrompt jamais le processus avec un code de sortie non nul -- un
cycle raté ne doit pas faire échouer le run, le suivant réessaiera 15
minutes plus tard.
"""

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import ccxt

# Charge data_collection/vps_deploy/.env si présent (déploiement VPS/Windows
# auto-géré). Sans effet sur GitHub Actions : le fichier n'existe pas là-bas
# et les secrets arrivent déjà comme variables d'environnement -- dotenv ne
# les écrase jamais (override=False par défaut).
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / "vps_deploy" / ".env")
except ImportError:
    pass
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("collect_funding_oi")

# Symbole unifié ccxt -> libellé stocké dans Supabase.
# Ajouter une entrée ici suffit pour suivre un nouvel instrument.
SYMBOLS = {
    "BTC/USDT:USDT": "BTCUSDT",
    "SOL/USDT:USDT": "SOLUSDT",
}

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SUPABASE_TABLE = "funding_oi_data"

REQUEST_TIMEOUT_SECONDS = 15

# Anti-doublon : si le dernier point collecté pour ce symbole date de moins
# de DEDUP_THRESHOLD_MINUTES, on saute ce cycle. La cadence réelle observée
# (cron GitHub Actions irrégulier) est de 70+ minutes entre deux runs, donc
# un écart de quelques minutes ne peut venir que d'un double-déclenchement
# (dispatch manuel proche d'un run planifié, retry, etc.), pas d'un cycle
# normal -- ce seuil ne risque donc pas de sauter un run légitime.
DEDUP_THRESHOLD_MINUTES = 10


def get_last_timestamp(label: str):
    """Renvoie le timestamp du dernier point déjà collecté pour ce symbole,
    ou None si la vérification échoue ou qu'il n'y a encore rien -- dans le
    doute, on collecte quand même plutôt que de risquer de perdre un cycle."""
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{SUPABASE_TABLE}"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    params = {"select": "timestamp", "symbol": f"eq.{label}", "order": "timestamp.desc", "limit": "1"}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
        if data:
            return datetime.fromisoformat(data[0]["timestamp"].replace("Z", "+00:00"))
    except requests.exceptions.RequestException as e:
        logger.error(f"Impossible de vérifier le dernier point pour {label} (on collecte quand même par précaution) : {e}")
    except (ValueError, KeyError, IndexError) as e:
        logger.error(f"Réponse Supabase inattendue en vérifiant le dernier point pour {label} : {e}")
    return None


def fetch_funding_and_oi(exchange: ccxt.Exchange, ccxt_symbol: str) -> dict:
    """Récupère funding rate + open interest pour un symbole. Laisse
    remonter les exceptions ccxt -- gérées par l'appelant (main), qui sait
    à quel symbole elles se rapportent pour le log."""
    funding = exchange.fetch_funding_rate(ccxt_symbol)
    open_interest = exchange.fetch_open_interest(ccxt_symbol)
    return {
        "funding_rate": funding.get("fundingRate"),
        "open_interest": open_interest.get("openInterestAmount"),
    }


def push_to_supabase(rows: list) -> bool:
    """Insère une liste de lignes dans Supabase via l'API REST (PostgREST).
    Retourne True si l'insertion a réussi, False sinon (jamais d'exception
    qui remonte)."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.error("SUPABASE_URL et/ou SUPABASE_KEY absents de l'environnement -- insertion annulée.")
        return False

    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{SUPABASE_TABLE}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }

    try:
        response = requests.post(url, headers=headers, json=rows, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Echec de l'insertion Supabase : {e}")
        return False


def main() -> int:
    exchange = ccxt.okx({"enableRateLimit": True})
    now_utc = datetime.now(timezone.utc).isoformat()

    rows = []
    for ccxt_symbol, label in SYMBOLS.items():
        last_ts = get_last_timestamp(label)
        if last_ts is not None:
            gap_minutes = (datetime.now(timezone.utc) - last_ts).total_seconds() / 60
            if gap_minutes < DEDUP_THRESHOLD_MINUTES:
                logger.info(
                    f"{label}: déjà collecté il y a {gap_minutes:.1f} min "
                    f"(< {DEDUP_THRESHOLD_MINUTES} min) -- cycle sauté pour éviter un doublon."
                )
                continue

        try:
            data = fetch_funding_and_oi(exchange, ccxt_symbol)
            row = {
                "timestamp": now_utc,
                "symbol": label,
                "funding_rate": data["funding_rate"],
                "open_interest": data["open_interest"],
            }
            rows.append(row)
            logger.info(f"{label}: funding_rate={row['funding_rate']}, open_interest={row['open_interest']}")
        except (ccxt.NetworkError, ccxt.ExchangeError) as e:
            # Timeout, erreur HTTP, rate limit, symbole indisponible, etc.
            # -- on logge et on continue avec les autres symboles.
            logger.error(f"Erreur OKX pour {label} ({ccxt_symbol}) : {e}")
        except Exception as e:
            # Filet de sécurité : une erreur inattendue sur UN symbole ne
            # doit pas empêcher de traiter les autres ni de crasher le run.
            logger.error(f"Erreur inattendue pour {label} ({ccxt_symbol}) : {e}")

    if not rows:
        logger.info("Rien à envoyer à Supabase ce cycle (symboles sautés pour anti-doublon, ou tous en échec -- voir logs ci-dessus).")
        return 0

    if push_to_supabase(rows):
        logger.info(f"{len(rows)} ligne(s) insérée(s) dans Supabase avec succès.")
    else:
        logger.error(f"{len(rows)} ligne(s) collectée(s) mais NON insérée(s) dans Supabase (voir erreur ci-dessus).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
