-- Table de collecte des liquidations BTC/SOL (Binance, via Coinalyze)
-- Déjà appliquée manuellement en production -- conservée ici pour
-- l'historique complet (idempotent, aucun risque à la rejouer).

create table if not exists liquidations_data (
    id bigint generated always as identity primary key,
    "timestamp" timestamptz not null,
    symbol text not null,
    "interval" text not null default '1min',
    longvolume numeric,
    shortvolume numeric,
    inserted_at timestamptz not null default now(),
    unique (symbol, "timestamp")
);

-- Index pour les requêtes "historique par symbole", et la clé unique
-- (symbol, timestamp) sert aussi de cible d'upsert idempotent -- le
-- script de collecte refetch une fenêtre large à chaque run (pour
-- rattraper les creux du cron) et peut donc renvoyer des lignes déjà
-- vues sans créer de doublons.
create index if not exists idx_liquidations_symbol_timestamp
    on liquidations_data (symbol, "timestamp" desc);
