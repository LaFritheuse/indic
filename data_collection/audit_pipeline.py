"""
Script de diagnostic ponctuel (à supprimer une fois l'audit terminé) :
audit complet des 5 tables de collecte (continuité temporelle, doublons,
gaps, cohérence des unités, fuseau horaire, fréquence des whale trades).

Ne modifie rien -- lecture seule sur Supabase, rapport texte uniquement.
"""

import json
import os
from collections import Counter
from datetime import timezone

import pandas as pd
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

SYMBOLS = ["BTCUSDT", "SOLUSDT"]
PAGE_SIZE = 1000  # PostgREST plafonne les réponses à 1000 lignes par défaut,
                  # peu importe le "limit" demandé -- il faut paginer via
                  # l'en-tête Range pour récupérer la totalité d'une table.


def fetch_all(table: str, select: str) -> pd.DataFrame:
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{table}"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Range-Unit": "items"}
    params = {"select": select, "order": "timestamp.asc"}

    all_rows = []
    offset = 0
    while True:
        page_headers = dict(headers, Range=f"{offset}-{offset+PAGE_SIZE-1}")
        resp = requests.get(url, headers=page_headers, params=params, timeout=30)
        resp.raise_for_status()
        batch = resp.json()
        all_rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    df = pd.DataFrame(all_rows)
    return df


def check_utc(raw_timestamps: pd.Series) -> dict:
    """Vérifie que 100% des timestamps ont un offset explicite (+00:00 ou Z)."""
    non_utc = raw_timestamps[~raw_timestamps.str.contains(r"\+00:00$|Z$", regex=True, na=False)]
    return {"total": len(raw_timestamps), "non_utc_count": len(non_utc), "sample_non_utc": non_utc.head(3).tolist()}


def interval_stats(ts: pd.Series) -> dict:
    ts = ts.sort_values()
    if len(ts) < 2:
        return {"n": len(ts), "median_min": None, "mean_min": None, "max_min": None, "p90_min": None}
    deltas_min = ts.diff().dropna().dt.total_seconds() / 60
    return {
        "n": len(ts),
        "median_min": round(deltas_min.median(), 1),
        "mean_min": round(deltas_min.mean(), 1),
        "max_min": round(deltas_min.max(), 1),
        "p90_min": round(deltas_min.quantile(0.9), 1),
    }


def section(title):
    print(f"\n{'='*72}\n{title}\n{'='*72}")


def audit_funding_oi():
    section("1. funding_oi_data")
    df = fetch_all("funding_oi_data", "timestamp,symbol,funding_rate,open_interest,oi_usd")
    print(f"Total lignes : {len(df)}")
    if df.empty:
        return
    utc = check_utc(df["timestamp"])
    print(f"Timestamps UTC : {utc['total']-utc['non_utc_count']}/{utc['total']} (non-UTC: {utc['non_utc_count']})")
    df["ts"] = pd.to_datetime(df["timestamp"], utc=True)

    dupes = df[df.duplicated(subset=["symbol", "timestamp"], keep=False)]
    print(f"Doublons exacts (symbol,timestamp) : {len(dupes)}")

    for sym in SYMBOLS:
        sub = df[df["symbol"] == sym].sort_values("ts")
        print(f"\n-- {sym} --")
        stats = interval_stats(sub["ts"])
        print(f"  n={stats['n']}, intervalle median={stats['median_min']}min, moyen={stats['mean_min']}min, "
              f"p90={stats['p90_min']}min, max={stats['max_min']}min")
        big_gaps = sub["ts"].diff().dt.total_seconds().dropna() / 60
        anomalies = big_gaps[big_gaps > 3 * (stats['median_min'] or 1)]
        print(f"  Gaps > 3x median : {len(anomalies)}")

        oi_usd_populated = sub["oi_usd"].notna().sum()
        print(f"  oi_usd renseigné : {oi_usd_populated}/{len(sub)} lignes")
        both = sub.dropna(subset=["oi_usd", "open_interest"])
        both = both[both["open_interest"] != 0]
        if len(both):
            ratio = both["oi_usd"] / both["open_interest"]
            print(f"  ratio oi_usd/open_interest (implique prix*taille contrat) : "
                  f"mean={ratio.mean():.2f}, std={ratio.std():.2f}, min={ratio.min():.2f}, max={ratio.max():.2f}")
        zero_funding = (sub["funding_rate"] == 0).sum()
        print(f"  funding_rate == 0 : {zero_funding}")


def audit_liquidations():
    section("2. liquidations_data")
    df = fetch_all("liquidations_data", "timestamp,symbol,interval,longvolume,shortvolume")
    print(f"Total lignes : {len(df)}")
    if df.empty:
        return
    utc = check_utc(df["timestamp"])
    print(f"Timestamps UTC : {utc['total']-utc['non_utc_count']}/{utc['total']}")
    df["ts"] = pd.to_datetime(df["timestamp"], utc=True)

    dupes = df[df.duplicated(subset=["symbol", "timestamp"], keep=False)]
    print(f"Doublons exacts (symbol,timestamp) : {len(dupes)}")
    print(f"Valeurs distinctes de 'interval' : {df['interval'].unique().tolist()}")

    for sym in SYMBOLS:
        sub = df[df["symbol"] == sym].sort_values("ts")
        print(f"\n-- {sym} --")
        stats = interval_stats(sub["ts"])
        print(f"  n={stats['n']}, span={(sub['ts'].max()-sub['ts'].min()) if len(sub) else None}, "
              f"intervalle entre buckets: median={stats['median_min']}min, max={stats['max_min']}min")
        if len(sub):
            print(f"  longvolume: min={sub['longvolume'].min():.4f}, max={sub['longvolume'].max():.4f}, "
                  f"mean={sub['longvolume'].mean():.4f}")
            print(f"  shortvolume: min={sub['shortvolume'].min():.4f}, max={sub['shortvolume'].max():.4f}, "
                  f"mean={sub['shortvolume'].mean():.4f}")


