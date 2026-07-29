"""
Resample the EURUSD 1m parquet (already produced by
process_eurusd_histdata.py) into additional timeframes and save as parquet.
Standard OHLC aggregation: open=first, high=max, low=min, close=last,
volume=sum.

Usage:
    python scripts/resample_eurusd_timeframes.py --timeframes 1h 4h
"""

import argparse
from pathlib import Path

import pandas as pd

OHLC_AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="data/eurusd_15m/EURUSD_1m.parquet")
    parser.add_argument("--out-dir", default="data/eurusd_15m")
    parser.add_argument("--timeframes", nargs="+", default=["1h", "4h"])
    args = parser.parse_args()

    full = pd.read_parquet(args.source)
    out_dir = Path(args.out_dir)

    for tf in args.timeframes:
        res = full.resample(tf).agg(OHLC_AGG).dropna(subset=["open"])
        path = out_dir / f"EURUSD_{tf}.parquet"
        res.to_parquet(path)
        print(f"{tf}: {len(res)} rows, {res.index[0]} -> {res.index[-1]} -> {path}")


if __name__ == "__main__":
    main()
