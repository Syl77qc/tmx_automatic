"""
TMX v2 — Simulateur Paper Trading
Phase 1, item 3 : Gestion des positions virtuelles avec modèle de coûts réaliste

Références PRD :
  - Section 5    : Maillons 3 (filtres A-G) et 4 (exécution/suivi/sortie)
  - Section 7    : Dimensionnement des positions
  - Section 8    : Modèle de coûts (spread, commission, slippage)
  - Section 9    : Métriques de succès (hit rate, rendement, MAE, drawdown)

Usage :
    python simulateur.py                          # cycle complet (scan → évaluation → suivi)
    python simulateur.py --action evaluer         # évaluer signaux du dernier scan seulement
    python simulateur.py --action surveiller      # surveiller positions ouvertes seulement
    python simulateur.py --action rapport         # afficher métriques section 9
    python simulateur.py --capital 100000         # capital virtuel (défaut : 100 000 $)
"""

import json
import argparse
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from copy import deepcopy

import numpy as np
import yfinance as yf

# ── Constantes PRD ─────────────────────────────────────────────────────────────

EASTERN = ZoneInfo("America/Toronto")

# Section 8 — Modèle de coûts
SPREAD_PCT        = 0.00050   # 0.05% par côté = 0.10% aller-retour (milieu fourchette PRD)
COMMISSION_CAD    = 4.95      # $ par transaction (achat ET vente)
SLIPPAGE_PCT      = 0.0005    # 0.05% additionnel par transaction

# Section 7.4 — Limites de concentration
MAX_POSITIONS_TOTAL   = 3
MAX_POSITIONS_PAR_FNB = 1

# Section 5, Maillon 4 — Sorties
SORTIE_PARTIELLE_PCT  = 0.50   # Vendre 50% quand 50% du rebond récupéré
TRAILING_STOP_PCT     = 0.015  # 1.5% depuis le plus haut atteint

# Section 5, Maillon 3, Filtre A — Cluster
CLUSTER_SEUIL_REDUCTION = 4    # 4-6 FNBs → taille ÷ 2
CLUSTER_SEUIL_BLOCAGE   = 7    # 7+ FNBs → bloquer

# Section 5, Maillon 3, Filtre G — Blocs corrélés
BLOCS_CORRELES = {
    "marche_large": {"XIU.TO", "XFN.TO", "XIN.TO"},
    "metaux":       {"XGD.TO", "XMA.TO"},
    "taux":         {"XRE.TO", "XUT.TO", "ZAG.TO"},
}

# FNBs sensibles aux taux (filtre BdC RPM)
FNBS_SENSIBLES_TAUX = {"XRE.TO", "XUT.TO", "XFN.TO", "ZAG.TO"}

# Profils FNB — stop-loss à ~1.5x la perte additionnelle moyenne (section 5 maillon 4)
PROFILS = {
    "XIU.TO": {"profil": "rapide", "seuil_min": 2.0, "horizon_j": 10,
               "perte_additionnelle_moy": 0.050, "stop_loss_mult": 1.5,
               "bloc": "marche_large"},
    "XFN.TO": {"profil": "moyen",  "seuil_min": 2.0, "horizon_j": 15,
               "perte_additionnelle_moy": 0.059, "stop_loss_mult": 1.5,
               "bloc": "marche_large"},
    "XEG.TO": {"profil": "lent",   "seuil_min": 2.5, "horizon_j": 25,
               "perte_additionnelle_moy": 0.117, "stop_loss_mult": 1.5,
               "bloc": None},
    "XUT.TO": {"profil": "rapide", "seuil_min": 2.0, "horizon_j": 10,
               "perte_additionnelle_moy": 0.053, "stop_loss_mult": 1.5,
               "bloc": "taux"},
    "XIT.TO": {"profil": "rapide", "seuil_min": 2.0, "horizon_j": 10,
               "perte_additionnelle_moy": 0.064, "stop_loss_mult": 1.5,
               "bloc": None},
    "XRE.TO": {"profil": "lent",   "seuil_min": 2.5, "horizon_j": 25,
               "perte_additionnelle_moy": 0.068, "stop_loss_mult": 1.5,
               "bloc": "taux"},
    "XMA.TO": {"profil": "moyen",  "seuil_min": 2.0, "horizon_j": 15,
               "perte_additionnelle_moy": 0.069, "stop_loss_mult": 1.5,
               "bloc": "metaux"},
    "XIN.TO": {"profil": "rapide", "seuil_min": 2.0, "horizon_j": 10,
               "perte_additionnelle_moy": 0.048, "stop_loss_mult": 1.5,
               "bloc": "marche_large"},
    "XHC.TO": {"profil": "moyen",  "seuil_min": 2.0, "horizon_j": 15,
               "perte_additionnelle_moy": 0.055, "stop_loss_mult": 1.5,
               "bloc": None},
    "XST.TO": {"profil": "rapide", "seuil_min": 2.0, "horizon_j": 10,
               "perte_additionnelle_moy": 0.031, "stop_loss_mult": 1.5,
               "bloc": None},
    "XGD.TO": {"profil": "moyen",  "seuil_min": 2.0, "horizon_j": 15,
               "perte_additionnelle_moy": 0.079, "stop_loss_mult": 1.5,
               "bloc": "metaux"},
    "ZAG.TO": {"profil": "lent",   "seuil_min": 2.5, "horizon_j": 25,
               "perte_additionnelle_moy": 0.018, "stop_loss_mult": 1.5,
               "bloc": "taux"},
}

