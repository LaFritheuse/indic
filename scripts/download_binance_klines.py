"""
Downloads monthly BTCUSDT 15m klines from data.binance.vision and
concatenates them into a single normalized CSV at data/btc_15m/BTCUSDT_15m_full.csv.

Usage:
    python scripts/download_binance_klines.py --symbol BTCUSDT --interval 15m \
        --start 2021-01 --end 2026-07

NOTE: as of 2026-07-29 this script cannot run in the current remote
execution environment: outbound requests to data.binance.vision (and every
other market-data host tested: api.binance.com, fapi.binance.com,
data-api.binance.vision, api.coingecko.com, api.kraken.com,
min-api.cryptocompare.com, query1.finance.yahoo.com) are rejected with a
403 by the environment's egress proxy policy. github.com and pypi.org are
reachable. See PROJECT_MEMORY.md for details. This script is ready to run
as soon as network access to Binance is available (e.g. a session with a
different network policy, or run locally on your machine).
"""

import argparse
import io
import zipfile
from datetime import datetime

import pandas as pd
import urllib.request

from engine.data_loader import BINANCE_KLINE_COLUMNS

BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"


def month_range(start: str, end: str):
    start_dt = datetime.strptime(start, "%Y-%m")
    end_dt = datetime.strptime(end, "%Y-%m")
    months = []
    y, m = start_dt.year, start_dt.month
    while (y, m) <= (end_dt.year, end_dt.month):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def download_month(symbol: str, interval: str, month: str) -> pd.DataFrame:
    url = f"{BASE_URL}/{symbol}/{interval}/{symbol}-{interval}-{month}.zip"
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        csv_name = zf.namelist()[0]
        with zf.open(csv_name) as f:
            df = pd.read_csv(f, header=None, names=BINANCE_KLINE_COLUMNS)
    return df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--start", default="2021-01")
    parser.add_argument("--end", required=True, help="e.g. 2026-07 (current month)")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    out_path = args.out or f"data/btc_15m/{args.symbol}_{args.interval}_full.csv"

    months = month_range(args.start, args.end)
    frames = []
    for month in months:
        print(f"Downloading {args.symbol} {args.interval} {month}...")
        try:
            frames.append(download_month(args.symbol, args.interval, month))
        except Exception as e:
            print(f"  Skipped {month}: {e}")

    full = pd.concat(frames, ignore_index=True)
    full = full.drop_duplicates(subset="open_time").sort_values("open_time")
    full.to_csv(out_path, index=False)
    print(f"Saved {len(full)} rows to {out_path}")


if __name__ == "__main__":
    main()
