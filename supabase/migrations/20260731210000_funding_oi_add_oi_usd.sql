-- Ajoute la colonne oi_usd (open interest en valeur notionnelle USD) à
-- funding_oi_data, en complément de open_interest (nombre brut de
-- contrats -- cf. les champs OKX oi / oiCcy / oiUsd, qui ne sont PAS
-- interchangeables : la taille de contrat diffère selon le symbole,
-- donc open_interest brut n'est pas comparable directement entre BTC
-- et SOL, oi_usd si). Déjà appliquée manuellement en production.

alter table funding_oi_data
    add column if not exists oi_usd numeric;
