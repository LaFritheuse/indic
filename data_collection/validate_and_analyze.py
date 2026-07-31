"""
Script de diagnostic temporaire (à supprimer une fois utilisé) :

Partie 1 -- Validation d'exactitude :
  1. Compare les derniers points de funding_oi_data aux valeurs live OKX.
  2. Vérifie l'absence de doublons dans liquidations_data malgré l'upsert.
  3. Inspecte la structure brute de la réponse OKX open-interest pour
     déterminer si openInterestAmount est en contrats ou en unité de
     l'actif sous-jacent (pas juste "une valeur", la BONNE valeur).
  4. Signale les anomalies (funding_rate à 0, OI qui s'effondre puis
     remonte, gaps temporels anormaux).

Partie 2 -- Test d'exploitation réaliste :
  Joint OHLCV (OKX 5m) + funding_oi_data + liquidations_data sur le
  timestamp le plus proche. Calcule, par symbole :
  - la variation de prix à +15min/+30min après chaque pic de liquidation
    (top 20% du volume total liquidé par bucket 1min)
  - la corrélation simple entre variation d'OI et variation de prix
    (sur les points funding_oi_data consécutifs, forcément irréguliers)

IMPORTANT : échantillon actuel de quelques jours seulement -- tout ce qui
suit est INDICATIF, pas une validation statistique de signal.
"""

import os
from datetime import timedelta
from pathlib import Path

import ccxt
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

SYMBOLS = {"BTCUSDT": "BTC/USDT:USDT", "SOLUSDT": "SOL/USDT:USDT"}

RESULTS_DIR = Path("results")
DATA_DIR = Path("data/crypto_5m")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)


def supabase_get(table: str, params: dict) -> pd.DataFrame:
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{table}"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    df = pd.DataFrame(resp.json())
    if not df.empty and "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.as_unit("ns")
    return df


def fetch_ohlcv(exchange, ccxt_symbol: str, start, end, timeframe="5m") -> pd.DataFrame:
    since_ms = int(start.timestamp() * 1000) - 3600_000
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


# =====================================================================
# PARTIE 1 -- Validation d'exactitude
# =====================================================================

def part1_validate(exchange, label, ccxt_symbol):
    print(f"\n{'='*70}\nPARTIE 1 -- {label}\n{'='*70}")

    # --- 1. Derniers points stockés vs valeurs live OKX ---
    recent = supabase_get("funding_oi_data", {
        "select": "timestamp,funding_rate,open_interest",
        "symbol": f"eq.{label}", "order": "timestamp.desc", "limit": "4",
    })
    print(f"\n-- 1. Derniers points funding_oi_data ({len(recent)}) --")
    print(recent.to_string(index=False))

    live_funding = exchange.fetch_funding_rate(ccxt_symbol)
    live_oi = exchange.fetch_open_interest(ccxt_symbol)
    live_rate = live_funding.get("fundingRate")
    live_oi_amount = live_oi.get("openInterestAmount")
    print(f"\nLive OKX maintenant : funding_rate={live_rate}, open_interest={live_oi_amount}")

    if not recent.empty:
        last_row = recent.iloc[0]
        rate_diff_pct = None
        oi_diff_pct = None
        if live_rate not in (None, 0) and last_row["funding_rate"] is not None:
            rate_diff_pct = 100 * (last_row["funding_rate"] - live_rate) / abs(live_rate)
        if live_oi_amount not in (None, 0) and last_row["open_interest"] is not None:
            oi_diff_pct = 100 * (last_row["open_interest"] - live_oi_amount) / abs(live_oi_amount)
        print(f"Dernier point stocké ({last_row['timestamp']}) vs live : "
              f"funding_rate écart={rate_diff_pct:.2f}% , open_interest écart={oi_diff_pct:.2f}%"
              if rate_diff_pct is not None and oi_diff_pct is not None else "Comparaison impossible (valeur nulle)")

    # --- 3. Unités : inspection brute de la réponse OKX ---
    print(f"\n-- 3. Structure brute open-interest OKX (pour vérifier contrats vs sous-jacent) --")
    print("live_oi (parsé ccxt) :", {k: v for k, v in live_oi.items() if k != "info"})
    print("live_oi['info'] (brut OKX) :", live_oi.get("info"))

    # --- 4. Anomalies sur funding_oi_data ---
    hist = supabase_get("funding_oi_data", {
        "select": "timestamp,funding_rate,open_interest",
        "symbol": f"eq.{label}", "order": "timestamp.asc", "limit": "10000",
    })
    print(f"\n-- 4. Anomalies funding_oi_data ({len(hist)} points au total) --")
    if not hist.empty:
        zero_funding = hist[hist["funding_rate"] == 0]
        print(f"funding_rate == 0 : {len(zero_funding)} point(s)")
        if len(zero_funding):
            print(zero_funding.to_string(index=False))

        oi_series = hist["open_interest"].astype(float)
        near_zero_oi = hist[oi_series < oi_series.median() * 0.1]
        print(f"open_interest < 10% de la médiane (effondrement suspect) : {len(near_zero_oi)} point(s)")
        if len(near_zero_oi):
            print(near_zero_oi.to_string(index=False))

        gaps = hist["timestamp"].diff().dt.total_seconds() / 60
        big_gaps = gaps[gaps > 240]
        print(f"gaps > 4h entre deux points : {len(big_gaps)}")
    else:
        print("Aucune donnée.")

    return live_oi, hist


