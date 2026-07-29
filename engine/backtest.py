"""
Modular, event-driven backtest engine.

Design choices (see PROJECT_MEMORY.md for rationale):
- No lookahead: a signal computed from bar i's own close is executed at the
  OPEN of bar i+1, never on the signal bar itself.
- Intrabar SL/TP are checked against high/low, not close. If both SL and TP
  are touched within the same bar, the conservative assumption is applied:
  SL is considered hit first (LOSS).
- SL is either a fixed % of entry price, or a multiple of ATR(atr_period)
  computed as of the signal bar's close.
- TP is always derived from the SL distance via rr_ratio (never set
  independently).
- Fees are charged as fee_pct_per_side on both entry and exit (round trip
  = 2x fee_pct_per_side), expressed as a fraction of entry price.
"""

from dataclasses import dataclass
from typing import Callable, Optional

import pandas as pd

from engine.indicators import atr as atr_indicator


@dataclass
class BacktestConfig:
    sl_mode: str = "atr"          # "fixed_pct" or "atr"
    sl_value: float = 1.5         # pct (e.g. 0.02) if fixed_pct, ATR multiple if atr
    atr_period: int = 14
    rr_ratio: float = 2.0         # TP distance = rr_ratio * SL distance
    fee_pct_per_side: float = 0.0005   # e.g. 0.05% crypto taker per side
    use_tech_exit: bool = True    # close on opposite crossover if SL/TP not hit
    allow_long: bool = True
    allow_short: bool = True
    risk_per_trade_pct: float = 0.01   # used only to build the equity curve
    sl_floor_pips: float = 0.0    # minimum SL distance (atr mode only), in pips; 0 disables the floor
    pip_size: float = 0.0001      # price value of one pip for this instrument


def _compute_sl_tp(entry_price: float, direction: str, config: BacktestConfig, atr_val: Optional[float]):
    if config.sl_mode == "fixed_pct":
        sl_dist = entry_price * config.sl_value
    elif config.sl_mode == "atr":
        sl_dist = atr_val * config.sl_value
        if config.sl_floor_pips > 0:
            sl_dist = max(sl_dist, config.sl_floor_pips * config.pip_size)
    else:
        raise ValueError(f"Unknown sl_mode: {config.sl_mode}")

    tp_dist = sl_dist * config.rr_ratio

    if direction == "long":
        sl_price = entry_price - sl_dist
        tp_price = entry_price + tp_dist
    else:
        sl_price = entry_price + sl_dist
        tp_price = entry_price - tp_dist

    sl_dist_pct = sl_dist / entry_price
    return sl_price, tp_price, sl_dist_pct


def run_backtest(df: pd.DataFrame, signal_fn: Callable[[pd.DataFrame], pd.DataFrame], config: BacktestConfig):
    """Run the backtest and return (trades_df, equity_curve_df).

    df must have a DatetimeIndex and columns: open, high, low, close.
    signal_fn(df) must return long_entry/short_entry/long_exit/short_exit
    boolean columns aligned to df.index (see engine/signals.py).
    """
    signals = signal_fn(df)

    atr_series = None
    if config.sl_mode == "atr":
        atr_series = atr_indicator(df, config.atr_period)

    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    idx = df.index

    long_entry = signals["long_entry"].values
    short_entry = signals["short_entry"].values
    long_exit = signals["long_exit"].values
    short_exit = signals["short_exit"].values
    atr_vals = atr_series.values if atr_series is not None else None

    position = None
    pending_entry_dir = None
    pending_tech_exit = False
    trades = []

    def open_trade(i, direction):
        entry_price = opens[i]
        atr_val = atr_vals[i - 1] if atr_vals is not None else None
        if config.sl_mode == "atr" and (atr_val is None or pd.isna(atr_val)):
            return None
        sl_price, tp_price, sl_dist_pct = _compute_sl_tp(entry_price, direction, config, atr_val)
        return {
            "direction": direction,
            "entry_idx": i,
            "entry_time": idx[i],
            "entry_price": entry_price,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "sl_dist_pct": sl_dist_pct,
        }

    def close_trade(pos, i, exit_price, exit_reason):
        direction = pos["direction"]
        entry_price = pos["entry_price"]
        if direction == "long":
            gross_pnl_pct = (exit_price - entry_price) / entry_price
        else:
            gross_pnl_pct = (entry_price - exit_price) / entry_price
        fees_pct = config.fee_pct_per_side * 2
        net_pnl_pct = gross_pnl_pct - fees_pct
        r_multiple = net_pnl_pct / pos["sl_dist_pct"]
        trades.append({
            "direction": direction,
            "entry_time": pos["entry_time"],
            "entry_price": entry_price,
            "exit_time": idx[i],
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "sl_dist_pct": pos["sl_dist_pct"],
            "gross_pnl_pct": gross_pnl_pct,
            "net_pnl_pct": net_pnl_pct,
            "r_multiple": r_multiple,
        })

    n = len(df)
    for i in range(n):
        # 1. Execute a technical exit queued from the previous bar's signal.
        if position is not None and pending_tech_exit:
            close_trade(position, i, opens[i], "TECH")
            position = None
        pending_tech_exit = False

        # 2. Execute an entry queued from the previous bar's signal.
        if position is None and pending_entry_dir is not None:
            new_pos = open_trade(i, pending_entry_dir)
            if new_pos is not None:
                position = new_pos
        pending_entry_dir = None

        # 3. Check intrabar SL/TP against this bar's high/low.
        if position is not None:
            direction = position["direction"]
            sl, tp = position["sl_price"], position["tp_price"]
            if direction == "long":
                hit_sl = lows[i] <= sl
                hit_tp = highs[i] >= tp
            else:
                hit_sl = highs[i] >= sl
                hit_tp = lows[i] <= tp

            if hit_sl:
                close_trade(position, i, sl, "SL")
                position = None
            elif hit_tp:
                close_trade(position, i, tp, "TP")
                position = None

        # 4. Queue a technical exit for the next bar if applicable.
        if position is not None and config.use_tech_exit:
            direction = position["direction"]
            if direction == "long" and long_exit[i]:
                pending_tech_exit = True
            elif direction == "short" and short_exit[i]:
                pending_tech_exit = True

        # 5. Queue a new entry for the next bar if flat.
        if position is None:
            if long_entry[i] and config.allow_long:
                pending_entry_dir = "long"
            elif short_entry[i] and config.allow_short:
                pending_entry_dir = "short"

    # Close any position still open at the end of the series (incomplete trade).
    if position is not None:
        close_trade(position, n - 1, closes[n - 1], "EOD")

    trades_df = pd.DataFrame(trades)
    return trades_df
