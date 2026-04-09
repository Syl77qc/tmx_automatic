"""
TMX v2 — Scanner de signaux z-scores
Phase 1, item 2 : Calcul des z-scores 20j et 60j sur les 12 FNBs

Références PRD :
  - Section 4.1  : Formule z-score (rendement du jour / écart-type N jours)
  - Section 4.3  : Profils FNB (rapide / moyen / lent) et seuils
  - Section 5    : Maillon 2 (scanner) et Maillon 3 (filtres)
  - Section 6    : Univers des 12 FNBs avec seuils et blocs de corrélation
  - Section 7.3  : Ajustement de taille selon z-score 60j
  - Section 9    : Métriques et tags de basketing

Source de données : yfinance (temporaire — remplacé par Questrade API dès activation)
Usage             : python scanner.py
                    python scanner.py --mode live   (pendant heures de marché)
                    python scanner.py --mode daily  (fin de journée)
"""

import json
import argparse
import warnings
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore", category=FutureWarning)

# ── Constantes PRD ─────────────────────────────────────────────────────────────

EASTERN = ZoneInfo("America/Toronto")

# Section 6 — Univers complet avec profils, seuils et blocs de corrélation
UNIVERSE = {
    "XIU.TO": {"profil": "rapide", "seuil_min": 2.0, "horizon_j": 10, "bloc": "marche_large"},
    "XFN.TO": {"profil": "moyen",  "seuil_min": 2.0, "horizon_j": 15, "bloc": "marche_large"},
    "XEG.TO": {"profil": "lent",   "seuil_min": 2.5, "horizon_j": 25, "bloc": None},
    "XUT.TO": {"profil": "rapide", "seuil_min": 2.0, "horizon_j": 10, "bloc": "taux"},
    "XIT.TO": {"profil": "rapide", "seuil_min": 2.0, "horizon_j": 10, "bloc": None},
    "XRE.TO": {"profil": "lent",   "seuil_min": 2.5, "horizon_j": 25, "bloc": "taux"},
    "XMA.TO": {"profil": "moyen",  "seuil_min": 2.0, "horizon_j": 15, "bloc": "metaux"},
    "XIN.TO": {"profil": "rapide", "seuil_min": 2.0, "horizon_j": 10, "bloc": "marche_large"},
    "XHC.TO": {"profil": "moyen",  "seuil_min": 2.0, "horizon_j": 15, "bloc": None},
    "XST.TO": {"profil": "rapide", "seuil_min": 2.0, "horizon_j": 10, "bloc": None},
    "XGD.TO": {"profil": "moyen",  "seuil_min": 2.0, "horizon_j": 15, "bloc": "metaux"},
    "ZAG.TO": {"profil": "lent",   "seuil_min": 2.5, "horizon_j": 25, "bloc": "taux"},
}

# Section 5, Maillon 1 — Seuils VIX
VIX_RISK_ON    = 16.0
VIX_RISK_OFF   = 25.0

# Section 4.1 — Fenêtres de calcul z-score
WINDOW_COURT   = 20   # z-score signal principal
WINDOW_MOYEN   = 60   # z-score confirmation / ajustement taille

# Section 7.3 — Seuil z60 pour ajustement de taille
Z60_SEUIL_CONFIRMATION = -1.5   # z60 ≤ -1.5 = signal "confirmé"

# Nombre de jours à télécharger (marge pour avoir 60 jours de bourse)
JOURS_HISTORIQUE = 100

# ── Téléchargement des données ─────────────────────────────────────────────────

