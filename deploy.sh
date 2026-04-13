#!/bin/bash
set -euo pipefail

# =============================================================
# Script de déploiement - Bot de Trading Alpaca
# Usage : bash deploy.sh
# =============================================================

REPO_URL="https://github.com/MacGreg4000/Bot-Bourse.git"
INSTALL_DIR="$HOME/Bot-Bourse"

echo "=== Déploiement Bot-Bourse ==="

# 1. Cloner le repo (ou pull si déjà présent)
if [ -d "$INSTALL_DIR" ]; then
    echo "[1/5] Mise à jour du repo existant..."
    cd "$INSTALL_DIR"
    git pull
else
    echo "[1/5] Clonage du repo..."
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# 2. Configurer le fichier .env
if [ ! -f .env ]; then
    echo "[2/5] Création du fichier .env depuis .env.example..."
    cp .env.example .env
    echo ""
    echo "  ⚠  IMPORTANT : Édite le fichier .env avec tes clés API Alpaca :"
    echo "     nano $INSTALL_DIR/.env"
    echo ""
    echo "  Puis relance ce script."
    exit 0
else
    echo "[2/5] Fichier .env déjà présent."
fi

# 3. Vérifier que les clés API sont configurées
if grep -q "votre_cle_ici\|votre_secret_ici" .env; then
    echo ""
    echo "  ⚠  Les clés API ne sont pas configurées dans .env"
    echo "     Édite le fichier : nano $INSTALL_DIR/.env"
    echo "     Puis relance ce script."
    exit 1
fi

# 4. Créer le dossier logs
echo "[3/5] Création du dossier logs..."
mkdir -p logs

# 5. Build et lancement
echo "[4/5] Build et lancement des containers..."
docker compose up --build -d

# 6. Vérification
echo "[5/5] Vérification..."
echo ""
docker compose ps
echo ""
echo "=== Déploiement terminé ==="
echo ""
echo "Commandes utiles :"
echo "  docker logs alpaca_bot -f     # Logs du bot"
echo "  docker logs alpaca_ui -f      # Logs de l'interface"
echo "  docker compose down           # Arrêter"
echo "  docker compose up -d          # Redémarrer"
echo ""
echo "Accès depuis ton Mac :"
echo "  ssh -L 8501:127.0.0.1:8501 user@ce-serveur"
echo "  Puis ouvrir http://localhost:8501"
