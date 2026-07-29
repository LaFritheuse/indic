"""
Modular signal interface.

A signal function takes the OHLCV DataFrame (with a DatetimeIndex, columns
open/high/low/close/volume) and returns a new DataFrame (same index) with
at least these boolean columns:

    long_entry   : True on the bar where a long entry is triggered
    short_entry  : True on the bar where a short entry is triggered
    long_exit    : True on the bar where an existing long should be closed
                   on a technical signal (e.g. reverse crossover)
    short_exit   : True on the bar where an existing short should be closed
                   on a technical signal

All columns are computed strictly from data available at the close of the
row's own bar (no lookahead). The backtest engine executes any signal at
the OPEN of the *next* bar, never on the signal bar itself.
"""

import pandas as pd

from engine.indicators import sma


def ma_crossover_signal(df: pd.DataFrame, fast: int = 9, slow: int = 21) -> pd.DataFrame:
    """Classic moving-average crossover.

    Long entry when the fast MA crosses above the slow MA.
    Short entry when the fast MA crosses below the slow MA.
    The reverse crossover is used both as the opposite entry and, when
    technical exit is enabled in the engine, as the exit signal for an
    open position in the other direction.
    """
    out = pd.DataFrame(index=df.index)
    out["ma_fast"] = sma(df["close"], fast)
    out["ma_slow"] = sma(df["close"], slow)

    prev_fast = out["ma_fast"].shift(1)
    prev_slow = out["ma_slow"].shift(1)

    cross_up = (out["ma_fast"] > out["ma_slow"]) & (prev_fast <= prev_slow)
    cross_down = (out["ma_fast"] < out["ma_slow"]) & (prev_fast >= prev_slow)

    out["long_entry"] = cross_up.fillna(False)
    out["short_entry"] = cross_down.fillna(False)
    # Reverse crossover closes an opposite open position.
    out["long_exit"] = out["short_entry"]
    out["short_exit"] = out["long_entry"]

    return out
