"""
ETL for HistData.com MT-format EURUSD 1-minute zips (data/eurusd_15m/*.zip).

Each zip contains one headerless CSV: date,time,open,high,low,close,volume
(date=YYYY.MM.DD, time=HH:MM, volume always 0 for HistData retail forex
history — there is no centralized FX volume, this is expected, not a
data-quality issue).

Steps:
1. Extract each zip in-memory, validate the column count/dtypes.
2. Concatenate chronologically, drop exact-duplicate timestamps.
3. Resample to 5m and 15m (standard OHLC: open=first, high=max, low=min,
   close=last, volume=sum).
4. Save all three timeframes as parquet.
5. Report row counts, date range per timeframe, and any gap > 2h on the 1m
   series (flagging which look like normal weekend closures vs. not).

Usage:
    python scripts/process_eurusd_histdata.py --data-dir data/eurusd_15m
"""

import argparse
import glob
import zipfile
from pathlib import Path

import pandas as pd

COLUMNS = ["date", "time", "open", "high", "low", "close", "volume"]


def read_zip_csv(zip_path: str) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as zf:
        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if len(csv_names) != 1:
            raise ValueError(f"{zip_path}: expected exactly 1 CSV inside, found {csv_names}")
        with zf.open(csv_names[0]) as f:
            df = pd.read_csv(f, header=None, names=COLUMNS, dtype=str)

    if list(df.columns) != COLUMNS:
        raise ValueError(f"{zip_path}: unexpected columns {list(df.columns)}")

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    df["datetime"] = pd.to_datetime(df["date"] + " " + df["time"], format="%Y.%m.%d %H:%M")
    return df[["datetime", "open", "high", "low", "close", "volume"]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data/eurusd_15m")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    zip_paths = sorted(glob.glob(str(data_dir / "*.zip")))
    if not zip_paths:
        raise SystemExit(f"No .zip files found in {data_dir}")

    frames = []
    for zp in zip_paths:
        df = read_zip_csv(zp)
        print(f"{Path(zp).name}: {len(df)} rows, {df['datetime'].min()} -> {df['datetime'].max()}")
        frames.append(df)

    full = pd.concat(frames, ignore_index=True)
    n_before = len(full)
    full = full.drop_duplicates(subset="datetime", keep="first").sort_values("datetime").reset_index(drop=True)
    n_dupes = n_before - len(full)
    print(f"\nConcatenated: {n_before} rows -> {len(full)} after de-dup ({n_dupes} duplicate timestamps removed)")

    full = full.set_index("datetime")

    # --- gap analysis on the raw 1m series ---
    diffs = full.index.to_series().diff().iloc[1:]
    gaps = diffs[diffs > pd.Timedelta(hours=2)]
    print(f"\nGaps > 2h found: {len(gaps)}")
    weekend_like = 0
    other = 0
    gap_rows = []
    for end_time, delta in gaps.items():
        start_time = end_time - delta
        is_weekend_like = start_time.weekday() == 4 and (40 <= delta.total_seconds() / 3600 <= 52)
        if is_weekend_like:
            weekend_like += 1
        else:
            other += 1
        gap_rows.append({
            "gap_start": start_time, "gap_end": end_time,
            "duration_h": round(delta.total_seconds() / 3600, 2),
            "weekend_like": is_weekend_like,
        })
    gaps_df = pd.DataFrame(gap_rows)
    print(f"  -> {weekend_like} look like normal weekend closures (Fri close -> Sun/Mon reopen, ~40-52h)")
    print(f"  -> {other} do NOT match that pattern (worth checking)")
    if other:
        print("\nNon-weekend gaps:")
        print(gaps_df[~gaps_df["weekend_like"]].to_string(index=False))

    out_dir = data_dir
    gaps_df.to_csv(out_dir / "gap_report.csv", index=False)

    # --- save timeframes ---
    full.to_parquet(out_dir / "EURUSD_1m.parquet")
    print(f"\nSaved 1m: {len(full)} rows -> {out_dir / 'EURUSD_1m.parquet'}")

    ohlc_agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    for label, rule in [("5m", "5min"), ("15m", "15min")]:
        res = full.resample(rule).agg(ohlc_agg).dropna(subset=["open"])
        path = out_dir / f"EURUSD_{label}.parquet"
        res.to_parquet(path)
        print(f"Saved {label}: {len(res)} rows, {res.index[0]} -> {res.index[-1]} -> {path}")


if __name__ == "__main__":
    main()
