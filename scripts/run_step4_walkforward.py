"""
Step 4: walk-forward split (70% in-sample / 30% out-of-sample, chronological,
no reoptimization) applied to the winning config from Step 3.

Usage:
    python scripts/run_step4_walkforward.py --data data/btc_15m/BTCUSDT_15m_full.csv \
        --sl-mode atr --sl-value 1.5 --rr 2.0 --fee 0.0005
"""

import argparse

import pandas as pd

from engine.backtest import BacktestConfig, run_backtest
from engine.data_loader import load_binance_klines_csv
from engine.metrics import compute_metrics
from engine.signals import ma_crossover_signal


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--sl-mode", choices=["fixed_pct", "atr"], required=True)
    parser.add_argument("--sl-value", type=float, required=True)
    parser.add_argument("--atr-period", type=int, default=14)
    parser.add_argument("--rr", type=float, default=2.0)
    parser.add_argument("--fee", type=float, default=0.0005)
    parser.add_argument("--split", type=float, default=0.7)
    args = parser.parse_args()

    df = load_binance_klines_csv(args.data)
    config = BacktestConfig(
        sl_mode=args.sl_mode, sl_value=args.sl_value, atr_period=args.atr_period,
        rr_ratio=args.rr, fee_pct_per_side=args.fee,
    )

    # Run once on the FULL series (indicators need warm-up history), then
    # split the resulting trades by entry_time. This avoids recomputing
    # indicators from scratch at the split boundary (which would just
    # shrink the warm-up window, not change the signal logic).
    trades = run_backtest(df, ma_crossover_signal, config)

    split_idx = int(len(df) * args.split)
    split_time = df.index[split_idx]

    is_trades = trades[trades["entry_time"] < split_time]
    oos_trades = trades[trades["entry_time"] >= split_time]

    rows = []
    for label, t in [("In-sample (70%)", is_trades), ("Out-of-sample (30%)", oos_trades)]:
        m = compute_metrics(t, risk_per_trade_pct=config.risk_per_trade_pct)
        rows.append({"Segment": label, **{k: v for k, v in m.items() if k != "equity_curve"}})

    result = pd.DataFrame(rows)
    print(f"Split date: {split_time}")
    print(result.to_markdown(index=False))
    result.to_csv("results/step4_walkforward_summary.csv", index=False)
    trades.to_csv("results/step4_trades_full.csv", index=False)


if __name__ == "__main__":
    main()