def part1_duplicates():
    print(f"\n{'='*70}\nPARTIE 1.2 -- Doublons liquidations_data\n{'='*70}")
    df = supabase_get("liquidations_data", {
        "select": "symbol,timestamp,longvolume,shortvolume", "order": "timestamp.asc", "limit": "20000",
    })
    print(f"Total lignes récupérées : {len(df)}")
    if df.empty:
        return df
    dupes = df[df.duplicated(subset=["symbol", "timestamp"], keep=False)]
    print(f"Doublons (même symbol+timestamp) : {len(dupes)}")
    if len(dupes):
        print(dupes.sort_values(["symbol", "timestamp"]).to_string(index=False))
    else:
        print("Aucun doublon détecté -- l'upsert (symbol, timestamp) fonctionne comme prévu.")
    return df


# =====================================================================
# PARTIE 2 -- Test d'exploitation réaliste
# =====================================================================

def part2_analysis(exchange, label, ccxt_symbol, liq_df):
    print(f"\n{'='*70}\nPARTIE 2 -- {label}\n{'='*70}")

    fo = supabase_get("funding_oi_data", {
        "select": "timestamp,funding_rate,open_interest",
        "symbol": f"eq.{label}", "order": "timestamp.asc", "limit": "10000",
    })
    liq = liq_df[liq_df["symbol"] == label].copy().sort_values("timestamp")

    if fo.empty and liq.empty:
        print("Aucune donnée funding/OI ni liquidations pour ce symbole.")
        return

    all_ts = pd.concat([fo["timestamp"], liq["timestamp"]]) if not fo.empty and not liq.empty else (
        fo["timestamp"] if not fo.empty else liq["timestamp"]
    )
    start, end = all_ts.min(), all_ts.max()
    print(f"Période couverte : {start} -> {end} ({(end - start)})")

    ohlcv = fetch_ohlcv(exchange, ccxt_symbol, start.to_pydatetime(), end.to_pydatetime(), timeframe="5m")
    ohlcv = ohlcv.sort_values("timestamp").reset_index(drop=True)
    print(f"{len(ohlcv)} bougies OHLCV 5m OKX récupérées.")

    ohlcv_path = DATA_DIR / f"{label}_5m_joined_period.parquet"
    ohlcv.to_parquet(ohlcv_path)

    # --- Réaction de prix après un pic de liquidation ---
    if not liq.empty:
        liq["total_volume"] = liq["longvolume"].fillna(0) + liq["shortvolume"].fillna(0)
        threshold = liq["total_volume"].quantile(0.8)
        spikes = liq[liq["total_volume"] >= threshold].copy()
        print(f"\nSeuil top 20% volume liquidé (bucket 1min) : {threshold:.2f}")
        print(f"{len(spikes)} buckets de pic sur {len(liq)} au total.")

        def price_at_or_after(ts):
            idx = ohlcv["timestamp"].searchsorted(ts)
            return ohlcv.iloc[idx]["close"] if idx < len(ohlcv) else np.nan

        def price_after_delta(ts, minutes):
            target = ts + timedelta(minutes=minutes)
            idx = ohlcv["timestamp"].searchsorted(target)
            return ohlcv.iloc[idx]["close"] if idx < len(ohlcv) else np.nan

        spikes["price_t0"] = spikes["timestamp"].apply(price_at_or_after)
        spikes["price_t15"] = spikes["timestamp"].apply(lambda t: price_after_delta(t, 15))
        spikes["price_t30"] = spikes["timestamp"].apply(lambda t: price_after_delta(t, 30))
        spikes["ret_15min_pct"] = 100 * (spikes["price_t15"] - spikes["price_t0"]) / spikes["price_t0"]
        spikes["ret_30min_pct"] = 100 * (spikes["price_t30"] - spikes["price_t0"]) / spikes["price_t0"]

        valid = spikes.dropna(subset=["ret_15min_pct", "ret_30min_pct"])
        print(f"\nVariation de prix après un pic de liquidation ({len(valid)} pics exploitables) :")
        if len(valid):
            print(f"  +15min : moyenne={valid['ret_15min_pct'].mean():.3f}%, "
                  f"médiane={valid['ret_15min_pct'].median():.3f}%, std={valid['ret_15min_pct'].std():.3f}%")
            print(f"  +30min : moyenne={valid['ret_30min_pct'].mean():.3f}%, "
                  f"médiane={valid['ret_30min_pct'].median():.3f}%, std={valid['ret_30min_pct'].std():.3f}%")

            fig, ax = plt.subplots(figsize=(8, 5))
            ax.bar(["+15min", "+30min"], [valid["ret_15min_pct"].mean(), valid["ret_30min_pct"].mean()],
                   yerr=[valid["ret_15min_pct"].std(), valid["ret_30min_pct"].std()], capsize=6, color="darkorange")
            ax.axhline(0, color="grey", linewidth=0.8)
            ax.set_ylabel("Variation de prix moyenne (%)")
            ax.set_title(f"{label} -- réaction prix après pic de liquidation (n={len(valid)}, INDICATIF)")
            plt.tight_layout()
            fig.savefig(RESULTS_DIR / f"liq_spike_reaction_{label}.png", dpi=120)
            plt.close(fig)
        else:
            print("  Pas assez de points exploitables (hors limites de la fenêtre OHLCV).")

    # --- Corrélation variation OI vs variation prix ---
    if not fo.empty:
        fo_sorted = fo.sort_values("timestamp")
        joined = pd.merge_asof(fo_sorted, ohlcv, on="timestamp", direction="nearest", tolerance=pd.Timedelta("30min"))
        joined = joined.dropna(subset=["close", "open_interest"])
        joined["oi_diff"] = joined["open_interest"].diff()
        joined["price_diff_pct"] = 100 * joined["close"].pct_change()
        corr_df = joined.dropna(subset=["oi_diff", "price_diff_pct"])
        print(f"\nCorrélation variation OI / variation prix ({len(corr_df)} points consécutifs, gaps irréguliers) :")
        if len(corr_df) >= 3:
            corr = corr_df["oi_diff"].corr(corr_df["price_diff_pct"])
            print(f"  Corrélation de Pearson : {corr:.3f}")

            fig, ax = plt.subplots(figsize=(6, 6))
            ax.scatter(corr_df["oi_diff"], corr_df["price_diff_pct"], alpha=0.6, color="steelblue")
            ax.set_xlabel("Variation open_interest")
            ax.set_ylabel("Variation prix (%)")
            ax.set_title(f"{label} -- OI vs prix (r={corr:.3f}, n={len(corr_df)}, INDICATIF)")
            ax.axhline(0, color="grey", linewidth=0.5)
            ax.axvline(0, color="grey", linewidth=0.5)
            plt.tight_layout()
            fig.savefig(RESULTS_DIR / f"oi_price_correlation_{label}.png", dpi=120)
            plt.close(fig)
        else:
            print("  Pas assez de points pour une corrélation significative.")


def main():
    exchange = ccxt.okx({"enableRateLimit": True})

    liq_df = part1_duplicates()

    for label, ccxt_symbol in SYMBOLS.items():
        part1_validate(exchange, label, ccxt_symbol)

    for label, ccxt_symbol in SYMBOLS.items():
        part2_analysis(exchange, label, ccxt_symbol, liq_df if not liq_df.empty else pd.DataFrame(columns=["symbol", "timestamp", "longvolume", "shortvolume"]))

    print(f"\n{'='*70}\nRAPPEL IMPORTANT\n{'='*70}")
    print("Échantillon actuel = quelques jours de collecte seulement, avec une")
    print("cadence de collecte irrégulière pour funding_oi_data (cron GitHub")
    print("Actions documenté comme peu fiable). Tous les résultats de la Partie 2")
    print("(réaction prix post-liquidation, corrélation OI/prix) sont INDICATIFS")
    print("uniquement -- ce n'est PAS une validation statistique de signal.")


if __name__ == "__main__":
    main()
