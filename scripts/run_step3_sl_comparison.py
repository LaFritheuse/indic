"""
Step 3: compare SL fixed 2% vs ATR(14)x1.5 vs ATR(14)x2.0 on BTC 15m,
MM9/21 crossover, crypto fees (0.05%/side).

Usage:
    python scripts/run_step3_sl_comparison.py --data data/btc_15m/BTCUSDT_15m_full.csv
"""

import argparse

import pandas as pd

from engine.backtest import BacktestConfig, run_backtest
from engine.data_loader import load_binance_klines_csv
from engine.metrics import compute_metrics
from engine.signals import ma_crossover_signal


CONFIGS = {
    "SL fixe 2%": BacktestConfig(sl_mode="fixed_pct", sl_value=0.02, rr_ratio=2.0, fee_pct_per_side=0.0005),
    "ATR(14) x1.5": BacktestConfig(sl_mode="atr", sl_value=1.5, atr_period=14, rr_ratio=2.0, fee_pct_per_side=0.0005),
    "ATR(14) x2.0": BacktestConfig(sl_mode="atr", sl_value=2.0, atr_period=14, rr_ratio=2.0, fee_pct_per_side=0.0005),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    args = parser.parse_args()

    df = load_binance_klines_csv(args.data)
    print(f"Loaded {len(df)} bars from {df.index[0]} to {df.index[-1]}")

    rows = []
    for name, config in CONFIGS.items():
        trades = run_backtest(df, ma_crossover_signal, config)
        m = compute_metrics(trades, risk_per_trade_pct=config.risk_per_trade_pct)
        rows.append({"Réglage": name, **{k: v for k, v in m.items() if k != "equity_curve"}})
        trades.to_csv(f"results/step3_trades_{name.replace(' ', '_').replace('%','pct')}.csv", index=False)

    result = pd.DataFrame(rows)
    print(result.to_markdown(index=False))
    result.to_csv("results/step3_summary.csv", index=False)


if __name__ == "__main__":
    main()
