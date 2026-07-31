#!/bin/bash
# Installe et active la collecte funding/OI en continu sur un VPS Debian/Ubuntu
# via systemd (service + timer toutes les 15 min). A lancer depuis la racine
# du repo cloné sur le VPS : bash data_collection/vps_deploy/setup.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR"

echo "1/5 - Environnement virtuel Python..."
python3 -m venv data_collection/vps_deploy/venv
data_collection/vps_deploy/venv/bin/pip install --upgrade pip -q
data_collection/vps_deploy/venv/bin/pip install -r data_collection/requirements.txt -q

if [ ! -f data_collection/vps_deploy/.env ]; then
  cp data_collection/vps_deploy/.env.example data_collection/vps_deploy/.env
  echo
  echo "2/5 - Fichier .env créé depuis le modèle."
  echo "  -> Édite data_collection/vps_deploy/.env avec tes vraies valeurs"
  echo "     SUPABASE_URL / SUPABASE_KEY, puis relance ce script."
  exit 1
fi
echo "2/5 - Fichier .env déjà présent, OK."

echo "3/5 - Installation des unités systemd..."
sudo cp data_collection/vps_deploy/collect-funding-oi.service /etc/systemd/system/
sudo cp data_collection/vps_deploy/collect-funding-oi.timer /etc/systemd/system/
# Remplace le chemin par défaut (/opt/indic) par le vrai chemin du repo sur cette machine.
sudo sed -i "s|/opt/indic|$REPO_DIR|g" /etc/systemd/system/collect-funding-oi.service

echo "4/5 - Activation du timer (toutes les 15 min)..."
sudo systemctl daemon-reload
sudo systemctl enable --now collect-funding-oi.timer

echo "5/5 - Terminé."
echo
echo "Vérifier l'état du timer :   systemctl status collect-funding-oi.timer"
echo "Voir les prochains passages : systemctl list-timers collect-funding-oi.timer"
echo "Suivre les logs en direct :   journalctl -u collect-funding-oi.service -f"
echo "Lancer un run manuel tout de suite : sudo systemctl start collect-funding-oi.service"
