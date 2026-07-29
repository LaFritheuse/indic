"""
Same neutral statistical exploration as explore_market_structure.py, run on
EURUSD 15m / 1h / 4h side by side, plus a 6th point: average number of
MM9/21 crossovers per month per timeframe (pure frequency proxy, not a
strategy test). No trading logic, no signal, no strategy.

Usage:
    python scripts/explore_timeframe_comparison.py
"""

import numpy as np
import pandas as pd
from scipy.stats import skew

from engine.data_loader import load_ohlcv
from engine.signals import ma_crossover_signal
from scripts.explore_market_structure import (
    HISTDATA_TO_UTC_OFFSET_HOURS,
    rolling_adf,
    rolling_hurst,
)

# Lags/windows adapted to each timeframe's own scale (kept at comparable
# CALENDAR spans across timeframes: ~5 days and ~21 days for ADF/Hurst
# windows, same convention as the 15m-only exploration).
TF_CONFIGS = {
    "15m": {
        "path": "data/eurusd_15m/EURUSD_15m.parquet",
        "lags": [1, 5, 20, 50],          # 15min, 1h15, 5h, 12h30
        "windows": [500, 2000],           # ~5.2 days, ~20.8 days
    },
    "1h": {
        "path": "data/eurusd_15m/EURUSD_1h.parquet",
        "lags": [1, 4, 24, 48],           # 1h, 4h, 1 day, 2 days
        "windows": [120, 504],            # 5 days, 21 days
    },
    "4h": {
        "path": "data/eurusd_15m/EURUSD_4h.parquet",
        "lags": [1, 6, 30, 60],           # 4h, 1 day, 5 days, 10 days
        "windows": [30, 126],             # 5 days, 21 days
    },
}