def telecharger_historique(tickers: list[str], jours: int = JOURS_HISTORIQUE) -> pd.DataFrame:
    """
    Télécharge les données quotidiennes OHLCV pour tous les FNBs.
    Retourne un DataFrame multi-colonnes indexé par date.
    """
    print(f"\n📥 Téléchargement des données ({jours} jours) via yfinance...")
    fin = date.today()
    debut = fin - timedelta(days=jours)

    data = yf.download(
        tickers=tickers,
        start=debut.strftime("%Y-%m-%d"),
        end=fin.strftime("%Y-%m-%d"),
        interval="1d",
        group_by="ticker",
        auto_adjust=True,
        progress=False,
    )

    # Nettoyer les lignes sans données (weekends, fériés)
    data = data.dropna(how="all")

    n_jours = len(data)
    print(f"   ✅ {n_jours} jours de bourse récupérés ({debut} → {fin})")

    if n_jours < WINDOW_MOYEN:
        print(f"   ⚠️  {n_jours} jours < {WINDOW_MOYEN} requis pour z-score 60j — résultats partiels")

    return data


def telecharger_vix() -> float | None:
    """
    Télécharge le VIX en temps réel via yfinance.
    Retourne la dernière valeur disponible.
    PRD section 5, Maillon 1.
    """
    try:
        vix = yf.Ticker("^VIX")
        hist = vix.history(period="2d", interval="1d")
        if not hist.empty:
            valeur = float(hist["Close"].iloc[-1])
            return valeur
    except Exception as e:
        print(f"   ⚠️  Impossible de récupérer le VIX : {e}")
    return None


def telecharger_intraday(ticker: str, interval: str = "5m") -> pd.DataFrame:
    """
    Télécharge les données intraday 5 minutes pour un FNB.
    Limité aux 60 derniers jours par yfinance.
    Utilisé pour : momentum intraday, vélocité, filtre D (XIU).
    """
    try:
        t = yf.Ticker(ticker)
        data = t.history(period="1d", interval=interval)
        return data
    except Exception:
        return pd.DataFrame()


# ── Calculs z-scores ───────────────────────────────────────────────────────────

def extraire_closes(data: pd.DataFrame, ticker: str) -> pd.Series:
    """Extrait la série de prix de clôture pour un ticker donné."""
    try:
        closes = data[ticker]["Close"].dropna()
        return closes
    except KeyError:
        return pd.Series(dtype=float)


def calculer_rendements(closes: pd.Series) -> pd.Series:
    """
    Calcule les rendements journaliers.
    PRD section 4.1 : rendement = (prix aujourd'hui − prix hier) / prix hier
    """
    return closes.pct_change().dropna()


def calculer_zscore(rendements: pd.Series, fenetre: int) -> float | None:
    """
    Calcule le z-score du rendement le plus récent.
    PRD section 4.1 :
      z = (rendement_aujourd'hui − moyenne_N_jours) / écart_type_N_jours
    
    Note : le rendement du jour courant est exclu du calcul de la moyenne
    et de l'écart-type (on utilise les N jours précédents).
    """
    if len(rendements) < fenetre + 1:
        return None

    rendement_jour = rendements.iloc[-1]
    historique = rendements.iloc[-(fenetre + 1):-1]  # N jours précédents

    moyenne = historique.mean()
    ecart_type = historique.std(ddof=1)

    if ecart_type == 0 or np.isnan(ecart_type):
        return None

    return float((rendement_jour - moyenne) / ecart_type)


def calculer_sma50(closes: pd.Series) -> dict:
    """
    Calcule la SMA 50 jours et détermine si le prix est au-dessus ou en dessous.
    PRD section 5, Filtre F.
    """
    if len(closes) < 50:
        return {"sma50": None, "dessus_sma50": None}

    sma50 = float(closes.iloc[-50:].mean())
    prix_actuel = float(closes.iloc[-1])
    dessus = prix_actuel >= sma50

    return {
        "sma50": round(sma50, 4),
        "prix_actuel": round(prix_actuel, 4),
        "dessus_sma50": dessus,
    }


