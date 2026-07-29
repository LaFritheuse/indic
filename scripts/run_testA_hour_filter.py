"""
Test A: MA crossover 9/21, SL fixe 2%, EURUSD 15m — référence connue (sans
filtre) vs la même config avec UNIQUEMENT un filtre horaire ajouté
(entrées autorisées seulement si l'exécution tombe entre 12h et 16h UTC).
Aucun autre changement.

Usage:
    python scripts/run_testA_hour_filter.py --data data/eurusd_15m/EURUSD_15m.parquet
"""

import argparse

import pandas as pd

from engine.backtest import BacktestConfig, run_backtest
from engine.data_loader import load_ohlcv
from engine.metrics import compute_metrics
from engine.signals import ma_crossover_signal, with_entry_hour_filter

UTC_OFFSET_HOURS = 5  # HistData fixed-EST timestamps -> UTC


def summarize(name, trades, config):
    m = compute_metrics(trades, risk_per_trade_pct=config.risk_per_trade_pct)
    return {
        "Config": name,
        "n_trades": m["n_trades"],
        "winrate_pct": m["winrate_pct"],
        "esperance_R": m["expectancy_R"],
        "rendement_net_pct": m["net_return_pct"],
        "max_DD_pct": m["max_drawdown_pct"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/eurusd_15m/EURUSD_15m.parquet")
    parser.add_argument("--fee", type=float, default=0.00015)
    args = parser.parse_args()

    df = load_ohlcv(args.data)
    print(f"Loaded {len(df)} bars from {df.index[0]} to {df.index[-1]}")

    config = BacktestConfig(sl_mode="fixed_pct", sl_value=0.02, rr_ratio=2.0, fee_pct_per_side=args.fee)

    hour_filtered_signal = with_entry_hour_filter(ma_crossover_signal, start_hour=12, end_hour=16, utc_offset_hours=UTC_OFFSET_HOURS)

    rows = []
    for name, signal_fn in [
        ("Sans filtre (référence)", ma_crossover_signal),
        ("Filtre horaire 12h-16h UTC", hour_filtered_signal),
    ]:
        trades = run_backtest(df, signal_fn, config)
        rows.append(summarize(name, trades, config))
        safe = name.replace(" ", "_").replace("(", "").replace(")", "").replace("%", "pct")
        trades.to_csv(f"results/testA_trades_{safe}.csv", index=False)

    result = pd.DataFrame(rows)
    print(result.to_markdown(index=False))
    result.to_csv("results/testA_hour_filter_summary.csv", index=False)


if __name__ == "__main__":
    main()
