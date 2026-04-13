# Bot de Trading Algorithmique — Alpaca

Bot de trading automatique pour actions et ETFs américains, utilisant l'API Alpaca.
Stratégie EMA Crossover + RSI + Volume. Interface web Streamlit incluse.

---

## Démarrage rapide

```bash
# 1. Copier le fichier de configuration
cp .env.example .env

# 2. Remplir les clés API dans .env
#    ALPACA_API_KEY=...
#    ALPACA_SECRET_KEY=...

# 3. Lancer tout (bot automatique + interface web)
docker-compose up --build -d

# 4. Ouvrir l'interface dans le navigateur
#    http://localhost:8501
```

---

## Configuration (.env)

| Variable | Description | Valeur par défaut |
|----------|-------------|-------------------|
| `ALPACA_API_KEY` | Clé API Alpaca | — (obligatoire) |
| `ALPACA_SECRET_KEY` | Clé secrète Alpaca | — (obligatoire) |
| `PAPER_TRADING` | `TRUE` = simulation, `FALSE` = argent réel | `TRUE` |
| `SYMBOLS` | Liste des symboles à suivre, séparés par des virgules | `AAPL,SPY,QQQ` |
| `TIMEFRAME` | Fréquence d'analyse | `5Min` |
| `STOP_LOSS_PERCENT` | Vente automatique si perte > X% | `5.0` |
| `TAKE_PROFIT_PERCENT` | Vente automatique si gain > X% | `10.0` |
| `MAX_POSITION_SIZE_PERCENT` | % du solde maximum par position | `10.0` |

### Timeframes disponibles

| Valeur | Fréquence |
|--------|-----------|
| `1Min` | Toutes les minutes |
| `5Min` | Toutes les 5 minutes (recommandé) |
| `15Min` | Toutes les 15 minutes |
| `1Hour` | Toutes les heures |
| `1Day` | Une fois par jour |

---

## Ajouter ou retirer des symboles

Modifie la ligne `SYMBOLS` dans ton fichier `.env` puis relance Docker.

```env
# Exemples d'actions
SYMBOLS=AAPL,TSLA,MSFT,NVDA,AMZN,META,GOOGL

# Exemples d'ETFs
SYMBOLS=SPY,QQQ,DIA,IWM,GLD,TLT,ARKK

# Mix actions + ETFs
SYMBOLS=AAPL,SPY,QQQ,TSLA,MSFT,NVDA,AMZN,META,GOOGL,DIA,IWM,GLD,TLT,ARKK
```

**Symboles courants :**

| Symbole | Description |
|---------|-------------|
| `AAPL` | Apple |
| `MSFT` | Microsoft |
| `NVDA` | Nvidia |
| `TSLA` | Tesla |
| `AMZN` | Amazon |
| `META` | Meta (Facebook) |
| `GOOGL` | Google |
| `SPY` | ETF S&P 500 |
| `QQQ` | ETF Nasdaq 100 |
| `DIA` | ETF Dow Jones |
| `IWM` | ETF Russell 2000 |
| `GLD` | ETF Or |
| `TLT` | ETF Obligations long terme |
| `ARKK` | ETF Ark Innovation |

Pour trouver d'autres symboles : **finance.yahoo.com** (tape le nom de l'entreprise).

---

## Stratégie de trading

### Indicateurs calculés

| Indicateur | Paramètre | Rôle |
|-----------|-----------|------|
| EMA 9 | Fenêtre 9 | Signal rapide (croisement) |
| EMA 21 | Fenêtre 21 | Signal lent (croisement) |
| EMA 50 | Fenêtre 50 | Tendance long terme (affichage) |
| RSI | Fenêtre 14 | Filtre momentum |
| MACD | 12/26/9 | Confirmation (affichage) |
| Volume SMA | Fenêtre 20 | Confirmation volume |

### Règles de signal

**ACHAT** — les 3 conditions doivent être vraies simultanément :
1. EMA 9 croise EMA 21 à la **hausse** (croisement haussier)
2. RSI entre **50 et 75** (momentum positif sans surachat)
3. Volume actuel > **1.5x** la moyenne des 20 dernières bougies (confirmation)

**VENTE** — une des deux conditions suffit :
1. EMA 9 croise EMA 21 à la **baisse** (croisement baissier)
2. RSI > **78** (surachat extrême)

**Protection automatique :**
- Stop-loss : vente si perte ≥ `STOP_LOSS_PERCENT` (défaut : 5%)
- Take-profit : vente si gain ≥ `TAKE_PROFIT_PERCENT` (défaut : 10%)

### Gestion de position

- Taille par trade : `MAX_POSITION_SIZE_PERCENT` % du solde disponible
- Exemple : 100 000$ de solde paper + 10% = 10 000$ max par position
- Le bot n'ouvre jamais deux positions simultanées sur le même symbole

