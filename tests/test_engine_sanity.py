"""
Sanity checks on synthetic OHLCV data. These verify the engine's mechanics
(no-lookahead entry timing, SL/TP intrabar priority, fee/R math) — they say
nothing about whether the strategy has an edge on real markets.
"""

import numpy as np
import pandas as pd

from engine.backtest import BacktestConfig, run_backtest
from engine.signals import ma_crossover_signal


def make_series(prices):
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="15min")
    df = pd.DataFrame({
        "open": prices, "high": [p * 1.0005 for p in prices],
        "low": [p * 0.9995 for p in prices], "close": prices,
    }, index=idx)
    return df


def test_no_lookahead_entry_is_next_bar_open():
    # Build a clean crossover: flat-ish then a sharp ramp up.
    prices = [100] * 25 + list(np.linspace(100, 130, 20))
    df = make_series(prices)
    config = BacktestConfig(sl_mode="fixed_pct", sl_value=0.5, rr_ratio=2.0, fee_pct_per_side=0.0)
    signals = ma_crossover_signal(df)
    cross_idx = signals.index[signals["long_entry"]]
    assert len(cross_idx) > 0
    trades = run_backtest(df, ma_crossover_signal, config)
    assert len(trades) > 0
    first_entry_time = trades.iloc[0]["entry_time"]
    # entry must be strictly AFTER the bar where the crossover was confirmed
    first_signal_time = cross_idx[0]
    entry_pos = df.index.get_loc(first_entry_time)
    signal_pos = df.index.get_loc(first_signal_time)
    assert entry_pos == signal_pos + 1, "entry must execute on the bar AFTER the signal bar"


def test_sl_priority_when_both_touched_same_bar():
    idx = pd.date_range("2024-01-01", periods=3, freq="15min")
    df = pd.DataFrame({
        "open": [100, 100, 80],
        "high": [100, 100, 130],   # would hit TP (say tp=120)
        "low": [100, 100, 70],     # would also hit SL (say sl=90)
        "close": [100, 100, 100],
    }, index=idx)

    def fake_signal(_df):
        out = pd.DataFrame(index=_df.index)
        out["long_entry"] = [True, False, False]
        out["short_entry"] = [False, False, False]
        out["long_exit"] = [False, False, False]
        out["short_exit"] = [False, False, False]
        return out

    config = BacktestConfig(sl_mode="fixed_pct", sl_value=0.10, rr_ratio=2.0, fee_pct_per_side=0.0, use_tech_exit=False)
    trades = run_backtest(df, fake_signal, config)
    assert len(trades) == 1
    assert trades.iloc[0]["exit_reason"] == "SL"


def test_fees_reduce_net_pnl():
    prices = [100] * 25 + list(np.linspace(100, 130, 20))
    df = make_series(prices)
    config_no_fee = BacktestConfig(sl_mode="fixed_pct", sl_value=0.5, rr_ratio=2.0, fee_pct_per_side=0.0)
    config_fee = BacktestConfig(sl_mode="fixed_pct", sl_value=0.5, rr_ratio=2.0, fee_pct_per_side=0.001)
    trades_no_fee = run_backtest(df, ma_crossover_signal, config_no_fee)
    trades_fee = run_backtest(df, ma_crossover_signal, config_fee)
    assert trades_fee.iloc[0]["net_pnl_pct"] < trades_no_fee.iloc[0]["net_pnl_pct"]


if __name__ == "__main__":
    test_no_lookahead_entry_is_next_bar_open()
    test_sl_priority_when_both_touched_same_bar()
    test_fees_reduce_net_pnl()
    print("All sanity checks passed.")
