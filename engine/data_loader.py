"""Data loading utilities for the backtest engine."""

import pandas as pd

BINANCE_KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_asset_volume", "n_trades",
    "taker_buy_base_vol", "taker_buy_quote_vol", "ignore",
]


def load_binance_klines_csv(path: str) -> pd.DataFrame:
    """Load a single Binance monthly klines CSV (data.binance.vision format,
    no header) or a pre-concatenated CSV that already has our normalized
    header (open_time, open, high, low, close, volume, ...).
    """
    first_line = open(path, "r").readline()
    has_header = "open_time" in first_line or "open" in first_line.split(",")[1:2]

    if has_header:
        df = pd.read_csv(path)
    else:
        df = pd.read_csv(path, header=None, names=BINANCE_KLINE_COLUMNS)

    # Binance timestamps can be in ms or us depending on export vintage.
    unit = "us" if df["open_time"].iloc[0] > 10**14 else "ms"
    df["open_time"] = pd.to_datetime(df["open_time"], unit=unit)
    df = df.set_index("open_time").sort_index()

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    return df[["open", "high", "low", "close", "volume"]]


def load_mt5_csv(path: str, sep: str = "\t") -> pd.DataFrame:
    """Load an MT5-exported CSV with columns: date, open, high, low, close,
    volume (column names/order as exported by MetaTrader 5's "Export" on a
    chart, tab-separated by default). Date may include a separate time
    column (MT5 default export is `<DATE> <TIME>` or two columns).
    """
    df = pd.read_csv(path, sep=sep)
    df.columns = [c.strip().lower().lstrip("<").rstrip(">") for c in df.columns]

    if "date" in df.columns and "time" in df.columns:
        dt = pd.to_datetime(df["date"] + " " + df["time"])
    elif "date" in df.columns:
        dt = pd.to_datetime(df["date"])
    else:
        raise ValueError(f"Could not find a date column in {path}, got columns: {list(df.columns)}")

    vol_col = "tickvol" if "tickvol" in df.columns else ("volume" if "volume" in df.columns else "vol")

    out = pd.DataFrame({
        "open": df["open"].astype(float),
        "high": df["high"].astype(float),
        "low": df["low"].astype(float),
        "close": df["close"].astype(float),
        "volume": df[vol_col].astype(float) if vol_col in df.columns else 0.0,
    }, index=dt)
    out.index.name = "open_time"
    return out.sort_index()


def load_ohlcv_parquet(path: str) -> pd.DataFrame:
    """Load an OHLCV parquet file with a DatetimeIndex (as produced by
    scripts/process_eurusd_histdata.py or any resample of it)."""
    df = pd.read_parquet(path)
    return df[["open", "high", "low", "close", "volume"]]


def load_ohlcv(path: str) -> pd.DataFrame:
    """Dispatch to the right loader based on file extension: .parquet ->
    load_ohlcv_parquet, .csv -> load_binance_klines_csv (Binance format)."""
    if path.endswith(".parquet"):
        return load_ohlcv_parquet(path)
    if path.endswith(".csv"):
        return load_binance_klines_csv(path)
    raise ValueError(f"Unrecognized file extension for {path}")
