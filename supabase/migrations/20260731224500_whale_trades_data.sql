-- Table de collecte des gros trades individuels ("whale trades") BTC/SOL
-- sur OKX perpetual (voir data_collection/collect_whale_trades.py pour
-- la méthode de collecte et ses limites).

create table if not exists whale_trades_data (
    id bigint generated always as identity primary key,
    "timestamp" timestamptz not null,
    symbol text not null,
    trade_id text not null,
    side text not null,           -- 'buy' ou 'sell' (côté taker)
    price numeric not null,
    amount numeric not null,      -- taille en unités de l'actif de base (BTC, SOL)
    notional_usd numeric not null,
    inserted_at timestamptz not null default now(),
    unique (symbol, trade_id)
);

create index if not exists idx_whale_trades_symbol_timestamp
    on whale_trades_data (symbol, "timestamp" desc);
