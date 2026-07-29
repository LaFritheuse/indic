"""
Pure statistical exploration of EURUSD 15m market structure — NO trading
logic, NO signal, NO strategy. Purpose: characterize what the market
actually shows (mean-reversion vs momentum, stationarity, trending vs
mean-reverting regimes over time, intraday seasonality, volatility
clustering) before designing any new strategy on top of it.

1. Autocorrelation of returns at lags 1/5/20/50 bars.
2. Augmented Dickey-Fuller test on price, rolling windows (500 and 2000
   bars) — % of windows where the unit-root null is rejected at 5%.
3. Hurst exponent (rescaled range, R/S) on rolling windows (500 and 2000
   bars) — proportion of time trending (H>0.55) vs mean-reverting (H<0.45)
   vs random-walk-like (0.45-0.55).
4. Return distribution (mean, vol, skew) grouped by UTC hour.
5. Volatility clustering: autocorrelation of |return| and return^2 at the
   same lags as point 1.

Usage:
    python scripts/explore_market_structure.py --data data/eurusd_15m/EURUSD_15m.parquet
"""

import argparse

import numpy as np
import pandas as pd
from scipy.stats import skew
from statsmodels.tsa.stattools import adfuller

from engine.data_loader import load_ohlcv

LAGS = [1, 5, 20, 50]
WINDOWS = [500, 2000]

# HistData.com timestamps are fixed EST (UTC-5, no DST) — inferred from the
# weekly pattern in this dataset (week reopens Sunday 17:00 raw time, which
# matches the standard forex week open of 22:00 UTC under a fixed -5 offset).
HISTDATA_TO_UTC_OFFSET_HOURS = 5


def hurst_rs(values: np.ndarray, min_lag: int = 10) -> float:
    """Rescaled range (R/S) Hurst exponent for a single window.

    IMPORTANT: `values` must be a (weakly) stationary series — i.e. RETURNS,
    not raw price levels. R/S applied directly to a non-stationary price
    series (itself already an integrated/random-walk-like process) inflates
    H toward 1 regardless of the true return dynamics, because the range of
    an integrated series over a window scales with the window length itself
    rather than with the fractal exponent of the underlying increments.
    Verified empirically: feeding a genuine random walk's price LEVELS into
    this function gives H≈0.996-1.0, while feeding its underlying white-noise
    INCREMENTS gives H≈0.51-0.57 (as theory predicts for H=0.5). Always call
    this on a returns/increments series.
    """
    n = len(values)
    max_lag = n // 2
    if max_lag <= min_lag:
        return np.nan
    lags = np.unique(np.floor(np.logspace(np.log10(min_lag), np.log10(max_lag), num=15)).astype(int))
    lags = lags[(lags >= min_lag) & (lags <= max_lag)]

    demeaned = values - values.mean()
    log_lags, log_rs = [], []
    for lag in lags:
        n_blocks = n // lag
        if n_blocks < 1:
            continue
        rs_block = []
        for b in range(n_blocks):
            chunk = demeaned[b * lag:(b + 1) * lag]
            cum = np.cumsum(chunk - chunk.mean())
            R = cum.max() - cum.min()
            S = chunk.std(ddof=0)
            if S > 0:
                rs_block.append(R / S)
        if rs_block:
            log_lags.append(np.log(lag))
            log_rs.append(np.log(np.mean(rs_block)))

    if len(log_lags) < 4:
        return np.nan
    slope, _ = np.polyfit(log_lags, log_rs, 1)
    return slope


def rolling_adf(close: pd.Series, window: int, stride: int) -> pd.DataFrame:
    rows = []
    values = close.values
    for start in range(0, len(values) - window + 1, stride):
        chunk = values[start:start + window]
        try:
            stat, pval, *_ = adfuller(chunk, autolag="AIC")
        except Exception:
            continue
        rows.append({"adf_stat": stat, "p_value": pval})
    return pd.DataFrame(rows)


