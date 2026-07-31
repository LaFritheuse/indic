"""
Script de diagnostic temporaire : interroge la table funding_oi_data dans
Supabase et rapporte, par symbole : nombre de lignes, plage de dates,
gaps > 20 min entre timestamps consécutifs, et fraîcheur du dernier point.

A supprimer une fois le diagnostic terminé (ne fait pas partie du
pipeline de collecte permanent).
"""

import os
from datetime import datetime, timezone

import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TABLE = "funding_oi_data"


def fetch_all_rows(symbol: str) -> list:
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{TABLE}"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    params = {
        "select": "timestamp,symbol,funding_rate,open_interest",
        "symbol": f"eq.{symbol}",
        "order": "timestamp.asc",
        "limit": "10000",
    }
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def analyze(symbol: str):
    rows = fetch_all_rows(symbol)
    print(f"\n=== {symbol} ===")
    print(f"n_rows: {len(rows)}")
    if not rows:
        print("Aucune ligne.")
        return

    timestamps = [datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")) for r in rows]
    print(f"premier timestamp: {timestamps[0].isoformat()}")
    print(f"dernier timestamp: {timestamps[-1].isoformat()}")

    now = datetime.now(timezone.utc)
    staleness_min = (now - timestamps[-1]).total_seconds() / 60
    print(f"maintenant (UTC): {now.isoformat()}")
    print(f"anciennete du dernier point: {staleness_min:.1f} min")

    gaps = []
    for i in range(1, len(timestamps)):
        delta_min = (timestamps[i] - timestamps[i - 1]).total_seconds() / 60
        if delta_min > 20:
            gaps.append((timestamps[i - 1].isoformat(), timestamps[i].isoformat(), round(delta_min, 1)))

    print(f"gaps > 20 min: {len(gaps)}")
    for start, end, mins in gaps:
        print(f"  {start} -> {end}  ({mins} min)")

    null_funding = sum(1 for r in rows if r.get("funding_rate") is None)
    null_oi = sum(1 for r in rows if r.get("open_interest") is None)
    print(f"funding_rate NULL: {null_funding} / {len(rows)}")
    print(f"open_interest NULL: {null_oi} / {len(rows)}")


def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("SUPABASE_URL / SUPABASE_KEY manquants.")
        return
    for symbol in ["BTCUSDT", "SOLUSDT"]:
        analyze(symbol)


if __name__ == "__main__":
    main()
