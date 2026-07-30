"""
Script de diagnostic temporaire (pas destiné à tourner en continu) : teste
plusieurs exchanges supportés par ccxt pour trouver lequel expose funding
rate + open interest sur BTC/USDT perpetual SANS être géo-bloqué depuis les
runners GitHub Actions hébergés (Binance renvoie une 451 "restricted
location" depuis ces runners -- voir data_collection/collect_funding_oi.py).

A supprimer une fois l'exchange définitif choisi.
"""

import logging

import ccxt

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("diagnose_exchanges")

CANDIDATES = {
    "okx": "BTC/USDT:USDT",
    "bitget": "BTC/USDT:USDT",
    "kucoinfutures": "BTC/USDT:USDT",
    "htx": "BTC/USDT:USDT",
    "bybit": "BTC/USDT:USDT",
}


def main():
    results = {}
    for exchange_id, symbol in CANDIDATES.items():
        try:
            exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})
            funding = exchange.fetch_funding_rate(symbol)
            oi = exchange.fetch_open_interest(symbol)
            logger.info(
                f"OK {exchange_id}: fundingRate={funding.get('fundingRate')}, "
                f"openInterestAmount={oi.get('openInterestAmount')}"
            )
            results[exchange_id] = "OK"
        except Exception as e:
            logger.error(f"ECHEC {exchange_id}: {type(e).__name__}: {e}")
            results[exchange_id] = f"ECHEC: {e}"

    print("\n=== Résumé ===")
    for exchange_id, status in results.items():
        print(f"{exchange_id}: {status}")


if __name__ == "__main__":
    main()
