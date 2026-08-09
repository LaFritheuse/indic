"""
Exporte un instantané des 5 tables de collecte (funding_oi_data,
liquidations_data, long_short_ratio_data, ohlcv_indicators,
whale_trades_data) vers un seul fichier JSON (dashboard/data.json),
pour alimenter un dashboard HTML
statique (voir dashboard/dashboard.html) -- ce dernier ne peut pas
interroger Supabase en direct (page publiée en artifact, CSP stricte
qui bloque les requêtes vers un hôte externe), donc les données sont
figées au moment de l'export. Pour rafraîchir le dashboard : relancer ce
script (via le workflow associé) puis régénérer la page HTML à partir
du nouveau data.json.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / "vps_deploy" / ".env")
except ImportError:
    pass
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

SYMBOLS = ["BTCUSDT", "SOLUSDT"]
OUT_PATH = Path("dashboard/data.json")

# Une table par clé de sortie -- select limité aux colonnes utiles au
# dashboard (pas besoin de id/inserted_at pour visualiser).
TABLES = {
    "funding_oi": ("funding_oi_data", "timestamp,funding_rate,open_interest,oi_usd"),
    "liquidations": ("liquidations_data", "timestamp,longvolume,shortvolume"),
    "long_short_ratio": ("long_short_ratio_data", "timestamp,ratio,longpct,shortpct"),
    "ohlcv": ("ohlcv_indicators", "timestamp,open,high,low,close,volume,vwap,cvd"),
    "whale_trades": ("whale_trades_data", "timestamp,side,price,amount,notional_usd"),
}

REQUEST_TIMEOUT_SECONDS = 30
ROW_LIMIT = 5000


def fetch(table: str, select: str, symbol: str) -> list:
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{table}"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    params = {
        "select": select,
        "symbol": f"eq.{symbol}",
        "order": "timestamp.asc",
        "limit": str(ROW_LIMIT),
    }
    resp = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("SUPABASE_URL / SUPABASE_KEY manquants -- export annulé.", file=sys.stderr)
        return 1

    output = {"generated_at": datetime.now(timezone.utc).isoformat()}

    for symbol in SYMBOLS:
        symbol_data = {}
        for key, (table, select) in TABLES.items():
            rows = fetch(table, select, symbol)
            symbol_data[key] = rows
            print(f"{symbol} / {key}: {len(rows)} lignes")
        output[symbol] = symbol_data

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, indent=None, separators=(",", ":")))
    print(f"Ecrit : {OUT_PATH} ({OUT_PATH.stat().st_size} octets)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