def calculer_momentum_intraday(ticker: str) -> dict:
    """
    Calcule le momentum intraday et la vélocité (dernière heure).
    PRD section 5, Maillon 2 :
      - Momentum : comment le prix évolue depuis l'ouverture
      - Vélocité : mouvement sur la dernière heure (12 bougies de 5 min)
    """
    data_5m = telecharger_intraday(ticker)

    if data_5m.empty or len(data_5m) < 2:
        return {
            "momentum_intraday_pct": None,
            "velocite_1h_pct": None,
            "source": "indisponible",
        }

    prix_ouverture = float(data_5m["Open"].iloc[0])
    prix_actuel = float(data_5m["Close"].iloc[-1])
    momentum = (prix_actuel - prix_ouverture) / prix_ouverture * 100

    # Vélocité : dernière heure = 12 bougies de 5 minutes
    n_bougies_1h = min(12, len(data_5m))
    prix_1h_avant = float(data_5m["Close"].iloc[-n_bougies_1h])
    velocite = (prix_actuel - prix_1h_avant) / prix_1h_avant * 100

    return {
        "momentum_intraday_pct": round(momentum, 4),
        "velocite_1h_pct": round(velocite, 4),
        "source": "yfinance_5m",
    }


# ── Régime de marché ───────────────────────────────────────────────────────────

def determiner_regime_vix(vix: float | None) -> dict:
    """
    Détermine le régime de marché selon le VIX.
    PRD section 5, Maillon 1.
    """
    if vix is None:
        return {"vix": None, "regime": "inconnu", "description": "VIX indisponible", "tag": "regime:inconnu"}

    if vix < VIX_RISK_ON:
        regime = "risk_on"
        description = f"VIX {vix:.1f} < {VIX_RISK_ON} — opération normale"
    elif vix <= VIX_RISK_OFF:
        regime = "neutre"
        description = f"VIX {vix:.1f} entre {VIX_RISK_ON}-{VIX_RISK_OFF} — tailles réduites"
    else:
        regime = "risk_off"
        description = f"VIX {vix:.1f} > {VIX_RISK_OFF} — pause ou signaux extrêmes seulement"

    return {
        "vix": round(vix, 2),
        "regime": regime,
        "description": description,
        "tag": f"regime:VIX_{regime}",
    }


# ── Filtre D — Corrélation avec le marché large ────────────────────────────────

def determiner_filtre_D(data: pd.DataFrame) -> dict:
    """
    Filtre D : XIU est-il stable/positif ou en baisse?
    PRD section 5, Maillon 3, Filtre D.
    
    - XIU ≥ 0%   : correction sectorielle isolée → seuil +0.5 é.-t. + taille ÷ 1.5
    - XIU < -0.5%: mouvement systémique → règles normales
    - Entre       : zone grise → log seulement
    """
    closes_xiu = extraire_closes(data, "XIU.TO")
    if len(closes_xiu) < 2:
        return {"xiu_rendement_pct": None, "contexte": "indisponible", "ajustement": "aucun"}

    rendement_xiu = float((closes_xiu.iloc[-1] - closes_xiu.iloc[-2]) / closes_xiu.iloc[-2] * 100)

    if rendement_xiu >= 0:
        contexte = "XIU_stable_ou_positif"
        ajustement = "seuil+0.5_taille÷1.5"
    elif rendement_xiu < -0.5:
        contexte = "XIU_en_baisse_systémique"
        ajustement = "règles_normales"
    else:
        contexte = "zone_grise"
        ajustement = "log_observation"

    return {
        "xiu_rendement_pct": round(rendement_xiu, 4),
        "contexte": contexte,
        "ajustement": ajustement,
    }


# ── Compteur de cluster ────────────────────────────────────────────────────────