---

## Architecture

```
Bot-Bourse/
├── src/
│   ├── main.py        # Boucle de trading automatique
│   ├── app.py         # Interface web Streamlit
│   ├── strategy.py    # Calcul des indicateurs et génération des signaux
│   ├── engine.py      # Connexion Alpaca, ordres, risk management
│   └── config.py      # Chargement et validation de la configuration
├── logs/              # Fichiers de log (montés depuis l'hôte)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env               # Tes clés API (ne jamais commiter)
└── .env.example       # Modèle de configuration
```

### Rôle de chaque fichier source

**`config.py`** — Charge toutes les variables depuis `.env` et les valide au démarrage. Si une clé API manque ou qu'un symbole est invalide, le bot refuse de démarrer.

**`strategy.py`** — Télécharge les données de marché via Alpaca, calcule les indicateurs techniques (EMA, RSI, MACD, Volume), et génère les signaux achat/vente.

**`engine.py`** — Wrapper autour de l'API Alpaca : récupère le solde, les positions, le prix en temps réel, passe les ordres marché, calcule la taille de position et gère le stop-loss/take-profit.

**`main.py`** — Boucle principale automatique : itère sur tous les symboles de `SYMBOLS`, applique la stratégie, exécute les ordres. S'arrête proprement sur SIGTERM (compatible Docker).

**`app.py`** — Interface web Streamlit : sélection du symbole, graphiques interactifs (bougies + EMAs + RSI + MACD), affichage des signaux, bouton d'exécution manuelle.

---

## Docker

### Services

| Service | Container | Rôle | Port |
|---------|-----------|------|------|
| `trading-ui` | `alpaca_ui` | Interface web Streamlit | 8501 |
| `trading-bot` | `alpaca_bot` | Bot automatique | — |

### Commandes

```bash
# Lancer tout (reconstruction de l'image)
docker-compose up --build

# Lancer en arrière-plan
docker-compose up --build -d

# Voir les logs du bot automatique (en direct)
docker logs alpaca_bot -f

# Voir les logs de l'interface web
docker logs alpaca_ui -f

# Arrêter tout
docker-compose down

# Arrêter et supprimer les images
docker-compose down --rmi all
```

### Sécurité Docker

- Utilisateur non-root (`app`) dans le container
- Filesystem en lecture seule (`read_only: true`)
- `no-new-privileges:true`
- Interface web accessible uniquement en localhost (`127.0.0.1:8501`)

---

## Obtenir les clés API Alpaca

1. Créer un compte gratuit sur **alpaca.markets**
2. Dans le dashboard → **Paper Trading** → **"Generate API Keys"**
3. Copier l'**API Key** et le **Secret Key** (le secret ne s'affiche qu'une fois)
4. Coller dans le fichier `.env`

> Le compte Paper Trading donne accès à **100 000$ simulés** pour tester sans risque.
> Les clés Paper et Live sont différentes — vérifier le bon environnement avant de passer en Live.

---

## Heures de marché

Le bot vérifie automatiquement si le marché est ouvert avant chaque cycle.

| Marché | Heures locales (Paris) | Jours |
|--------|----------------------|-------|
| NYSE / Nasdaq | 15h30 — 22h00 | Lundi — Vendredi |

En dehors de ces horaires, le bot attend le prochain cycle sans passer d'ordres.

---

## Logs

Les logs sont écrits dans `logs/bot.log` (accessible depuis l'hôte grâce au volume Docker).

```bash
# Suivre les logs en direct depuis l'hôte
tail -f logs/bot.log
```

Format des logs :
```
2026-01-15 16:32:01 [INFO] Bot démarré | Symboles=['AAPL', 'SPY', 'QQQ'] | Timeframe=5Min | Paper=True
2026-01-15 16:32:05 [INFO] [AAPL] Signaux: achat=False, vente=False
2026-01-15 16:32:07 [INFO] [AAPL] Solde: $98420.50 | Prix actuel: $189.32
2026-01-15 16:37:01 [INFO] [TSLA] Signaux: achat=True, vente=False
2026-01-15 16:37:03 [INFO] [TSLA] Signal ACHAT: qty=52.3, prix=191.20
```

---

## Dépendances Python

| Package | Version | Rôle |
|---------|---------|------|
| `alpaca-py` | ≥ 0.28.0 | SDK officiel Alpaca (données + ordres) |
| `pandas` | ≥ 2.0.0 | Manipulation des données de marché |
| `ta` | ≥ 0.10.0 | Calcul des indicateurs techniques |
| `streamlit` | ≥ 1.28.0 | Interface web |
| `plotly` | ≥ 5.0.0 | Graphiques interactifs |
| `python-dotenv` | ≥ 1.0.0 | Chargement du fichier .env |
| `pytz` | ≥ 2023.0 | Gestion des fuseaux horaires |
