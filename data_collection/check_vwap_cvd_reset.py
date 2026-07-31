"""
Script de diagnostic ponctuel (à supprimer une fois vérifié) : vérifie
sur les vraies données OKX déjà collectées dans ohlcv_indicators
(pas des données synthétiques) que VWAP et CVD se resettent bien à
chaque 00:00 UTC, comme prévu par collect_ohlcv_indicators.py.

Affiche, pour chaque frontière de journée UTC présente dans les
données, les 3 dernières bougies avant minuit et les 3 premières après
-- confirmation visuelle attendue : cvd repart d'une valeur proche de
+-volume de la première bougie du jour (pas un cumul de la veille), et
vwap de la première bougie == son propre prix typique (pas hérité de
la veille).
"""

import os

import pandas as pd
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TABLE = "ohlcv_indicators"

SYMBOLS = ["BTCUSDT", "SOLUSDT"]


def fetch_all(symbol: str) -> pd.DataFrame:
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{TABLE}"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    params = {
        "select": "timestamp,open,high,low,close,volume,vwap,cvd",
        "symbol": f"eq.{symbol}",
        "order": "timestamp.asc",
        "limit": "5000",
    }
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    df = pd.DataFrame(resp.json())
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def check_symbol(symbol: str):
    print(f"\n{'='*70}\n{symbol}\n{'='*70}")
    df = fetch_all(symbol)
    if df.empty:
        print("Aucune donnée.")
        return

    print(f"{len(df)} bougies récupérées, de {df['timestamp'].min()} à {df['timestamp'].max()}")

    day = df["timestamp"].dt.floor("D")
    boundaries = sorted(day.unique())
    if len(boundaries) < 2:
        print("Une seule journée UTC présente dans les données -- pas de frontière à vérifier pour l'instant.")
        return

    for i in range(1, len(boundaries)):
        prev_day_mask = day == boundaries[i - 1]
        this_day_mask = day == boundaries[i]
        before = df[prev_day_mask].tail(3)
        after = df[this_day_mask].head(3)
        print(f"\n-- Frontière {boundaries[i-1].date()} -> {boundaries[i].date()} --")
        print("Avant minuit (fin de journée précédente) :")
        print(before[["timestamp", "close", "volume", "vwap", "cvd"]].to_string(index=False))
        print("Après minuit (début de nouvelle journée) :")
        print(after[["timestamp", "close", "volume", "vwap", "cvd"]].to_string(index=False))

        first_after = after.iloc[0]
        # Vérification explicite : le VWAP de la 1ere bougie du jour doit
        # égaler son propre prix typique (pas hérité de la veille).
        tp_first = (first_after["high"] + first_after["low"] + first_after["close"]) / 3
        vwap_ok = abs(first_after["vwap"] - tp_first) < 1e-6
        print(f"Vérif VWAP reset : vwap 1ere bougie ({first_after['vwap']:.4f}) == prix typique seul ({tp_first:.4f}) -> {'OK' if vwap_ok else 'ECART'}")


def main():
    for symbol in SYMBOLS:
        check_symbol(symbol)


if __name__ == "__main__":
    main()