def compter_cluster(signaux: list[dict]) -> dict:
    """
    Compte les FNBs en signal simultané.
    PRD section 5, Maillon 3, Filtre A.
    
    - 1-3 FNBs  : agir normalement
    - 4-6 FNBs  : taille ÷ 2 + seuil 2.5 é.-t.
    - 7+ FNBs   : bloquer toute nouvelle position
    """
    n = len(signaux)

    if n <= 3:
        action = "normal"
        tag = "cluster:1_3"
    elif n <= 6:
        action = "reduire_taille_50pct_et_seuil_2.5"
        tag = "cluster:4_6"
    else:
        action = "bloquer"
        tag = "cluster:7+"

    return {"n_signaux": n, "action": action, "tag": tag}


# ── Vérification jour BdC ──────────────────────────────────────────────────────

# PRD section 4.7 et Annexe A — Calendrier 2026
DATES_BDC_RPM    = {"2026-01-28", "2026-04-29", "2026-07-15", "2026-10-28"}
DATES_BDC_SANS_RPM = {"2026-03-18", "2026-06-10", "2026-09-02", "2026-12-09"}

def verifier_jour_bdc() -> dict:
    """
    Vérifie si aujourd'hui est un jour d'annonce BdC.
    PRD section 4.7, Annexe A.
    """
    aujourd_hui = date.today().strftime("%Y-%m-%d")

    if aujourd_hui in DATES_BDC_RPM:
        return {
            "est_jour_bdc": True,
            "type_bdc": "RPM",
            "tag": "boc:RPM",
            "regle": "Attendre 10h00 HE. Seuil +0.5 é.-t. pour XRE, XUT, XFN, ZAG.",
        }
    elif aujourd_hui in DATES_BDC_SANS_RPM:
        return {
            "est_jour_bdc": True,
            "type_bdc": "sans_RPM",
            "tag": "boc:sans_RPM",
            "regle": "Règles normales — ZAG tend à être positif ces jours.",
        }
    else:
        return {
            "est_jour_bdc": False,
            "type_bdc": None,
            "tag": "boc:non_BdC",
            "regle": None,
        }


# ── Calcul du multiplicateur de taille ────────────────────────────────────────

def calculer_multiplicateur_taille(
    ticker: str,
    z20: float,
    z60: float | None,
    regime: str,
    filtre_D: dict,
    dessus_sma50: bool | None,
    cluster_action: str,
) -> dict:
    """
    Calcule le multiplicateur de taille de position final.
    PRD sections 7.1, 7.2, 7.3.

    Base selon profil :
      Rapide : 100% | Moyen : 75% | Lent : 50%
    
    Multiplicateur selon profondeur du signal :
      2.0 é.-t. : 1.0x | 2.5 é.-t. : 1.5x | 3.0 é.-t. : 2.0x
    
    Ajustements cumulatifs selon filtres.
    """
    cfg = UNIVERSE[ticker]
    profil = cfg["profil"]

    # Base profil (section 7.2)
    base = {"rapide": 1.00, "moyen": 0.75, "lent": 0.50}[profil]

    # Multiplicateur signal (section 7.1)
    az20 = abs(z20)
    if az20 >= 3.0:
        mult_signal = 2.0
        bucket_z20 = "z20:≥3.0"
    elif az20 >= 2.5:
        mult_signal = 1.5
        bucket_z20 = "z20:2.5-2.99"
    else:
        mult_signal = 1.0
        bucket_z20 = "z20:2.0-2.49"

    taille = base * mult_signal

    # Ajustements (section 7.3) — cumulatifs
    ajustements = []

    if regime == "neutre":
        taille /= 2
        ajustements.append("régime_neutre÷2")

    if dessus_sma50 is False:
        taille /= 2
        ajustements.append("sous_SMA50÷2")

    if z60 is not None and z60 > Z60_SEUIL_CONFIRMATION:
        taille /= 1.5
        ajustements.append("z60_faible÷1.5")

    if filtre_D.get("ajustement") == "seuil+0.5_taille÷1.5":
        taille /= 1.5
        ajustements.append("filtreD_XIU_stable÷1.5")

    if cluster_action == "reduire_taille_50pct_et_seuil_2.5":
        taille /= 2
        ajustements.append("cluster_4_6÷2")

    # Tag z60
    if z60 is None:
        tag_z60 = "z60:N/A"
    elif z60 <= Z60_SEUIL_CONFIRMATION:
        tag_z60 = "z60:confirmé"
    else:
        tag_z60 = "z60:faible"

    return {
        "taille_finale": round(taille, 4),
        "base_profil": base,
        "mult_signal": mult_signal,
        "ajustements": ajustements,
        "bucket_z20": bucket_z20,
        "tag_z60": tag_z60,
    }


