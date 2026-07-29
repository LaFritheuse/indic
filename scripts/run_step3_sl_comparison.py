"""
Step 3: compare SL fixed 2% vs ATR(14)x1.5 vs ATR(14)x2.0, MM9/21 crossover.

Fees must be calibrated per instrument (crypto taker ~0.05%/side vs. forex
spread-equivalent ~0.015%/side) — pass --fee explicitly, do not reuse the
crypto default on forex data.

Usage:
    python scripts/run_step3_sl_comparison.py --data data/btc_15m/BTCUSDT_15m_full.csv --fee 0.0005 --out-prefix btc
    python scripts/run_step3_sl_comparison.py --data data/eurusd_15m/EURUSD_15m.parquet --fee 0.00015 --out-prefix eurusd
"""

import argparse

import pandas as pd

from engine.backtest import BacktestConfig, run_backtest
from engine.data_loader import load_ohlcv
from engine.metrics import compute_metrics
from engine.signals import ma_crossover_signal


def build_configs(fee_pct_per_side: float):
    return {
        "SL fixe 2%": BacktestConfig(sl_mode="fixed_pct", sl_value=0.02, rr_ratio=2.0, fee_pct_per_side=fee_pct_per_side),
        "ATR(14) x1.5": BacktestConfig(sl_mode="atr", sl_value=1.5, atr_period=14, rr_ratio=2.0, fee_pct_per_side=fee_pct_per_side),
        "ATR(14) x2.0": BacktestConfig(sl_mode="atr", sl_value=2.0, atr_period=14, rr_ratio=2.0, fee_pct_per_side=fee_pct_per_side),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--fee", type=float, required=True, help="fee per side, e.g. 0.0005 for crypto, 0.00015 for forex")
    parser.add_argument("--out-prefix", default="step3")
    args = parser.parse_args()

    df = load_ohlcv(args.data)
    print(f"Loaded {len(df)} bars from {df.index[0]} to {df.index[-1]} (fee/side={args.fee})")

    rows = []
    for name, config in build_configs(args.fee).items():
        trades = run_backtest(df, ma_crossover_signal, config)
        m = compute_metrics(trades, risk_per_trade_pct=config.risk_per_trade_pct)
        rows.append({"Réglage": name, **{k: v for k, v in m.items() if k != "equity_curve"}})
        trades.to_csv(f"results/{args.out_prefix}_step3_trades_{name.replace(' ', '_').replace('%','pct')}.csv", index=False)

    result = pd.DataFrame(rows)
    print(result.to_markdown(index=False))
    result.to_csv(f"results/{args.out_prefix}_step3_summary.csv", index=False)


if __name__ == "__main__":
    main()