def rolling_hurst(returns: pd.Series, window: int, stride: int) -> np.ndarray:
    """Rolling Hurst exponent computed on a RETURNS series (see hurst_rs)."""
    values = returns.values
    hs = []
    for start in range(0, len(values) - window + 1, stride):
        h = hurst_rs(values[start:start + window])
        if not np.isnan(h):
            hs.append(h)
    return np.array(hs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/eurusd_15m/EURUSD_15m.parquet")
    args = parser.parse_args()

    df = load_ohlcv(args.data)
    close = df["close"]
    returns = close.pct_change().dropna()
    print(f"Loaded {len(df)} bars, {len(returns)} returns, {df.index[0]} -> {df.index[-1]}\n")

    # --- 1. Autocorrelation of returns ---
    print("=== 1. Autocorrélation des rendements ===")
    ac_rows = [{"lag": lag, "autocorr_rendements": round(returns.autocorr(lag=lag), 5)} for lag in LAGS]
    ac_df = pd.DataFrame(ac_rows)
    print(ac_df.to_markdown(index=False))
    print()

    # --- 2. Rolling ADF ---
    print("=== 2. Test ADF (Augmented Dickey-Fuller) sur le prix, fenêtres glissantes ===")
    adf_rows = []
    for window in WINDOWS:
        stride = window // 5
        res = rolling_adf(close, window, stride)
        pct_reject = 100 * (res["p_value"] < 0.05).mean() if len(res) else np.nan
        adf_rows.append({
            "fenetre": window,
            "n_fenetres": len(res),
            "adf_stat_moyen": round(res["adf_stat"].mean(), 3) if len(res) else None,
            "pct_fenetres_stationnaires_p<0.05": round(pct_reject, 1) if len(res) else None,
        })
    adf_df = pd.DataFrame(adf_rows)
    print(adf_df.to_markdown(index=False))
    print()

    # --- 3. Rolling Hurst (computed on RETURNS, not raw price levels — see
    # hurst_rs docstring: R/S on non-stationary price levels inflates H
    # toward 1 regardless of the true dynamics) ---
    print("=== 3. Exposant de Hurst (R/S sur les rendements), fenêtres glissantes ===")
    hurst_rows = []
    for window in WINDOWS:
        stride = window // 5
        h_vals = rolling_hurst(returns, window, stride)
        hurst_rows.append({
            "fenetre": window,
            "n_fenetres": len(h_vals),
            "H_moyen": round(h_vals.mean(), 3) if len(h_vals) else None,
            "H_median": round(np.median(h_vals), 3) if len(h_vals) else None,
            "pct_trending_H>0.55": round(100 * (h_vals > 0.55).mean(), 1) if len(h_vals) else None,
            "pct_mean_reverting_H<0.45": round(100 * (h_vals < 0.45).mean(), 1) if len(h_vals) else None,
            "pct_random_walk_0.45-0.55": round(100 * ((h_vals >= 0.45) & (h_vals <= 0.55)).mean(), 1) if len(h_vals) else None,
        })
    hurst_df = pd.DataFrame(hurst_rows)
    print(hurst_df.to_markdown(index=False))
    print()

    # --- 4. Returns by UTC hour ---
    print("=== 4. Distribution des rendements par heure UTC ===")
    utc_hour = (returns.index + pd.Timedelta(hours=HISTDATA_TO_UTC_OFFSET_HOURS)).hour
    hourly_df = pd.DataFrame({"ret": returns.values, "hour_utc": utc_hour})
    hourly_stats = hourly_df.groupby("hour_utc")["ret"].agg(
        n="count", mean_pct=lambda x: 100 * x.mean(), vol_pct=lambda x: 100 * x.std(), skewness=lambda x: skew(x),
    ).round(6).reset_index()
    print(hourly_stats.to_markdown(index=False))
    print()

    # --- 5. Volatility clustering ---
    print("=== 5. Autocorrélation de la volatilité (clustering) ===")
    abs_ret = returns.abs()
    sq_ret = returns ** 2
    vol_rows = []
    for lag in LAGS:
        vol_rows.append({
            "lag": lag,
            "autocorr_|rendement|": round(abs_ret.autocorr(lag=lag), 5),
            "autocorr_rendement2": round(sq_ret.autocorr(lag=lag), 5),
        })
    vol_df = pd.DataFrame(vol_rows)
    print(vol_df.to_markdown(index=False))

    # save everything
    ac_df.to_csv("results/explore_1_autocorr_returns.csv", index=False)
    adf_df.to_csv("results/explore_2_adf_rolling.csv", index=False)
    hurst_df.to_csv("results/explore_3_hurst_rolling.csv", index=False)
    hourly_stats.to_csv("results/explore_4_returns_by_utc_hour.csv", index=False)
    vol_df.to_csv("results/explore_5_volatility_clustering.csv", index=False)


if __name__ == "__main__":
    main()