# ── Analyse complète par FNB ───────────────────────────────────────────────────

def analyser_fnb(
    ticker: str,
    data: pd.DataFrame,
    regime_info: dict,
    filtre_D: dict,
    jour_bdc: dict,
    mode: str,
) -> dict:
    """
    Analyse complète d'un FNB : z-scores, SMA50, signal, tags de basketing.
    """
    cfg = UNIVERSE[ticker]
    closes = extraire_closes(data, ticker)

    if closes.empty or len(closes) < WINDOW_COURT + 1:
        return {
            "ticker": ticker,
            "erreur": f"Données insuffisantes ({len(closes)} jours)",
            "signal": False,
        }

    rendements = calculer_rendements(closes)

    # Z-scores
    z20 = calculer_zscore(rendements, WINDOW_COURT)
    z60 = calculer_zscore(rendements, WINDOW_MOYEN)

    # SMA 50 jours (Filtre F)
    sma_info = calculer_sma50(closes)

    # Rendement du jour
    rendement_jour = float(rendements.iloc[-1]) if len(rendements) > 0 else None

    # Signal actif?
    seuil_effectif = cfg["seuil_min"]

    # Ajustement seuil : jour BdC avec RPM pour FNBs sensibles aux taux
    fnbs_sensibles_taux = {"XRE.TO", "XUT.TO", "XFN.TO", "ZAG.TO"}
    if jour_bdc["type_bdc"] == "RPM" and ticker in fnbs_sensibles_taux:
        seuil_effectif += 0.5

    # Ajustement seuil Filtre D
    if filtre_D.get("ajustement") == "seuil+0.5_taille÷1.5":
        seuil_effectif += 0.5

    # Ajustement seuil cluster 4-6
    # (sera appliqué après le comptage global — marqué ici pour log)

    signal_actif = z20 is not None and z20 <= -seuil_effectif

    # Momentum intraday (seulement en mode live pour éviter les appels inutiles)
    intraday = {}
    if mode == "live" and signal_actif:
        intraday = calculer_momentum_intraday(ticker)

    # Tags de basketing (section 9 PRD + commentaires reçus)
    tags = [
        jour_bdc["tag"],
        regime_info["tag"],
        f"bloc:{cfg['bloc'] or 'autre'}",
        f"profil:{cfg['profil']}",
    ]

    if z20 is not None:
        az20 = abs(z20)
        tags.append("z20:2.0-2.49" if az20 < 2.5 else ("z20:2.5-2.99" if az20 < 3.0 else "z20:≥3.0"))

    if z60 is not None:
        tags.append("z60:confirmé" if z60 <= Z60_SEUIL_CONFIRMATION else "z60:faible")
    else:
        tags.append("z60:N/A")

    if sma_info["dessus_sma50"] is not None:
        tags.append("trend:SMA50_dessus" if sma_info["dessus_sma50"] else "trend:SMA50_sous")

    resultat = {
        "ticker": ticker,
        "profil": cfg["profil"],
        "seuil_min_base": cfg["seuil_min"],
        "seuil_effectif": seuil_effectif,
        "horizon_j": cfg["horizon_j"],
        "bloc": cfg["bloc"],
        "prix_cloture": float(closes.iloc[-1]),
        "rendement_jour_pct": round(rendement_jour * 100, 4) if rendement_jour else None,
        "z20": round(z20, 4) if z20 is not None else None,
        "z60": round(z60, 4) if z60 is not None else None,
        "sma50": sma_info.get("sma50"),
        "dessus_sma50": sma_info.get("dessus_sma50"),
        "signal": signal_actif,
        "tags": tags,
    }

    if intraday:
        resultat["intraday"] = intraday

    return resultat


