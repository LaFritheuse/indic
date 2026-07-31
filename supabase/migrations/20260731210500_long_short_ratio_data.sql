-- Table de collecte du ratio long/short (comptes) BTC/SOL sur Binance,
-- via l'API Coinalyze (endpoint long-short-ratio-history). Déjà
-- appliquée manuellement en production.

create table if not exists long_short_ratio_data (
    id bigint generated always as identity primary key,
    "timestamp" timestamptz not null,
    symbol text not null,
    "interval" text not null default '1min',
    ratio numeric,
    longpct numeric,
    shortpct numeric,
    inserted_at timestamptz not null default now(),
    unique (symbol, "timestamp")
);

create index if not exists idx_long_short_ratio_symbol_timestamp
    on long_short_ratio_data (symbol, "timestamp" desc);
