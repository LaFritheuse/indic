"""
Test B: signal de breakout de range (Donchian), entrées limitées à la
fenêtre 12h-16h UTC, SL en ATR(14) x1.5 avec floor 8 pips (déjà validé
en session 2). Teste plusieurs valeurs de lookback N pour la définition
du range.

Usage:
    python scripts/run_testB_breakout_hour.py --data data/eurusd_15m/EURUSD_15m.parquet
"""

import argparse

import pandas as pd

from engine.backtest import BacktestConfig, run_backtest
from engine.data_loader import load_ohlcv
from engine.metrics import compute_metrics
from engine.signals import donchian_breakout_signal, with_entry_hour_filter

UTC_OFFSET_HOURS = 5  # HistData fixed-EST timestamps -> UTC
LOOKBACKS = [20, 50, 100]


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

    config = BacktestConfig(
        sl_mode="atr", sl_value=1.5, atr_period=14, rr_ratio=2.0,
        fee_pct_per_side=args.fee, sl_floor_pips=8.0, pip_size=0.0001,
    )

    rows = []
    for n in LOOKBACKS:
        base_signal = lambda d, n=n: donchian_breakout_signal(d, lookback=n)
        signal_fn = with_entry_hour_filter(base_signal, start_hour=12, end_hour=16, utc_offset_hours=UTC_OFFSET_HOURS)
        trades = run_backtest(df, signal_fn, config)
        rows.append(summarize(f"Breakout N={n}, 12h-16h UTC", trades, config))
        trades.to_csv(f"results/testB_trades_N{n}.csv", index=False)

    result = pd.DataFrame(rows)
    print(result.to_markdown(index=False))
    result.to_csv("results/testB_breakout_hour_summary.csv", index=False)


if __name__ == "__main__":
    main()