def audit_long_short_ratio():
    section("3. long_short_ratio_data")
    df = fetch_all("long_short_ratio_data", "timestamp,symbol,interval,ratio,longpct,shortpct")
    print(f"Total lignes : {len(df)}")
    if df.empty:
        return
    utc = check_utc(df["timestamp"])
    print(f"Timestamps UTC : {utc['total']-utc['non_utc_count']}/{utc['total']}")
    df["ts"] = pd.to_datetime(df["timestamp"], utc=True)

    dupes = df[df.duplicated(subset=["symbol", "timestamp"], keep=False)]
    print(f"Doublons exacts (symbol,timestamp) : {len(dupes)}")
    print(f"Valeurs distinctes de 'interval' : {df['interval'].unique().tolist()}")

    df["pct_sum"] = df["longpct"] + df["shortpct"]
    off = df[(df["pct_sum"] - 100).abs() > 0.5]
    print(f"longpct+shortpct != ~100 (tolerance 0.5) : {len(off)}")

    for sym in SYMBOLS:
        sub = df[df["symbol"] == sym].sort_values("ts")
        print(f"\n-- {sym} --")
        stats = interval_stats(sub["ts"])
        print(f"  n={stats['n']}, intervalle median={stats['median_min']}min, max={stats['max_min']}min")
        if len(sub):
            print(f"  ratio: min={sub['ratio'].min():.3f}, max={sub['ratio'].max():.3f}, mean={sub['ratio'].mean():.3f}")


def audit_ohlcv():
    section("4. ohlcv_indicators")
    df = fetch_all("ohlcv_indicators", "timestamp,symbol,interval,open,high,low,close,volume,vwap,cvd")
    print(f"Total lignes : {len(df)}")
    if df.empty:
        return
    utc = check_utc(df["timestamp"])
    print(f"Timestamps UTC : {utc['total']-utc['non_utc_count']}/{utc['total']}")
    df["ts"] = pd.to_datetime(df["timestamp"], utc=True)

    dupes = df[df.duplicated(subset=["symbol", "timestamp", "interval"], keep=False)]
    print(f"Doublons exacts (symbol,timestamp,interval) : {len(dupes)}")

    for sym in SYMBOLS:
        sub = df[df["symbol"] == sym].sort_values("ts")
        print(f"\n-- {sym} --")
        stats = interval_stats(sub["ts"])
        print(f"  n={stats['n']}, intervalle median={stats['median_min']}min (attendu 5.0), max={stats['max_min']}min")
        big_gaps = sub["ts"].diff().dt.total_seconds().dropna() / 60
        anomalies = big_gaps[big_gaps > 10]
        print(f"  Gaps > 10min : {len(anomalies)}")
        bad_ohlc = sub[(sub["high"] < sub["low"]) | (sub["high"] < sub["open"]) | (sub["high"] < sub["close"]) |
                       (sub["low"] > sub["open"]) | (sub["low"] > sub["close"])]
        print(f"  Bougies OHLC incoherentes (high<low etc) : {len(bad_ohlc)}")


def audit_whale_trades():
    section("5. whale_trades_data")
    df = fetch_all("whale_trades_data", "timestamp,symbol,trade_id,side,price,amount,notional_usd")
    print(f"Total lignes : {len(df)}")
    if df.empty:
        print("Aucune donnee -- rien a analyser (verifier qu'un run a bien tourne depuis l'ajout de la table).")
        return
    utc = check_utc(df["timestamp"])
    print(f"Timestamps UTC : {utc['total']-utc['non_utc_count']}/{utc['total']}")
    df["ts"] = pd.to_datetime(df["timestamp"], utc=True)

    dupes = df[df.duplicated(subset=["symbol", "trade_id"], keep=False)]
    print(f"Doublons exacts (symbol,trade_id) : {len(dupes)}")

    notional_check = (df["price"] * df["amount"] - df["notional_usd"]).abs()
    bad_notional = df[notional_check > 0.01]
    print(f"Incoherence notional_usd != price*amount : {len(bad_notional)}")

    for sym in SYMBOLS:
        sub = df[df["symbol"] == sym].sort_values("ts")
        print(f"\n-- {sym} --")
        if sub.empty:
            print("  Aucun whale trade.")
            continue
        span_min = (sub["ts"].max() - sub["ts"].min()).total_seconds() / 60
        n = len(sub)
        rate_per_min = n / span_min if span_min > 0 else None
        print(f"  n={n} trades captes, span reel couvert={span_min:.1f} min")
        if rate_per_min:
            print(f"  Taux observe : {rate_per_min:.3f} trades/min "
                  f"-> ~{rate_per_min*5:.2f} trades / fenetre 5min, ~{rate_per_min*15:.2f} trades / fenetre 15min")
        print(f"  side counts : {Counter(sub['side'])}")
        print(f"  notional_usd: min={sub['notional_usd'].min():,.0f}, max={sub['notional_usd'].max():,.0f}, "
              f"median={sub['notional_usd'].median():,.0f}")


def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("SUPABASE_URL / SUPABASE_KEY manquants.")
        return
    audit_funding_oi()
    audit_liquidations()
    audit_long_short_ratio()
    audit_ohlcv()
    audit_whale_trades()
    section("FIN AUDIT")


if __name__ == "__main__":
    main()
