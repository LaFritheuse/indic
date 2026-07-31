-- Table des bougies OHLCV OKX (BTC/SOL perpetual, 5m) et des indicateurs
-- calculés VWAP / CVD (voir collect_ohlcv_indicators.py pour la méthode
-- de calcul et ses limites, notamment sur le CVD qui est une
-- approximation basée sur la couleur des bougies, pas un vrai delta
-- acheteur/vendeur). A coller dans l'éditeur SQL de Supabase.

create table if not exists ohlcv_indicators (
    id bigint generated always as identity primary key,
    "timestamp" timestamptz not null,
    symbol text not null,
    "interval" text not null default '5m',
    open numeric,
    high numeric,
    low numeric,
    close numeric,
    volume numeric,
    vwap numeric,
    cvd numeric,
    inserted_at timestamptz not null default now(),
    unique (symbol, "timestamp", "interval")
);

create index if not exists idx_ohlcv_indicators_symbol_timestamp
    on ohlcv_indicators (symbol, "timestamp" desc);
