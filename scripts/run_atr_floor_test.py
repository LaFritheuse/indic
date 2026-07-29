"""
Compare ATR(14) x1.5 SL with no floor vs. a minimum floor distance (in pips),
on EURUSD 15m. Follows up on the diagnosis that fixed round-trip fees
dominate the R-multiple when the ATR-based SL distance gets very small
(fee_drag_R = 2*fee_pct_per_side / sl_dist_pct, mean 0.377, corr -0.825 with
ATR at entry on the un-floored run).

Usage:
    python scripts/run_atr_floor_test.py --data data/eurusd_15m/EURUSD_15m.parquet --fee 0.00015
"""

import argparse

import pandas as pd

from engine.backtest import BacktestConfig, run_backtest
from engine.data_loader import load_ohlcv
from engine.metrics import compute_metrics
from engine.signals import ma_crossover_signal


def summarize(name, trades, config):
    m = compute_metrics(trades, risk_per_trade_pct=config.risk_per_trade_pct)
    fee_drag_R = (2 * config.fee_pct_per_side / trades["sl_dist_pct"]).mean() if len(trades) else None
    return {
        "Configuration": name,
        "n_trades": m["n_trades"],
        "winrate_pct": m["winrate_pct"],
        "esperance_R": m["expectancy_R"],
        "rendement_net_pct": m["net_return_pct"],
        "max_DD_pct": m["max_drawdown_pct"],
        "fee_drag_R_moyen": round(fee_drag_R, 4) if fee_drag_R is not None else None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/eurusd_15m/EURUSD_15m.parquet")
    parser.add_argument("--fee", type=float, default=0.00015)
    parser.add_argument("--pip-size", type=float, default=0.0001)
    args = parser.parse_args()

    df = load_ohlcv(args.data)
    print(f"Loaded {len(df)} bars from {df.index[0]} to {df.index[-1]} (fee/side={args.fee})")

    configs = {
        "ATR(14) x1.5 sans floor": BacktestConfig(
            sl_mode="atr", sl_value=1.5, atr_period=14, rr_ratio=2.0,
            fee_pct_per_side=args.fee, sl_floor_pips=0.0, pip_size=args.pip_size,
        ),
        "ATR(14) x1.5 floor 5 pips": BacktestConfig(
            sl_mode="atr", sl_value=1.5, atr_period=14, rr_ratio=2.0,
            fee_pct_per_side=args.fee, sl_floor_pips=5.0, pip_size=args.pip_size,
        ),
        "ATR(14) x1.5 floor 8 pips": BacktestConfig(
            sl_mode="atr", sl_value=1.5, atr_period=14, rr_ratio=2.0,
            fee_pct_per_side=args.fee, sl_floor_pips=8.0, pip_size=args.pip_size,
        ),
    }

    rows = []
    for name, config in configs.items():
        trades = run_backtest(df, ma_crossover_signal, config)
        rows.append(summarize(name, trades, config))
        safe_name = name.replace(" ", "_").replace("(", "").replace(")", "")
        trades.to_csv(f"results/eurusd_atr_floor_trades_{safe_name}.csv", index=False)

    result = pd.DataFrame(rows)
    print(result.to_markdown(index=False))
    result.to_csv("results/eurusd_atr_floor_summary.csv", index=False)


if __name__ == "__main__":
    main()
