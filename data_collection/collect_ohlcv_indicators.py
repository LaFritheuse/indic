"""
Calcule VWAP et CVD (Cumulative Volume Delta) à partir des bougies OHLCV
OKX (via ccxt) pour BTC/SOL perpetual, et pousse le résultat vers
Supabase (table ohlcv_indicators, voir
supabase/migrations/20260731211000_ohlcv_indicators.sql).

Pas de nouvelle source externe : ce script recalcule tout depuis les
bougies déjà récupérables via ccxt -- aucune dépendance à une donnée
tick-by-tick.

VWAP et CVD sont tous les deux ancrés sur la journée calendaire UTC
(reset à 00:00 UTC), convention standard pour un usage intraday (c'est
aussi le comportement par défaut de l'indicateur CVD de TradingView) --
pas un cumul depuis le début de la collecte.

LIMITE IMPORTANTE sur le CVD : l'API OHLCV unifiée de ccxt (et OKX en
général) ne fournit pas le volume acheteur/vendeur réel (côté
agresseur) -- seul Binance expose un champ "taker buy base volume" sur
son endpoint natif, non repris par ccxt.fetch_ohlcv(). Le CVD calculé
ici est donc une APPROXIMATION classique par la couleur de bougie :
volume compté + si close > open (bougie haussière), - si close < open,
0 sinon. Ce n'est PAS un delta d'ordre réel, juste un proxy directionnel
usuel quand seules des données OHLCV sont disponibles.

Fenêtre de lookback (LOOKBACK_HOURS, 48h) volontairement large par
rapport au cron (15 min configuré, cadence réelle irrégulière -- voir
collect_liquidations.py) : garantit que la bougie la plus ancienne de la
journée UTC en cours est toujours incluse, même après un creux de cron,
pour que le VWAP/CVD du jour restent calculés sur la totalité des
bougies disponibles depuis minuit UTC. Recalcul complet à chaque run
(pas d'état conservé entre deux runs) + upsert idempotent (on_conflict
symbol+timestamp+interval) : le résultat pour une bougie donnée est
donc déterministe, peu importe quand/combien de fois ce script tourne.
"""

import logging
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ccxt
import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / "vps_deploy" / ".env")
except ImportError:
    pass
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("collect_ohlcv_indicators")

SYMBOLS = {"BTC/USDT:USDT": "BTCUSDT", "SOL/USDT:USDT": "SOLUSDT"}

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SUPABASE_TABLE = "ohlcv_indicators"

TIMEFRAME = "5m"
LOOKBACK_HOURS = 48
REQUEST_TIMEOUT_SECONDS = 30


def fetch_ohlcv(exchange: ccxt.Exchange, ccxt_symbol: str, since: datetime) -> pd.DataFrame:
    since_ms = int(since.timestamp() * 1000)
    all_candles = []
    while True:
        candles = exchange.fetch_ohlcv(ccxt_symbol, timeframe=TIMEFRAME, since=since_ms, limit=300)
        if not candles:
            break
        all_candles.extend(candles)
        if len(candles) < 300:
            break
        since_ms = candles[-1][0] + 1

    df = pd.DataFrame(all_candles, columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calcule VWAP et CVD, tous deux ancrés sur la journée calendaire
    UTC (reset à 00:00 UTC pour chaque nouvelle journée)."""
    df = df.sort_values("timestamp").reset_index(drop=True)
    day = df["timestamp"].dt.floor("D")

    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    pv_cum = (typical_price * df["volume"]).groupby(day).cumsum()
    vol_cum = df["volume"].groupby(day).cumsum()
    df["vwap"] = pv_cum / vol_cum

    signed_volume = df["volume"].where(df["close"] > df["open"], -df["volume"])
    signed_volume = signed_volume.where(df["close"] != df["open"], 0.0)
    df["cvd"] = signed_volume.groupby(day).cumsum()

    return df


def _safe_float(v):
    """Convertit en float JSON-safe : None/NaN/inf -> None (NaN/inf ne
    sont pas du JSON valide, PostgREST les rejetterait)."""
    if v is None:
        return None
    v = float(v)
    return v if math.isfinite(v) else None


def push_to_supabase(rows: list) -> bool:
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.error("SUPABASE_URL / SUPABASE_KEY manquants -- insertion annulée.")
        return False

    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{SUPABASE_TABLE}?on_conflict=symbol,timestamp,interval"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
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
    since = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

    for ccxt_symbol, label in SYMBOLS.items():
        try:
            df = fetch_ohlcv(exchange, ccxt_symbol, since)
        except (ccxt.NetworkError, ccxt.ExchangeError) as e:
            logger.error(f"Erreur OKX pour {label} ({ccxt_symbol}) : {e}")
            continue

        if df.empty:
            logger.error(f"{label}: aucune bougie récupérée.")
            continue

        df = compute_indicators(df)
        rows = [
            {
                "timestamp": r.timestamp.isoformat(),
                "symbol": label,
                "interval": TIMEFRAME,
                "open": _safe_float(r.open),
                "high": _safe_float(r.high),
                "low": _safe_float(r.low),
                "close": _safe_float(r.close),
                "volume": _safe_float(r.volume),
                "vwap": _safe_float(r.vwap),
                "cvd": _safe_float(r.cvd),
            }
            for r in df.itertuples()
        ]

        logger.info(
            f"{label}: {len(rows)} bougies {TIMEFRAME} calculées "
            f"(VWAP/CVD ancrés sur la journée UTC, fenêtre {LOOKBACK_HOURS}h)"
        )

        if push_to_supabase(rows):
            logger.info(f"{label}: {len(rows)} ligne(s) upsertées dans Supabase.")
        else:
            logger.error(f"{label}: {len(rows)} ligne(s) calculée(s) mais NON insérée(s) dans Supabase.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