def analyze_timeframe(label: str, cfg: dict) -> dict:
    df = load_ohlcv(cfg["path"])
    close = df["close"]
    returns = close.pct_change().dropna()
    lags = cfg["lags"]
    windows = cfg["windows"]

    result = {"timeframe": label, "n_bars": len(df), "date_start": df.index[0], "date_end": df.index[-1]}

    # 1. Autocorrelation of returns
    result["autocorr_returns"] = {lag: round(returns.autocorr(lag=lag), 5) for lag in lags}

    # 2. Rolling ADF
    adf_summary = {}
    for window in windows:
        stride = max(window // 5, 1)
        res = rolling_adf(close, window, stride)
        pct_reject = 100 * (res["p_value"] < 0.05).mean() if len(res) else None
        adf_summary[window] = {
            "n_fenetres": len(res),
            "adf_stat_moyen": round(res["adf_stat"].mean(), 3) if len(res) else None,
            "pct_stationnaires": round(pct_reject, 1) if pct_reject is not None else None,
        }
    result["adf"] = adf_summary

    # 3. Rolling Hurst (on returns, not raw price — see explore_market_structure.hurst_rs)
    hurst_summary = {}
    for window in windows:
        stride = max(window // 5, 1)
        h_vals = rolling_hurst(returns, window, stride)
        hurst_summary[window] = {
            "n_fenetres": len(h_vals),
            "H_moyen": round(h_vals.mean(), 3) if len(h_vals) else None,
            "pct_trending": round(100 * (h_vals > 0.55).mean(), 1) if len(h_vals) else None,
            "pct_mean_rev": round(100 * (h_vals < 0.45).mean(), 1) if len(h_vals) else None,
        }
    result["hurst"] = hurst_summary

    # 4. Returns by UTC hour (skip detail table here, just summarize spread)
    utc_hour = (returns.index + pd.Timedelta(hours=HISTDATA_TO_UTC_OFFSET_HOURS)).hour
    hourly_df = pd.DataFrame({"ret": returns.values, "hour_utc": utc_hour})
    hourly_vol = hourly_df.groupby("hour_utc")["ret"].std() * 100
    result["hourly_vol_min_pct"] = round(hourly_vol.min(), 4)
    result["hourly_vol_max_pct"] = round(hourly_vol.max(), 4)
    result["hourly_vol_ratio_max_min"] = round(hourly_vol.max() / hourly_vol.min(), 2)

    # 5. Volatility clustering
    abs_ret = returns.abs()
    result["vol_clustering_autocorr_abs"] = {lag: round(abs_ret.autocorr(lag=lag), 5) for lag in lags}

    # 6. MM9/21 crossovers per month (frequency proxy only, not a strategy test)
    sig = ma_crossover_signal(df)
    n_crossings = int((sig["long_entry"] | sig["short_entry"]).sum())
    months_span = (df.index[-1] - df.index[0]).days / 30.44
    result["mm9_21_crossings_total"] = n_crossings
    result["mm9_21_crossings_per_month"] = round(n_crossings / months_span, 1)

    return result


def main():
    results = {label: analyze_timeframe(label, cfg) for label, cfg in TF_CONFIGS.items()}

    print("=== 0. Couverture des données ===")
    cov_rows = [{"TF": label, "n_bars": r["n_bars"], "debut": r["date_start"], "fin": r["date_end"]} for label, r in results.items()]
    print(pd.DataFrame(cov_rows).to_markdown(index=False))
    print()

    print("=== 1. Autocorrélation des rendements (lags adaptés par TF, positions comparables) ===")
    print("Légende lags par TF (barres -> durée) :")
    legend_rows = []
    for label, cfg in TF_CONFIGS.items():
        legend_rows.append({"TF": label, **{f"position_{i+1}": f"{lag} barre(s)" for i, lag in enumerate(cfg["lags"])}})
    print(pd.DataFrame(legend_rows).to_markdown(index=False))
    rows = []
    for label, r in results.items():
        row = {"TF": label}
        for i, val in enumerate(r["autocorr_returns"].values()):
            row[f"position_{i+1}"] = val
        rows.append(row)
    print(pd.DataFrame(rows).to_markdown(index=False))
    print()

    print("=== 2. ADF glissant (fenêtres ~5 jours et ~21 jours) ===")
    rows = []
    for label, r in results.items():
        windows = list(r["adf"].keys())
        row = {"TF": label}
        for i, w in enumerate(windows):
            tag = "fenetre_courte (~5j)" if i == 0 else "fenetre_longue (~21j)"
            row[f"{tag}_n"] = r["adf"][w]["n_fenetres"]
            row[f"{tag}_%stationnaire"] = r["adf"][w]["pct_stationnaires"]
        rows.append(row)
    print(pd.DataFrame(rows).to_markdown(index=False))
    print()

    print("=== 3. Hurst glissant (sur rendements, fenêtres ~5 jours et ~21 jours) ===")
    rows = []
    for label, r in results.items():
        windows = list(r["hurst"].keys())
        row = {"TF": label}
        for i, w in enumerate(windows):
            tag = "fenetre_courte (~5j)" if i == 0 else "fenetre_longue (~21j)"
            row[f"{tag}_H_moyen"] = r["hurst"][w]["H_moyen"]
            row[f"{tag}_%trending"] = r["hurst"][w]["pct_trending"]
            row[f"{tag}_%mean_rev"] = r["hurst"][w]["pct_mean_rev"]
        rows.append(row)
    print(pd.DataFrame(rows).to_markdown(index=False))
    print()

    print("=== 4. Amplitude de la saisonnalité horaire (vol par heure UTC) ===")
    rows = [{
        "TF": label, "vol_min_%": r["hourly_vol_min_pct"], "vol_max_%": r["hourly_vol_max_pct"],
        "ratio_max/min": r["hourly_vol_ratio_max_min"],
    } for label, r in results.items()]
    print(pd.DataFrame(rows).to_markdown(index=False))
    print()

    print("=== 5. Clustering de volatilité (autocorr |rendement|, mêmes positions de lag que le point 1) ===")
    rows = []
    for label, r in results.items():
        row = {"TF": label}
        for i, val in enumerate(r["vol_clustering_autocorr_abs"].values()):
            row[f"position_{i+1}"] = val
        rows.append(row)
    print(pd.DataFrame(rows).to_markdown(index=False))
    print()

    print("=== 6. Fréquence des croisements MM9/21 (proxy de volume de trades) ===")
    rows = [{
        "TF": label, "n_croisements_total": r["mm9_21_crossings_total"],
        "croisements_par_mois": r["mm9_21_crossings_per_month"],
    } for label, r in results.items()]
    print(pd.DataFrame(rows).to_markdown(index=False))

    # save
    pd.DataFrame(cov_rows).to_csv("results/tf_comparison_0_coverage.csv", index=False)
    import json
    with open("results/tf_comparison_full.json", "w") as f:
        json.dump(results, f, default=str, indent=2)


if __name__ == "__main__":
    main()