# Fichiers de persistance
FICHIER_POSITIONS  = Path("positions.json")
FICHIER_TRADES_LOG = Path("trades_log.json")
FICHIER_SCAN       = Path("scan_results.json")


# ── Persistance JSON ───────────────────────────────────────────────────────────

def charger_positions() -> dict:
    """Charge l'état courant du portefeuille virtuel."""
    if FICHIER_POSITIONS.exists():
        with open(FICHIER_POSITIONS, encoding="utf-8") as f:
            return json.load(f)
    return {
        "capital_initial": 100_000.0,
        "capital_disponible": 100_000.0,
        "positions_ouvertes": {},
        "cree_le": datetime.now(EASTERN).isoformat(),
        "derniere_maj": datetime.now(EASTERN).isoformat(),
    }


def sauvegarder_positions(portefeuille: dict):
    """Sauvegarde l'état du portefeuille."""
    portefeuille["derniere_maj"] = datetime.now(EASTERN).isoformat()
    with open(FICHIER_POSITIONS, "w", encoding="utf-8") as f:
        json.dump(portefeuille, f, ensure_ascii=False, indent=2, default=str)


def charger_trades_log() -> list:
    """Charge l'historique des trades fermés."""
    if FICHIER_TRADES_LOG.exists():
        with open(FICHIER_TRADES_LOG, encoding="utf-8") as f:
            return json.load(f)
    return []


def sauvegarder_trades_log(trades: list):
    """Sauvegarde l'historique des trades."""
    with open(FICHIER_TRADES_LOG, "w", encoding="utf-8") as f:
        json.dump(trades, f, ensure_ascii=False, indent=2, default=str)


def charger_scan() -> dict | None:
    """Charge les résultats du dernier scan."""
    if not FICHIER_SCAN.exists():
        print(f"❌ Fichier {FICHIER_SCAN} introuvable — lance d'abord scanner.py")
        return None
    with open(FICHIER_SCAN, encoding="utf-8") as f:
        return json.load(f)


# ── Modèle de coûts (section 8) ───────────────────────────────────────────────

def calculer_couts_entree(prix: float, nb_unites: float) -> dict:
    """
    Calcule les coûts d'entrée en position.
    PRD section 8 :
      - Achat au prix ask = prix × (1 + spread/2 + slippage)
      - Commission : 4.95 $
    """
    spread_unitaire   = prix * SPREAD_PCT / 2   # Moitié du spread à l'achat
    slippage_unitaire = prix * SLIPPAGE_PCT
    prix_execution    = prix + spread_unitaire + slippage_unitaire
    commission        = COMMISSION_CAD
    cout_total        = prix_execution * nb_unites + commission

    return {
        "prix_execution": round(prix_execution, 4),
        "spread_cad": round(spread_unitaire * nb_unites, 2),
        "slippage_cad": round(slippage_unitaire * nb_unites, 2),
        "commission_cad": commission,
        "cout_total_cad": round(cout_total, 2),
    }


def calculer_couts_sortie(prix: float, nb_unites: float) -> dict:
    """
    Calcule les coûts de sortie de position.
    Vente au prix bid = prix × (1 - spread/2 - slippage)
    """
    spread_unitaire   = prix * SPREAD_PCT / 2
    slippage_unitaire = prix * SLIPPAGE_PCT
    prix_execution    = prix - spread_unitaire - slippage_unitaire
    commission        = COMMISSION_CAD
    produit_net       = prix_execution * nb_unites - commission

    return {
        "prix_execution": round(prix_execution, 4),
        "spread_cad": round(spread_unitaire * nb_unites, 2),
        "slippage_cad": round(slippage_unitaire * nb_unites, 2),
        "commission_cad": commission,
        "produit_net_cad": round(produit_net, 2),
    }


# ── Prix courant ───────────────────────────────────────────────────────────────

