"""
Collecte les gros trades individuels ("whale trades") BTC/SOL sur OKX
perpetual (BTC/USDT:USDT, SOL/USDT:USDT -- mêmes instruments que le
reste du pipeline) et pousse ceux dépassant un seuil de valeur
notionnelle vers Supabase (table whale_trades_data, voir
supabase/migrations/20260731224500_whale_trades_data.sql).

Seuil retenu par défaut : 100 000 $ de notionnel pour BTC et SOL. Ordre
de grandeur cohérent avec ce qui est généralement considéré comme un
trade "notable" sur ces paires (nettement au-dessus d'un ordre retail
typique) -- pas une référence figée : à ajuster (NOTIONAL_THRESHOLD_USD
ci-dessous) si le volume capté s'avère trop faible/élevé en usage réel.

Approche périodique (pas de WebSocket/stream continu, cohérent avec le
reste du pipeline GitHub Actions) : remonte dans le temps via
l'endpoint OKX history-trades (jusqu'à 3 mois d'historique, paginé par
timestamp) depuis maintenant jusqu'à couvrir une fenêtre de
LOOKBACK_HOURS, filtre les trades sous le seuil, et upsert le reste
(idempotent sur (symbol, trade_id) -- même logique que
collect_liquidations.py / collect_long_short_ratio.py, qui rattrape les
creux du cron GitHub Actions, empiriquement irrégulier).

IMPORTANT -- unité de taille (sz) : sur les swaps perpetual OKX, sz est
exprimé en CONTRATS, pas en unité de l'actif sous-jacent (même piège
que openInterestAmount, déjà rencontré et corrigé pour funding_oi_data
-- voir oi_usd). Converti ici via market['contractSize'] (0.01 BTC et
1 SOL au moment de l'écriture, confirmé via l'API OKX pour l'open
interest -- non revérifié spécifiquement pour l'endpoint trades, à
confirmer au premier run réel).

IMPORTANT -- limite de couverture, à vérifier au premier run réel (pas
d'accès réseau à l'API OKX depuis l'environnement où ce script a été
écrit) : la pagination utilise le paramètre `type=2` (pagination par
timestamp) de l'endpoint history-trades, plafonnée à
MAX_PAGES_PER_SYMBOL pages de PAGE_LIMIT trades. Si le volume total de
trades sur une paire dépasse ce plafond pendant un creux de cron, les
trades les plus anciens de la fenêtre seraient tronqués (log
d'avertissement si le plafond est atteint, mais pas d'erreur bloquante).
"""

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ccxt

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / "vps_deploy" / ".env")
except ImportError:
    pass
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("collect_whale_trades")

SYMBOLS = {"BTC/USDT:USDT": "BTCUSDT", "SOL/USDT:USDT": "SOLUSDT"}

# Seuil de notionnel ($) pour qu'un trade soit considéré "gros". Par
# symbole pour pouvoir ajuster indépendamment plus tard (voir docstring).
NOTIONAL_THRESHOLD_USD = {"BTCUSDT": 100_000, "SOLUSDT": 100_000}

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SUPABASE_TABLE = "whale_trades_data"

# Fenêtre large (comme collect_liquidations.py) pour rattraper les
# creux du cron GitHub Actions -- upsert idempotent en aval.
LOOKBACK_HOURS = 3
PAGE_LIMIT = 100            # max autorisé par OKX sur history-trades
MAX_PAGES_PER_SYMBOL = 30   # plafond de sécurité (30*100 = 3000 trades/symbole/run)
REQUEST_TIMEOUT_SECONDS = 20


def fetch_recent_trades(exchange: ccxt.Exchange, market_id: str, since_ms: int) -> list:
    """Remonte dans le temps via l'endpoint OKX history-trades
    (pagination par timestamp, type=2) jusqu'à couvrir since_ms ou
    atteindre MAX_PAGES_PER_SYMBOL. Retourne les trades bruts OKX
    (dicts avec tradeId/side/px/sz/ts) dont ts >= since_ms."""
    all_trades = []
    after_ts = None  # None = partir des trades les plus récents

    for page in range(MAX_PAGES_PER_SYMBOL):
        params = {"instId": market_id, "type": "2", "limit": str(PAGE_LIMIT)}
        if after_ts is not None:
            params["after"] = str(after_ts)
        response = exchange.public_get_market_history_trades(params)
        batch = response.get("data", [])
        if not batch:
            break
        all_trades.extend(batch)

        oldest_ts = min(int(t["ts"]) for t in batch)
        if oldest_ts <= since_ms:
            break
        after_ts = oldest_ts

        if page == MAX_PAGES_PER_SYMBOL - 1:
            logger.warning(
                f"{market_id}: plafond de {MAX_PAGES_PER_SYMBOL} pages atteint -- "
                f"la fenêtre de {LOOKBACK_HOURS}h n'a peut-être pas été couverte en entier."
            )

    return [t for t in all_trades if int(t["ts"]) >= since_ms]


def push_to_supabase(rows: list) -> bool:
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.error("SUPABASE_URL / SUPABASE_KEY manquants -- insertion annulée.")
        return False

    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{SUPABASE_TABLE}?on_conflict=symbol,trade_id"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        # merge-duplicates : upsert idempotent sur (symbol, trade_id) --
        # nécessaire puisqu'on refetch une fenêtre large à chaque run.
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    try:
        resp = requests.post(url, headers=headers, json=rows, timeout=REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Echec de l'upsert Supabase : {e}")
        return False


def main() -> int:
    exchange = ccxt.okx({"enableRateLimit": True})
    exchange.load_markets()
    since_ms = int((datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).timestamp() * 1000)

    all_rows = []
    for ccxt_symbol, label in SYMBOLS.items():
        try:
            market = exchange.market(ccxt_symbol)
            contract_size = float(market.get("contractSize") or 1)
            raw_trades = fetch_recent_trades(exchange, market["id"], since_ms)
        except (ccxt.NetworkError, ccxt.ExchangeError) as e:
            logger.error(f"Erreur OKX pour {label} ({ccxt_symbol}) : {e}")
            continue

        threshold = NOTIONAL_THRESHOLD_USD[label]
        rows = []
        for t in raw_trades:
            price = float(t["px"])
            amount = float(t["sz"]) * contract_size  # contrats -> unités de l'actif
            notional = price * amount
            if notional < threshold:
                continue
            rows.append({
                "timestamp": datetime.fromtimestamp(int(t["ts"]) / 1000, tz=timezone.utc).isoformat(),
                "symbol": label,
                "trade_id": str(t["tradeId"]),
                "side": t["side"],
                "price": price,
                "amount": amount,
                "notional_usd": notional,
            })

        logger.info(
            f"{label}: {len(raw_trades)} trades examinés (fenêtre {LOOKBACK_HOURS}h), "
            f"{len(rows)} au-dessus du seuil {threshold:,.0f}$"
        )
        all_rows.extend(rows)

    if not all_rows:
        logger.info("Aucun whale trade détecté ce cycle.")
        return 0

    if push_to_supabase(all_rows):
        logger.info(f"{len(all_rows)} ligne(s) upsertées dans Supabase (dédoublonnage sur symbol+trade_id).")
    else:
        logger.error(f"{len(all_rows)} ligne(s) détectée(s) mais NON insérée(s) dans Supabase.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