# ── Rapport final ──────────────────────────────────────────────────────────────

def generer_rapport(
    resultats: list[dict],
    regime_info: dict,
    filtre_D: dict,
    jour_bdc: dict,
    cluster_info: dict,
) -> dict:
    """Assemble le rapport JSON final."""

    signaux = [r for r in resultats if r.get("signal")]

    # Ajouter le tag cluster à chaque signal
    for s in signaux:
        s["tags"].append(cluster_info["tag"])

    maintenant = datetime.now(EASTERN)
    est_heures_marche = (
        maintenant.weekday() < 5
        and maintenant.hour >= 9
        and (maintenant.hour > 9 or maintenant.minute >= 30)
        and maintenant.hour < 16
    )

    return {
        "scan_at": maintenant.isoformat(),
        "source_donnees": "yfinance (temporaire — Questrade API à l'activation du compte)",
        "heures_marche": est_heures_marche,
        "regime_marche": regime_info,
        "filtre_D": filtre_D,
        "jour_bdc": jour_bdc,
        "cluster": cluster_info,
        "n_fnbs_scannes": len(resultats),
        "n_signaux": len(signaux),
        "signaux": signaux,
        "tous_fnbs": resultats,
    }


def afficher_console(rapport: dict):
    """Affiche un résumé lisible dans le terminal."""

    now = rapport["scan_at"][:19].replace("T", " ")
    regime = rapport["regime_marche"]
    bdc = rapport["jour_bdc"]
    cluster = rapport["cluster"]

    print("\n" + "=" * 65)
    print(f"  TMX v2 — Scan z-scores   {now}")
    print("=" * 65)

    # Régime
    icone_regime = {"risk_on": "🟢", "neutre": "🟡", "risk_off": "🔴"}.get(
        regime["regime"], "⚪"
    )
    print(f"\n  {icone_regime} Régime VIX : {regime.get('description', 'inconnu')}")

    # BdC
    if bdc["est_jour_bdc"]:
        print(f"  ⚠️  Jour BdC ({bdc['type_bdc']}) : {bdc['regle']}")

    # Cluster
    n = cluster["n_signaux"]
    if n == 0:
        print(f"\n  Aucun signal actif sur les {rapport['n_fnbs_scannes']} FNBs scannés.")
    else:
        icone_cluster = "🟢" if n <= 3 else ("🟡" if n <= 6 else "🔴")
        print(f"\n  {icone_cluster} {n} signal(s) — {cluster['action']}")

    # Tableau des signaux
    if rapport["signaux"]:
        print(f"\n  {'FNB':<10} {'Profil':<8} {'Z20':>7} {'Z60':>7} "
              f"{'SMA50':>8} {'Seuil':>7} {'Taille':>8}")
        print("  " + "-" * 58)

        for s in rapport["signaux"]:
            z20_str = f"{s['z20']:+.2f}" if s["z20"] is not None else "  N/A"
            z60_str = f"{s['z60']:+.2f}" if s["z60"] is not None else "  N/A"
            sma_str = "✓" if s.get("dessus_sma50") else ("✗" if s.get("dessus_sma50") is False else "?")

            # Calculer taille indicative (sans cluster appliqué ici pour affichage)
            taille_info = calculer_multiplicateur_taille(
                s["ticker"],
                s["z20"],
                s["z60"],
                rapport["regime_marche"]["regime"],
                rapport["filtre_D"],
                s.get("dessus_sma50"),
                cluster["action"],
            )
            taille_str = f"{taille_info['taille_finale']:.2f}x"

            print(f"  {s['ticker']:<10} {s['profil']:<8} {z20_str:>7} {z60_str:>7} "
                  f"{sma_str:>8} {s['seuil_effectif']:>7.1f} {taille_str:>8}")

    # Vue d'ensemble de tous les FNBs
    print(f"\n  {'FNB':<10} {'Z20':>7} {'Z60':>7} {'SMA50':>8} {'Prix':>8}")
    print("  " + "-" * 45)
    for r in rapport["tous_fnbs"]:
        if r.get("erreur"):
            print(f"  {r['ticker']:<10} {'ERREUR'}")
            continue
        z20_str = f"{r['z20']:+.2f}" if r["z20"] is not None else "  N/A"
        z60_str = f"{r['z60']:+.2f}" if r["z60"] is not None else "  N/A"
        sma_str = "✓" if r.get("dessus_sma50") else ("✗" if r.get("dessus_sma50") is False else "?")
        prix_str = f"{r['prix_cloture']:.2f}" if r.get("prix_cloture") else "N/A"
        flag = " ◄ SIGNAL" if r.get("signal") else ""
        print(f"  {r['ticker']:<10} {z20_str:>7} {z60_str:>7} {sma_str:>8} {prix_str:>8}{flag}")

    print()


