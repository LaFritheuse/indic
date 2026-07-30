-- Table de collecte funding rate / open interest (Binance Futures via ccxt)
-- A coller dans l'éditeur SQL de Supabase.

create table if not exists funding_oi_data (
    id bigint generated always as identity primary key,
    "timestamp" timestamptz not null,
    symbol text not null,
    funding_rate numeric,
    open_interest numeric,
    inserted_at timestamptz not null default now()
);

-- Index pour les requêtes typiques "dernières valeurs pour un symbole donné"
-- (utile plus tard pour calculer un indicateur sur l'historique).
create index if not exists idx_funding_oi_symbol_timestamp
    on funding_oi_data (symbol, "timestamp" desc);
