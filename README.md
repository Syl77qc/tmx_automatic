# TMX v2 — Démarrage rapide

## Prérequis

- Python 3.11+
- Un compte Questrade avec l'API Centre activé

## Installation

```bash
pip install -r requirements.txt
```

## Étape 1 — Obtenir ton token Questrade

1. Connecte-toi à [questrade.com](https://questrade.com)
2. Menu (coin supérieur droit) → **API Centre**
3. **Personal apps** → **New manual authorization** → **Generate new token**
4. Copie le token (⚠️ il n'est affiché qu'une seule fois — durée : 7 jours)

## Étape 2 — Configurer le fichier .env

```bash
cp .env.template .env
# Édite .env et colle ton token :
# QUESTRADE_REFRESH_TOKEN=ton_token_ici
```

## Étape 3 — Explorer l'API

```bash
python questrade_explorer.py
```

Le script va :
- Authentifier via OAuth2
- Résoudre les 12 symboles TSX de l'univers TMX v2
- Tester les quotes L1 en temps réel
- Tester les candles historiques quotidiennes (65 jours)
- Tester les candles intraday 5 minutes
- Vérifier l'accès aux ordres
- Sauvegarder un rapport complet dans `questrade_capabilities.json`

## ⚠️  Sécurité

- Ne jamais committer `.env` dans Git
- `.gitignore` doit contenir `.env` et `questrade_capabilities.json`
- Le script est 100% lecture seule — aucun ordre ne sera placé

## Structure du projet TMX v2

```
tmx_v2/
├── questrade_explorer.py     # Phase 1 — Diagnostic API (ce script)
├── requirements.txt
├── .env.template
├── .env                      # ← À créer localement (non versionné)
└── questrade_capabilities.json  # ← Généré par le script
```