def obtenir_prix_courant(ticker: str) -> float | None:
    """Récupère le prix courant via yfinance."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="2d", interval="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


def obtenir_prix_depuis_scan(ticker: str, scan: dict) -> float | None:
    """Extrait le prix de clôture depuis le dernier scan (fallback)."""
    for fnb in scan.get("tous_fnbs", []):
        if fnb["ticker"] == ticker:
            return fnb.get("prix_cloture")
    return None


# ── Filtres de sécurité (section 5, Maillon 3) ────────────────────────────────

def filtre_A_cluster(scan: dict) -> tuple[bool, str]:
    """
    Filtre A — Compteur de signaux simultanés.
    7+ FNBs en signal → bloquer.
    """
    n = scan["cluster"]["n_signaux"]
    if n >= CLUSTER_SEUIL_BLOCAGE:
        return False, f"Filtre A : {n} signaux simultanés ≥ {CLUSTER_SEUIL_BLOCAGE} → BLOQUÉ"
    return True, f"Filtre A : {n} signaux simultanés → OK"


def filtre_B_regime(scan: dict) -> tuple[bool, str]:
    """
    Filtre B — Régime VIX compatible.
    Risk-off → bloquer sauf signaux ≥ 3.0 é.-t. sur XST/ZAG.
    """
    regime = scan["regime_marche"]["regime"]
    if regime == "risk_off":
        return False, f"Filtre B : Régime risk-off (VIX {scan['regime_marche']['vix']}) → BLOQUÉ"
    return True, f"Filtre B : Régime {regime} → OK"


def filtre_C_profil(signal: dict) -> tuple[bool, str]:
    """
    Filtre C — Seuil z-score suffisant pour le profil du FNB.
    Le seuil effectif (déjà calculé par le scanner) inclut les ajustements BdC et filtre D.
    """
    z20 = signal.get("z20")
    seuil = signal.get("seuil_effectif", signal.get("seuil_min_base", 2.0))
    if z20 is None or z20 > -seuil:
        return False, (f"Filtre C : z20={z20} > -{seuil} "
                       f"(seuil {signal['ticker']}) → BLOQUÉ")
    return True, f"Filtre C : z20={z20:.2f} ≤ -{seuil} → OK"


def filtre_F_tendance(signal: dict) -> tuple[bool, str]:
    """
    Filtre F — Tendance moyen terme (SMA 50 jours).
    Sous SMA50 → seuil +0.5 et taille ÷ 2 (déjà appliqué dans taille).
    Ce filtre ne bloque pas — il réduit (déjà géré dans multiplicateur).
    """
    dessus = signal.get("dessus_sma50")
    if dessus is False:
        return True, "Filtre F : Sous SMA50 → taille réduite (déjà appliqué)"
    return True, "Filtre F : Au-dessus SMA50 → OK"


def filtre_G_correlation(ticker: str, positions_ouvertes: dict) -> tuple[bool, str]:
    """
    Filtre G — Exposition corrélée.
    Maximum 1 position par bloc corrélé (marché large, métaux, taux).
    """
    profil = PROFILS.get(ticker, {})
    bloc = profil.get("bloc")
    if bloc is None:
        return True, f"Filtre G : {ticker} hors bloc → OK"

    tickers_bloc = BLOCS_CORRELES.get(bloc, set())
    for pos_ticker in positions_ouvertes:
        if pos_ticker in tickers_bloc and pos_ticker != ticker:
            return False, (f"Filtre G : {pos_ticker} déjà ouvert dans le bloc "
                           f"'{bloc}' → BLOQUÉ")
    return True, f"Filtre G : Bloc '{bloc}' libre → OK"


def filtre_concentration(ticker: str, positions_ouvertes: dict) -> tuple[bool, str]:
    """
    Vérifie les limites de concentration globales (section 7.4).
    Max 3 positions totales, max 1 par FNB.
    """
    if ticker in positions_ouvertes:
        return False, f"Concentration : Position déjà ouverte sur {ticker} → BLOQUÉ"
    if len(positions_ouvertes) >= MAX_POSITIONS_TOTAL:
        return False, (f"Concentration : {len(positions_ouvertes)} positions ouvertes "
                       f"≥ max {MAX_POSITIONS_TOTAL} → BLOQUÉ")
    return True, "Concentration : OK"


# ── Dimensionnement des positions ──────────────────────────────────────────────

def calculer_taille_position(
    ticker: str,
    signal: dict,
    scan: dict,
    capital_disponible: float,
) -> dict:
    """
    Calcule la taille de position en dollars et en unités.
    PRD sections 7.1, 7.2, 7.3.
    
    Capital de base par position = capital_disponible / MAX_POSITIONS_TOTAL
    """
    profil_cfg = PROFILS[ticker]
    profil = profil_cfg["profil"]
    z20 = abs(signal["z20"])
    z60 = signal.get("z60")
    regime = scan["regime_marche"]["regime"]
    filtre_D_ajustement = scan["filtre_D"]["ajustement"]
    dessus_sma50 = signal.get("dessus_sma50")
    cluster_action = scan["cluster"]["action"]

    # Base par profil (section 7.2)
    base_profil = {"rapide": 1.00, "moyen": 0.75, "lent": 0.50}[profil]

    # Multiplicateur signal (section 7.1)
    if z20 >= 3.0:
        mult_signal = 2.0
        bucket_z20 = "z20:≥3.0"
    elif z20 >= 2.5:
        mult_signal = 1.5
        bucket_z20 = "z20:2.5-2.99"
    else:
        mult_signal = 1.0
        bucket_z20 = "z20:2.0-2.49"

    multiplicateur = base_profil * mult_signal

    # Ajustements cumulatifs (section 7.3)
    ajustements = []

    if regime == "neutre":
        multiplicateur /= 2
        ajustements.append("régime_neutre÷2")

    if dessus_sma50 is False:
        multiplicateur /= 2
        ajustements.append("sous_SMA50÷2")

    z60_tag = "z60:N/A"
    if z60 is not None:
        if z60 > -1.5:
            multiplicateur /= 1.5
            ajustements.append("z60_faible÷1.5")
            z60_tag = "z60:faible"
        else:
            z60_tag = "z60:confirmé"

    if filtre_D_ajustement == "seuil+0.5_taille÷1.5":
        multiplicateur /= 1.5
        ajustements.append("filtreD_XIU_stable÷1.5")

    if cluster_action == "reduire_taille_50pct_et_seuil_2.5":
        multiplicateur /= 2
        ajustements.append("cluster_4_6÷2")

    # Capital alloué
    capital_base = capital_disponible / MAX_POSITIONS_TOTAL
    capital_position = capital_base * multiplicateur
    capital_position = min(capital_position, capital_disponible * 0.40)  # Max 40% du dispo

    prix = signal["prix_cloture"]
    nb_unites = int(capital_position / prix)

    if nb_unites < 1:
        nb_unites = 1

    return {
        "capital_position_cad": round(capital_position, 2),
        "nb_unites": nb_unites,
        "multiplicateur_final": round(multiplicateur, 4),
        "base_profil": base_profil,
        "mult_signal": mult_signal,
        "ajustements": ajustements,
        "bucket_z20": bucket_z20,
        "tag_z60": z60_tag,
    }


# ── Ouverture de position ──────────────────────────────────────────────────────

def ouvrir_position(
    ticker: str,
    signal: dict,
    scan: dict,
    portefeuille: dict,
    raisons_filtres: list[str],
) -> dict | None:
    """
    Ouvre une position virtuelle et met à jour le portefeuille.
    Retourne le dictionnaire de la nouvelle position, ou None si impossible.
    """
    capital_dispo = portefeuille["capital_disponible"]
    taille = calculer_taille_position(ticker, signal, scan, capital_dispo)

    prix_signal = signal["prix_cloture"]
    nb_unites = taille["nb_unites"]

    if nb_unites < 1:
        return None

    # Coûts d'entrée (section 8)
    couts = calculer_couts_entree(prix_signal, nb_unites)
    cout_total = couts["cout_total_cad"]

    if cout_total > capital_dispo:
        print(f"   ⚠️  {ticker} : Capital insuffisant ({cout_total:.2f}$ > {capital_dispo:.2f}$)")
        return None

    profil_cfg = PROFILS[ticker]

    # Prix pré-baisse (objectif de retour) = prix_signal / (1 + rendement_jour)
    # Le rendement du jour est négatif (c'est une baisse)
    rendement = signal.get("rendement_jour_pct", 0) / 100
    if rendement < 0:
        prix_pre_baisse = prix_signal / (1 + rendement)
    else:
        prix_pre_baisse = prix_signal * 1.02  # Fallback conservateur

    # Stop-loss : 1.5x la perte additionnelle moyenne (section 5, Maillon 4)
    stop_loss_pct = profil_cfg["perte_additionnelle_moy"] * profil_cfg["stop_loss_mult"]
    prix_stop_loss = prix_signal * (1 - stop_loss_pct)

    # Date d'horizon max
    aujourd_hui = date.today()
    date_horizon = (aujourd_hui + timedelta(days=profil_cfg["horizon_j"])).isoformat()

    # Tags de basketing complets
    tags = list(signal.get("tags", []))
    tags.append(f"profil:{profil_cfg['profil']}")
    if taille["tag_z60"] not in tags:
        tags.append(taille["tag_z60"])
    tags.append(taille["bucket_z20"])

    position = {
        "id": f"{ticker}_{datetime.now(EASTERN).strftime('%Y%m%d_%H%M%S')}",
        "ticker": ticker,
        "statut": "ouvert",
        "date_entree": datetime.now(EASTERN).isoformat(),
        "date_horizon_max": date_horizon,
        "jours_restants": profil_cfg["horizon_j"],

        # Prix
        "prix_signal": round(prix_signal, 4),
        "prix_entree": couts["prix_execution"],
        "prix_pre_baisse": round(prix_pre_baisse, 4),
        "prix_stop_loss": round(prix_stop_loss, 4),
        "prix_plus_haut_atteint": couts["prix_execution"],  # Pour trailing stop
        "prix_sortie_partielle": None,  # Rempli lors de la sortie partielle

        # Taille
        "nb_unites_total": nb_unites,
        "nb_unites_restant": nb_unites,
        "sortie_partielle_faite": False,

        # Coûts d'entrée
        "cout_entree": couts,

        # Capital
        "capital_investi": cout_total,
        "multiplicateur": taille["multiplicateur_final"],

        # Contexte du signal
        "z20_entree": signal.get("z20"),
        "z60_entree": signal.get("z60"),
        "vix_entree": scan["regime_marche"].get("vix"),
        "regime_entree": scan["regime_marche"]["regime"],
        "sma50_entree": signal.get("sma50"),
        "dessus_sma50_entree": signal.get("dessus_sma50"),

        # Filtres appliqués
        "raisons_filtres_passes": raisons_filtres,
        "ajustements_taille": taille["ajustements"],

        # Tags basketing
        "tags": tags,

        # MAE (pire excursion adverse) — mis à jour à chaque cycle
        "mae_pct": 0.0,
        "mae_prix": couts["prix_execution"],
    }

    # Mettre à jour le portefeuille
    portefeuille["positions_ouvertes"][ticker] = position
    portefeuille["capital_disponible"] = round(capital_dispo - cout_total, 2)

    return position


# ── Surveillance et clôture des positions ─────────────────────────────────────

def evaluer_sortie(position: dict, prix_actuel: float) -> dict | None:
    """
    Évalue si une position doit être fermée (totalement ou partiellement).
    PRD section 5, Maillon 4 — Quatre scénarios de sortie.

    Retourne un dict décrivant la sortie, ou None si on conserve.
    """
    prix_entree       = position["prix_entree"]
    prix_pre_baisse   = position["prix_pre_baisse"]
    prix_stop_loss    = position["prix_stop_loss"]
    prix_plus_haut    = position["prix_plus_haut_atteint"]
    date_horizon      = date.fromisoformat(position["date_horizon_max"])
    sortie_partielle_faite = position["sortie_partielle_faite"]
    nb_restant        = position["nb_unites_restant"]

    # Mise à jour du plus haut (pour trailing stop)
    nouveau_plus_haut = max(prix_plus_haut, prix_actuel)

    # Rebond récupéré (%)
    baisse_totale = prix_pre_baisse - prix_entree
    rebond_actuel = prix_actuel - prix_entree
    pct_rebond    = rebond_actuel / baisse_totale if baisse_totale > 0 else 0

    # ── Scénario 1 : Objectif atteint (retour au prix pré-baisse) ──
    if prix_actuel >= prix_pre_baisse:
        return {
            "type": "objectif",
            "raison": f"Prix {prix_actuel:.4f} ≥ objectif {prix_pre_baisse:.4f}",
            "nb_unites": nb_restant,
            "partielle": False,
            "nouveau_plus_haut": nouveau_plus_haut,
        }

    # ── Scénario 2A : Sortie partielle à 50% du rebond ──
    if not sortie_partielle_faite and pct_rebond >= SORTIE_PARTIELLE_PCT:
        nb_partielle = max(1, nb_restant // 2)
        return {
            "type": "partielle",
            "raison": f"50% du rebond récupéré ({pct_rebond:.1%})",
            "nb_unites": nb_partielle,
            "partielle": True,
            "nouveau_plus_haut": nouveau_plus_haut,
        }

    # ── Scénario 2B : Trailing stop (après sortie partielle) ──
    if sortie_partielle_faite:
        prix_trailing_stop = nouveau_plus_haut * (1 - TRAILING_STOP_PCT)
        if prix_actuel <= prix_trailing_stop:
            return {
                "type": "trailing_stop",
                "raison": (f"Prix {prix_actuel:.4f} ≤ trailing stop "
                           f"{prix_trailing_stop:.4f} (depuis plus haut {nouveau_plus_haut:.4f})"),
                "nb_unites": nb_restant,
                "partielle": False,
                "nouveau_plus_haut": nouveau_plus_haut,
            }

    # ── Scénario 3 : Horizon dépassé ──
    if date.today() >= date_horizon:
        return {
            "type": "horizon",
            "raison": f"Horizon max atteint ({date_horizon})",
            "nb_unites": nb_restant,
            "partielle": False,
            "nouveau_plus_haut": nouveau_plus_haut,
        }

    # ── Scénario 4 : Stop-loss ──
    if prix_actuel <= prix_stop_loss:
        return {
            "type": "stop_loss",
            "raison": f"Prix {prix_actuel:.4f} ≤ stop-loss {prix_stop_loss:.4f}",
            "nb_unites": nb_restant,
            "partielle": False,
            "nouveau_plus_haut": nouveau_plus_haut,
        }

    # Conserver la position
    return None


def fermer_position(
    position: dict,
    prix_actuel: float,
    sortie: dict,
    portefeuille: dict,
    trades_log: list,
) -> dict:
    """
    Ferme (totalement ou partiellement) une position et enregistre le trade.
    """
    ticker     = position["ticker"]
    nb_unites  = sortie["nb_unites"]
    prix_entree = position["prix_entree"]

    # Coûts de sortie
    couts_sortie = calculer_couts_sortie(prix_actuel, nb_unites)
    produit_net  = couts_sortie["produit_net_cad"]

    # P&L
    cout_entree_unitaire = position["prix_entree"]
    pnl_brut = (prix_actuel - cout_entree_unitaire) * nb_unites
    couts_totaux = (
        position["cout_entree"]["spread_cad"] +
        position["cout_entree"]["slippage_cad"] +
        couts_sortie["spread_cad"] +
        couts_sortie["slippage_cad"] +
        (position["cout_entree"]["commission_cad"] if not position["sortie_partielle_faite"]
         else 0) +
        couts_sortie["commission_cad"]
    )
    pnl_net = pnl_brut - couts_totaux
    pnl_net_pct = pnl_net / position["capital_investi"] * 100

    # MAE mise à jour
    mae_pct = min(
        position.get("mae_pct", 0),
        (prix_actuel - prix_entree) / prix_entree * 100,
    )

    # Jours en position
    date_entree = datetime.fromisoformat(position["date_entree"])
    jours_detenus = (datetime.now(EASTERN) - date_entree).days

    # Enregistrement du trade
    trade = {
        "id": position["id"],
        "ticker": ticker,
        "type_sortie": sortie["type"],
        "raison_sortie": sortie["raison"],
        "partielle": sortie["partielle"],

        # Dates
        "date_entree": position["date_entree"],
        "date_sortie": datetime.now(EASTERN).isoformat(),
        "jours_detenus": jours_detenus,

        # Prix
        "prix_entree": position["prix_entree"],
        "prix_sortie": prix_actuel,
        "prix_pre_baisse": position["prix_pre_baisse"],
        "prix_stop_loss": position["prix_stop_loss"],

        # Quantités
        "nb_unites": nb_unites,

        # P&L
        "pnl_brut_cad": round(pnl_brut, 2),
        "couts_totaux_cad": round(couts_totaux, 2),
        "pnl_net_cad": round(pnl_net, 2),
        "pnl_net_pct": round(pnl_net_pct, 4),
        "gagnant": pnl_net > 0,

        # Métriques section 9
        "mae_pct": round(mae_pct, 4),

        # Contexte signal
        "z20_entree": position.get("z20_entree"),
        "z60_entree": position.get("z60_entree"),
        "vix_entree": position.get("vix_entree"),
        "regime_entree": position.get("regime_entree"),
        "dessus_sma50_entree": position.get("dessus_sma50_entree"),

        # Tags basketing complets (section 9 + commentaires reçus)
        "tags": position.get("tags", []) + [f"exit:{sortie['type']}"],
    }

    trades_log.append(trade)

    # Mise à jour du portefeuille
    portefeuille["capital_disponible"] = round(
        portefeuille["capital_disponible"] + produit_net, 2
    )

    if sortie["partielle"]:
        # Sortie partielle : mettre à jour la position
        position["nb_unites_restant"] -= nb_unites
        position["sortie_partielle_faite"] = True
        position["prix_sortie_partielle"] = prix_actuel
        position["prix_plus_haut_atteint"] = sortie["nouveau_plus_haut"]
        position["mae_pct"] = mae_pct
        print(f"   📤 {ticker} Sortie partielle : {nb_unites} unités @ {prix_actuel:.4f} "
              f"| P&L net : {pnl_net:+.2f}$")
    else:
        # Sortie totale : supprimer la position
        del portefeuille["positions_ouvertes"][ticker]
        print(f"   📤 {ticker} Fermé ({sortie['type']}) : {nb_unites} unités @ {prix_actuel:.4f} "
              f"| P&L net : {pnl_net:+.2f}$ ({pnl_net_pct:+.2f}%)")

    return trade


# ── Métriques section 9 ────────────────────────────────────────────────────────

def calculer_metriques(trades_log: list, portefeuille: dict) -> dict:
    """
    Calcule les métriques de succès et critères d'arrêt.
    PRD section 9.1 et 9.2.
    """
    trades_fermes = [t for t in trades_log if not t.get("partielle", False)]

    if not trades_fermes:
        return {"message": "Aucun trade complet encore — métriques indisponibles"}

    n = len(trades_fermes)
    gagnants = [t for t in trades_fermes if t["gagnant"]]
    perdants  = [t for t in trades_fermes if not t["gagnant"]]

    hit_rate = len(gagnants) / n * 100
    rendement_moyen = sum(t["pnl_net_pct"] for t in trades_fermes) / n
    duree_moyenne = sum(t["jours_detenus"] for t in trades_fermes) / n

    # Gain/perte moyen
    gain_moyen  = sum(t["pnl_net_pct"] for t in gagnants) / len(gagnants) if gagnants else 0
    perte_moy   = sum(t["pnl_net_pct"] for t in perdants) / len(perdants) if perdants else 0
    ratio_gp    = abs(gain_moyen / perte_moy) if perte_moy != 0 else float("inf")

    # MAE moyen
    mae_moyen = sum(t.get("mae_pct", 0) for t in trades_fermes) / n

    # Drawdown portefeuille (simplifié : peak to trough sur capital)
    capital_initial = portefeuille["capital_initial"]
    capital_actuel  = portefeuille["capital_disponible"]
    # Ajouter valeur mark-to-market des positions ouvertes
    capital_total   = capital_actuel  # Simplifié — à enrichir avec prix actuel des positions
    drawdown_pct    = (capital_initial - capital_total) / capital_initial * 100

    # Critères d'arrêt (section 9.2)
    kill_switch = []
    if n >= 10 and hit_rate < 50:
        kill_switch.append(f"⚠️  Hit rate {hit_rate:.1f}% < 50% — réévaluation requise")
    if n >= 10 and rendement_moyen < 0:
        kill_switch.append(f"⚠️  Rendement moyen {rendement_moyen:.2f}% < 0 — réévaluation requise")
    if drawdown_pct > 20:
        kill_switch.append(f"🔴 Drawdown {drawdown_pct:.1f}% > 20% — KILL SWITCH")

    # Critères de passage en argent réel (section 9.3)
    go_live = []
    if n >= 30:
        go_live.append(f"✅ ≥ 30 trades ({n})")
    if hit_rate >= 60:
        go_live.append(f"✅ Hit rate {hit_rate:.1f}% ≥ 60%")
    if drawdown_pct < 15:
        go_live.append(f"✅ Drawdown {drawdown_pct:.1f}% < 15%")

    return {
        "n_trades": n,
        "hit_rate_pct": round(hit_rate, 2),
        "rendement_moyen_pct": round(rendement_moyen, 4),
        "gain_moyen_pct": round(gain_moyen, 4),
        "perte_moyenne_pct": round(perte_moy, 4),
        "ratio_gain_perte": round(ratio_gp, 2),
        "duree_moyenne_j": round(duree_moyenne, 1),
        "mae_moyen_pct": round(mae_moyen, 4),
        "capital_initial": capital_initial,
        "capital_actuel": capital_total,
        "drawdown_pct": round(drawdown_pct, 2),
        "kill_switch_alertes": kill_switch,
        "criteres_go_live": go_live,
        "cibles_prd": {
            "hit_rate": "≥ 60%",
            "rendement_moyen": "≥ +1.5%",
            "drawdown_max": "< 15%",
            "ratio_gain_perte": "≥ 1.5:1",
            "n_trades_min": "≥ 30",
        },
    }


# ── Actions principales ────────────────────────────────────────────────────────

def action_evaluer(portefeuille: dict, trades_log: list, capital: float):
    """
    Évalue les signaux du dernier scan et ouvre les positions qui passent
    tous les filtres.
    """
    print("\n🔍 Évaluation des signaux du dernier scan...")

    scan = charger_scan()
    if scan is None:
        return

    if not scan.get("signaux"):
        print("   Aucun signal dans le dernier scan — rien à évaluer.")
        return

    # Initialiser le capital si premier lancement
    if portefeuille["capital_initial"] != capital:
        portefeuille["capital_initial"] = capital
        portefeuille["capital_disponible"] = capital

    positions = portefeuille["positions_ouvertes"]

    # Filtres globaux (s'appliquent à tous les signaux)
    ok_A, msg_A = filtre_A_cluster(scan)
    ok_B, msg_B = filtre_B_regime(scan)

    print(f"\n   {msg_A}")
    print(f"   {msg_B}")

    if not ok_A or not ok_B:
        print("\n   ❌ Filtres globaux bloquants — aucune position ouverte.")
        return

    nouvelles = 0
    for signal in scan["signaux"]:
        ticker = signal["ticker"]
        print(f"\n   → {ticker} (z20={signal['z20']:.2f}) :")

        # Filtre C — profil
        ok_C, msg_C = filtre_C_profil(signal)
        print(f"      {msg_C}")
        if not ok_C:
            continue

        # Filtre concentration
        ok_conc, msg_conc = filtre_concentration(ticker, positions)
        print(f"      {msg_conc}")
        if not ok_conc:
            continue

        # Filtre F — tendance (informatif seulement)
        ok_F, msg_F = filtre_F_tendance(signal)
        print(f"      {msg_F}")

        # Filtre G — corrélation
        ok_G, msg_G = filtre_G_correlation(ticker, positions)
        print(f"      {msg_G}")
        if not ok_G:
            continue

        # Tous les filtres passés — ouvrir la position
        raisons = [msg_A, msg_B, msg_C, msg_F, msg_G]
        position = ouvrir_position(ticker, signal, scan, portefeuille, raisons)

        if position:
            print(f"\n   📥 POSITION OUVERTE : {ticker}")
            print(f"      Prix entrée  : {position['prix_entree']:.4f} $")
            print(f"      Nb unités    : {position['nb_unites_total']}")
            print(f"      Capital      : {position['capital_investi']:.2f} $")
            print(f"      Objectif     : {position['prix_pre_baisse']:.4f} $")
            print(f"      Stop-loss    : {position['prix_stop_loss']:.4f} $")
            print(f"      Horizon max  : {position['date_horizon_max']}")
            print(f"      Multiplicateur: {position['multiplicateur']:.4f}x")
            if position["ajustements_taille"]:
                print(f"      Ajustements  : {', '.join(position['ajustements_taille'])}")
            nouvelles += 1
        else:
            print(f"      ⚠️  Impossible d'ouvrir la position (capital insuffisant?)")

    print(f"\n   → {nouvelles} nouvelle(s) position(s) ouverte(s)")
    print(f"   → Capital disponible : {portefeuille['capital_disponible']:.2f} $")


def action_surveiller(portefeuille: dict, trades_log: list):
    """
    Surveille les positions ouvertes et applique les règles de sortie.
    """
    positions = portefeuille["positions_ouvertes"]

    if not positions:
        print("\n📊 Aucune position ouverte à surveiller.")
        return

    print(f"\n📊 Surveillance de {len(positions)} position(s) ouverte(s)...")

    scan = charger_scan()

    for ticker, position in list(positions.items()):
        # Récupérer le prix actuel
        prix_actuel = obtenir_prix_courant(ticker)
        if prix_actuel is None and scan:
            prix_actuel = obtenir_prix_depuis_scan(ticker, scan)
        if prix_actuel is None:
            print(f"   ⚠️  {ticker} : Prix indisponible — position conservée")
            continue

        # Mise à jour MAE
        prix_entree = position["prix_entree"]
        excursion = (prix_actuel - prix_entree) / prix_entree * 100
        position["mae_pct"] = min(position.get("mae_pct", 0), excursion)
        position["prix_plus_haut_atteint"] = max(
            position.get("prix_plus_haut_atteint", prix_entree), prix_actuel
        )

        # P&L courant
        pnl_courant = (prix_actuel - prix_entree) * position["nb_unites_restant"]
        pnl_pct = (prix_actuel - prix_entree) / prix_entree * 100

        print(f"\n   {ticker} | Prix actuel: {prix_actuel:.4f} $ | "
              f"P&L: {pnl_courant:+.2f}$ ({pnl_pct:+.2f}%)")

        # Évaluer la sortie
        sortie = evaluer_sortie(position, prix_actuel)

        if sortie:
            fermer_position(position, prix_actuel, sortie, portefeuille, trades_log)
        else:
            # Mise à jour jours restants
            date_entree = datetime.fromisoformat(position["date_entree"])
            jours_ecoules = (datetime.now(EASTERN) - date_entree).days
            jours_restants = PROFILS[ticker]["horizon_j"] - jours_ecoules
            position["jours_restants"] = jours_restants
            print(f"   ↳ Position conservée | {jours_restants}j restants | "
                  f"Objectif: {position['prix_pre_baisse']:.4f} $ | "
                  f"Stop: {position['prix_stop_loss']:.4f} $")


def action_rapport(trades_log: list, portefeuille: dict):
    """Affiche le rapport de métriques section 9."""
    metriques = calculer_metriques(trades_log, portefeuille)

    print("\n" + "=" * 65)
    print("  TMX v2 — Métriques Paper Trading (Section 9 PRD)")
    print("=" * 65)

    if "message" in metriques:
        print(f"\n  {metriques['message']}")
        return

    n = metriques["n_trades"]
    cibles = metriques["cibles_prd"]

    print(f"\n  Trades complétés : {n}")
    print(f"\n  {'Métrique':<30} {'Résultat':>12} {'Cible PRD':>12}")
    print("  " + "-" * 56)

    def ligne(label, valeur, cible, format_val="{:.2f}%"):
        v_str = format_val.format(valeur)
        print(f"  {label:<30} {v_str:>12} {cible:>12}")

    ligne("Hit rate",           metriques["hit_rate_pct"],      cibles["hit_rate"])
    ligne("Rendement moyen/trade", metriques["rendement_moyen_pct"], cibles["rendement_moyen"])
    ligne("Ratio gain/perte",   metriques["ratio_gain_perte"],  cibles["ratio_gain_perte"],
          "{:.2f}:1")
    ligne("Durée moyenne",      metriques["duree_moyenne_j"],   "8-25j", "{:.1f}j")
    ligne("MAE moyen",          metriques["mae_moyen_pct"],     "Conforme historique")
    ligne("Drawdown max",       metriques["drawdown_pct"],      cibles["drawdown_max"])

    if metriques["kill_switch_alertes"]:
        print("\n  ⚠️  ALERTES KILL SWITCH :")
        for alerte in metriques["kill_switch_alertes"]:
            print(f"     {alerte}")

    if metriques["criteres_go_live"]:
        print("\n  CRITÈRES GO-LIVE (section 9.3) :")
        for critere in metriques["criteres_go_live"]:
            print(f"     {critere}")

    print(f"\n  Capital initial  : {metriques['capital_initial']:>12,.2f} $")
    print(f"  Capital actuel   : {metriques['capital_actuel']:>12,.2f} $")
    print()


# ── Point d'entrée ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TMX v2 — Simulateur Paper Trading")
    parser.add_argument(
        "--action",
        choices=["evaluer", "surveiller", "rapport", "cycle"],
        default="cycle",
        help=(
            "evaluer   = évaluer signaux du scan et ouvrir positions\n"
            "surveiller = surveiller positions ouvertes et fermer si critères atteints\n"
            "rapport   = afficher métriques section 9\n"
            "cycle     = evaluer + surveiller (défaut)"
        ),
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=100_000.0,
        help="Capital virtuel initial en $ CAD (défaut : 100 000)",
    )
    args = parser.parse_args()

    print("=" * 65)
    print("  TMX v2 — Simulateur Paper Trading")
    print(f"  Action : {args.action.upper()}")
    print("=" * 65)

    # Charger l'état persistant
    portefeuille = charger_positions()
    trades_log   = charger_trades_log()

    # Initialiser le capital au premier lancement
    if portefeuille.get("capital_initial") == 100_000.0 and args.capital != 100_000.0:
        portefeuille["capital_initial"] = args.capital
        portefeuille["capital_disponible"] = args.capital

    try:
        if args.action in ("evaluer", "cycle"):
            action_evaluer(portefeuille, trades_log, args.capital)

        if args.action in ("surveiller", "cycle"):
            action_surveiller(portefeuille, trades_log)

        if args.action == "rapport":
            action_rapport(trades_log, portefeuille)

    finally:
        # Toujours sauvegarder l'état, même en cas d'erreur partielle
        sauvegarder_positions(portefeuille)
        sauvegarder_trades_log(trades_log)
        print(f"\n  💾 État sauvegardé — "
              f"{len(portefeuille['positions_ouvertes'])} position(s) ouverte(s) | "
              f"{len(trades_log)} trade(s) dans le log")
        print()


if __name__ == "__main__":
    main()