# ── Point d'entrée ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TMX v2 — Scanner z-scores")
    parser.add_argument(
        "--mode",
        choices=["daily", "live"],
        default="daily",
        help="daily = données de clôture uniquement | live = inclut momentum intraday",
    )
    parser.add_argument(
        "--output",
        default="scan_results.json",
        help="Fichier JSON de sortie (défaut : scan_results.json)",
    )
    args = parser.parse_args()

    print("=" * 65)
    print("  TMX v2 — Scanner de signaux z-scores")
    print(f"  Mode : {args.mode.upper()}")
    print("=" * 65)

    tickers = list(UNIVERSE.keys())

    # 1. Données historiques quotidiennes
    data = telecharger_historique(tickers)

    # 2. VIX et régime de marché
    print("\n📊 Récupération du VIX...")
    vix = telecharger_vix()
    regime_info = determiner_regime_vix(vix)
    print(f"   {regime_info['description']}")

    # 3. Filtre D — contexte XIU
    filtre_D = determiner_filtre_D(data)
    print(f"\n🔍 Filtre D (XIU) : {filtre_D['contexte']} "
          f"(rendement : {filtre_D.get('xiu_rendement_pct', 'N/A')}%)")

    # 4. Jour BdC
    jour_bdc = verifier_jour_bdc()
    if jour_bdc["est_jour_bdc"]:
        print(f"\n⚠️  Jour BdC détecté : {jour_bdc['type_bdc']}")

    # 5. Analyse de chaque FNB
    print(f"\n🔎 Analyse des {len(tickers)} FNBs...")
    resultats = []
    for ticker in tickers:
        r = analyser_fnb(ticker, data, regime_info, filtre_D, jour_bdc, args.mode)
        resultats.append(r)
        z20_str = f"{r['z20']:+.3f}" if r.get("z20") is not None else "N/A"
        z60_str = f"{r['z60']:+.3f}" if r.get("z60") is not None else "N/A"
        flag = " ◄ SIGNAL" if r.get("signal") else ""
        print(f"   {ticker:<10} z20: {z20_str:>8}  z60: {z60_str:>8}{flag}")

    # 6. Compteur de cluster
    signaux_actifs = [r for r in resultats if r.get("signal")]
    cluster_info = compter_cluster(signaux_actifs)

    # 7. Rapport
    rapport = generer_rapport(resultats, regime_info, filtre_D, jour_bdc, cluster_info)
    afficher_console(rapport)

    # 8. Sauvegarde JSON
    output_path = Path(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(rapport, f, ensure_ascii=False, indent=2, default=str)
    print(f"  📄 Rapport sauvegardé : {output_path.resolve()}")
    print()


if __name__ == "__main__":
    main()
