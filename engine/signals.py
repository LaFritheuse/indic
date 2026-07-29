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


def donchian_breakout_signal(df: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    """Range breakout (Donchian-style).

    Range = rolling high/low over the PRIOR `lookback` bars (shifted by 1,
    so the current bar is never part of its own range — no lookahead).
    Long entry when the close breaks above the prior range high.
    Short entry when the close breaks below the prior range low.
    Reverse breakout closes an opposite open position (same convention as
    ma_crossover_signal).
    """
    out = pd.DataFrame(index=df.index)
    range_high = df["high"].rolling(window=lookback, min_periods=lookback).max().shift(1)
    range_low = df["low"].rolling(window=lookback, min_periods=lookback).min().shift(1)

    out["long_entry"] = (df["close"] > range_high).fillna(False)
    out["short_entry"] = (df["close"] < range_low).fillna(False)
    out["long_exit"] = out["short_entry"]
    out["short_exit"] = out["long_entry"]

    return out


def with_entry_hour_filter(signal_fn, start_hour: int, end_hour: int, utc_offset_hours: float = 0.0):
    """Wrap a signal function so entries only fire if the EXECUTION bar
    (the next bar after the signal, where the engine actually opens the
    trade) falls within [start_hour, end_hour) UTC. Exits are untouched —
    only entries are gated.

    utc_offset_hours: added to the DataFrame's raw timestamp index to get
    UTC (e.g. +5 for HistData's fixed-EST timestamps).
    """
    def wrapped(df: pd.DataFrame) -> pd.DataFrame:
        out = signal_fn(df).copy()
        utc_hour = (df.index + pd.Timedelta(hours=utc_offset_hours)).hour
        # Entry at signal-bar i executes at bar i+1 -> gate on hour[i+1].
        execution_hour = pd.Series(utc_hour, index=df.index).shift(-1)
        in_window = (execution_hour >= start_hour) & (execution_hour < end_hour)
        in_window = in_window.fillna(False)
        out["long_entry"] = out["long_entry"] & in_window
        out["short_entry"] = out["short_entry"] & in_window
        return out

    return wrapped
