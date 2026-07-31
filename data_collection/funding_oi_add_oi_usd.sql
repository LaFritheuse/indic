-- Migration : ajoute la colonne oi_usd (open interest en valeur
-- notionnelle USD) à la table funding_oi_data existante, en complément
-- de open_interest (nombre brut de contrats -- cf. les champs OKX
-- oi / oiCcy / oiUsd, qui ne sont PAS interchangeables : la taille de
-- contrat diffère selon le symbole, donc open_interest brut n'est pas
-- comparable directement entre BTC et SOL, oi_usd si).
-- A coller dans l'éditeur SQL de Supabase.

alter table funding_oi_data
    add column if not exists oi_usd numeric;
