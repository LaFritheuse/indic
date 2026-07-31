"""
Test de bout en bout (temporaire) du pipeline funding/OI : récupère les
OHLCV OKX correspondant aux timestamps déjà collectés dans Supabase,
joint les deux jeux de données sur le timestamp le plus proche, produit
un graphique prix + funding_rate par symbole, et un résumé statistique
funding_rate / open_interest.

Ceci teste UNIQUEMENT la mécanique du pipeline (collecte -> stockage ->
récupération -> jointure -> visualisation), pas la qualité d'un signal.
Avec ~14 points sur ~26h et une résolution de 1-3h (cf. problème de cron
GitHub Actions connu), ce n'est pas un échantillon exploitable pour une
quelconque conclusion de trading.

A supprimer une fois le test terminé (diagnostic ponctuel).
"""

import os
from datetime import datetime, timezone

import ccxt
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TABLE = "funding_oi_data"

SYMBOLS = {
    "BTCUSDT": "BTC/USDT:USDT",
    "SOLUSDT": "SOL/USDT:USDT",
}


def fetch_funding_oi(symbol: str) -> pd.DataFrame:
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{TABLE}"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    params = {
        "select": "timestamp,symbol,funding_rate,open_interest",
        "symbol": f"eq.{symbol}",
        "order": "timestamp.asc",
        "limit": "10000",
    }
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    df = pd.DataFrame(resp.json())
    # .as_unit("ns") : pandas >=3.0 exige que les deux côtés d'un merge_asof
    # aient exactement la même résolution datetime64 (ns ici, vs le ms des
    # bougies OHLCV) -- sinon MergeError.
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.as_unit("ns")
    return df


def fetch_ohlcv(exchange, ccxt_symbol: str, start: datetime, end: datetime, timeframe: str = "5m") -> pd.DataFrame:
    since_ms = int(start.timestamp() * 1000) - 3600_000  # marge d'1h avant
    all_candles = []
    while True:
        candles = exchange.fetch_ohlcv(ccxt_symbol, timeframe=timeframe, since=since_ms, limit=300)
        if not candles:
            break
        all_candles.extend(candles)
        last_ts = candles[-1][0]
        if last_ts >= int(end.timestamp() * 1000) or len(candles) < 300:
            break
        since_ms = last_ts + 1

    df = pd.DataFrame(all_candles, columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True).dt.as_unit("ns")
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


def analyze_symbol(label: str, ccxt_symbol: str, exchange):
    fo = fetch_funding_oi(label)
    if fo.empty:
        print(f"{label}: aucune donnée funding/OI dans Supabase.")
        return

    start, end = fo["timestamp"].min(), fo["timestamp"].max()
    ohlcv = fetch_ohlcv(exchange, ccxt_symbol, start.to_pydatetime(), end.to_pydatetime(), timeframe="5m")
    print(f"{label}: {len(fo)} points funding/OI, {len(ohlcv)} bougies OHLCV 5m OKX ({start} -> {end})")

    ohlcv_path = f"ohlcv_{label}_5m.parquet"
    ohlcv.to_parquet(ohlcv_path)
    print(f"OHLCV sauvegardées : {ohlcv_path}")

    # Jointure sur le timestamp le plus proche
    fo_sorted = fo.sort_values("timestamp")
    ohlcv_sorted = ohlcv.sort_values("timestamp")
    joined = pd.merge_asof(
        fo_sorted, ohlcv_sorted, on="timestamp", direction="nearest", tolerance=pd.Timedelta("30min")
    )

    n_matched = joined["close"].notna().sum()
    print(f"{label}: {n_matched}/{len(joined)} points funding/OI matchés à une bougie (tolérance 30 min)")

    # Stats funding_rate / open_interest
    stats = joined[["funding_rate", "open_interest"]].agg(["mean", "min", "max", "std"])
    print(f"\n--- Statistiques {label} (funding_rate / open_interest) ---")
    print(stats.to_string())

    # Graphique : prix (ligne) + funding_rate (subplot dessous)
    fig, (ax_price, ax_funding) = plt.subplots(2, 1, figsize=(10, 6), sharex=True, height_ratios=[2, 1])
    ax_price.plot(ohlcv_sorted["timestamp"], ohlcv_sorted["close"], color="steelblue", linewidth=1)
    ax_price.set_ylabel("Prix (close)")
    ax_price.set_title(f"{label} — prix OKX 5m + funding_rate (test mécanique pipeline, {len(fo)} points sur {(end-start)})")

    ax_funding.plot(joined["timestamp"], joined["funding_rate"], color="darkorange", marker="o", markersize=4, linewidth=1)
    ax_funding.axhline(0, color="grey", linewidth=0.5)
    ax_funding.set_ylabel("funding_rate")
    ax_funding.set_xlabel("Temps (UTC)")

    fig.autofmt_xdate()
    plt.tight_layout()
    out_path = f"pipeline_test_{label}.png"
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    print(f"Graphique sauvegardé : {out_path}")


def main():
    exchange = ccxt.okx({"enableRateLimit": True})
    for label, ccxt_symbol in SYMBOLS.items():
        analyze_symbol(label, ccxt_symbol, exchange)
        print()


if __name__ == "__main__":
    main()
