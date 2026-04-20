"""
TMX v2 — Signaux de contagion inter-FNB  [PRD v3.0 — Section 5bis]

Logique : si un FNB émetteur contextuel chute ≥ seuil à la clôture du jour J,
le système place un trade J+1 sur le FNB récepteur actif à l'ouverture du lendemain.

Signaux déployés (Phase 2) :
  S1 — XRE → XIN  : achat XIN J+1  | Niveau 1 | p perm. 0,000 | 4/4 sous-périodes ✓
  S2 — XEG → XFN  : achat XFN J+1  | Niveau 2 | stabilité tridécennale | p=0,016
  S3 — XUT → XIN  : achat XIN J+1  | Niveau 1 | p perm. 0,002 | érosion 2021-26 à surveiller
  S4 — XUT → XFN  : achat XFN J+1  | Niveau 1 | p perm. <0,001

Signal en veille (ne pas déployer) :
  S5 — XEG → XIU  : achat XIU J+1  | Niveau 3 | n=14 seulement — hors production

Note : XUT est un FNB actif (mean reversion), donc son z-score vient du rapport scan
       principal (tous_fnbs), pas du flag choc_contagion réservé aux contextuels.
       XRE est aussi actif — même traitement.

Fichiers de persistance :
  contagion_pending.json  : signaux déclenchés J, en attente d'exécution J+1
  contagion_trades.json   : historique complet des trades de contagion fermés

Usage depuis main() de scanner.py :
  from contagion import evaluer_signaux_contagion, executer_trades_pending
  evaluer_signaux_contagion(rapport, portefeuille, trades_log)
  executer_trades_pending(portefeuille, trades_log, capital)
"""

import json
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf

EASTERN = ZoneInfo("America/Toronto")

# ── Définition des signaux (PRD v3.0 §5bis) ───────────────────────────────────

# Direction : "long" = achat du récepteur J+1 | "short" = vente à découvert (futur)
# taille_base : fraction de la position de base mean reversion (PRD §5bis)
#   Niveau 1 → 0.75 | Niveau 2 → 0.50
# seuil_emetteur : z-score de clôture qui déclenche le signal sur l'émetteur
# horizon_j : durée max du trade de contagion en jours de bourse
# emetteur_source : "contextuel" si le FNB est dans UNIVERSE_CONTEXTUEL,
#                   "actif" s'il est dans UNIVERSE_ACTIF (XRE, XUT)

SIGNAUX_CONTAGION = {
    "S1": {
        "label":            "XRE → XIN",
        "emetteur":         "XRE.TO",
        "emetteur_source":  "actif",        # XRE est actif, z-score dans tous_fnbs
        "recepteur":        "XIN.TO",
        "direction":        "long",
        "seuil_emetteur":   2.5,            # z20 ≤ -2.5 sur l'émetteur
        "taille_base":      0.75,           # Niveau 1
        "horizon_j":        1,              # trade J+1 : 1 jour de bourse
        "horizon_max_j":    3,              # max 3 jours si pas profitable à J+1
        "niveau":           1,
        "p_permutation":    0.000,
        "stabilite":        "4/4",
        "mecanisme":        "Décalage horaire — structurel",
        "risque_erosion":   "FAIBLE",
        "deploye":          True,
    },
    "S2": {
        "label":            "XEG → XFN",
        "emetteur":         "XEG.TO",
        "emetteur_source":  "contextuel",
        "recepteur":        "XFN.TO",
        "direction":        "long",
        "seuil_emetteur":   2.5,
        "taille_base":      0.50,           # Niveau 2
        "horizon_j":        1,
        "horizon_max_j":    3,
        "niveau":           2,
        "p_permutation":    None,           # test de permutation non disponible
        "stabilite":        "3/3",
        "mecanisme":        "Crédit mécanique — co-dépendance énergie-banques CA",
        "risque_erosion":   "FAIBLE",
        "deploye":          True,
    },
    "S3": {
        "label":            "XUT → XIN",
        "emetteur":         "XUT.TO",
        "emetteur_source":  "actif",
        "recepteur":        "XIN.TO",
        "direction":        "long",
        "seuil_emetteur":   2.5,
        "taille_base":      0.75,           # Niveau 1
        "horizon_j":        1,
        "horizon_max_j":    3,
        "niveau":           1,
        "p_permutation":    0.002,
        "stabilite":        "3/4",
        "mecanisme":        "Décalage horaire — érosion 2021-26 à surveiller",
        "risque_erosion":   "MODÉRÉ",
        "deploye":          True,
    },
    "S4": {
        "label":            "XUT → XFN",
        "emetteur":         "XUT.TO",
        "emetteur_source":  "actif",
        "recepteur":        "XFN.TO",
        "direction":        "long",
        "seuil_emetteur":   2.5,
        "taille_base":      0.75,           # Niveau 1
        "horizon_j":        1,
        "horizon_max_j":    3,
        "niveau":           1,
        "p_permutation":    0.001,
        "stabilite":        "3/4",
        "mecanisme":        "Rotation défensive — érosion 2021-26 à surveiller",
        "risque_erosion":   "MODÉRÉ",
        "deploye":          True,
    },
    "S5": {
        "label":            "XEG → XIU",
        "emetteur":         "XEG.TO",
        "emetteur_source":  "contextuel",
        "recepteur":        "XIU.TO",
        "direction":        "long",
        "seuil_emetteur":   3.0,            # seuil plus élevé — n=14 seulement
        "taille_base":      0.00,           # Niveau 3 — ne pas déployer
        "horizon_j":        1,
        "horizon_max_j":    3,
        "niveau":           3,
        "p_permutation":    None,
        "stabilite":        "irrégulière",
        "mecanisme":        "Rebalancement indiciel — n=14, trop limité",
        "risque_erosion":   "MODÉRÉ",
        "deploye":          False,          # EN VEILLE — ne pas déployer
    },
}

# Fichiers de persistance
FICHIER_PENDING = Path("contagion_pending.json")
FICHIER_TRADES  = Path("contagion_trades.json")


# ── Persistance ────────────────────────────────────────────────────────────────

def charger_pending() -> list[dict]:
    """Signaux déclenchés J, en attente d'exécution à l'ouverture J+1."""
    if FICHIER_PENDING.exists():
        with open(FICHIER_PENDING, encoding="utf-8") as f:
            return json.load(f)
    return []


def sauvegarder_pending(pending: list[dict]) -> None:
    with open(FICHIER_PENDING, "w", encoding="utf-8") as f:
        json.dump(pending, f, ensure_ascii=False, indent=2, default=str)


def charger_trades_contagion() -> list[dict]:
    """Historique complet des trades de contagion fermés."""
    if FICHIER_TRADES.exists():
        with open(FICHIER_TRADES, encoding="utf-8") as f:
            return json.load(f)
    return []


def sauvegarder_trades_contagion(trades: list[dict]) -> None:
    with open(FICHIER_TRADES, "w", encoding="utf-8") as f:
        json.dump(trades, f, ensure_ascii=False, indent=2, default=str)


# ── Lecture du rapport scan ────────────────────────────────────────────────────

def _z20_emetteur(rapport: dict, ticker: str) -> float | None:
    """Extrait le z20 d'un FNB depuis le rapport scan (actif ou contextuel)."""
    for fnb in rapport.get("tous_fnbs", []):
        if fnb.get("ticker") == ticker:
            return fnb.get("z20")
    return None


def _prix_cloture(rapport: dict, ticker: str) -> float | None:
    """Extrait le prix de clôture d'un FNB depuis le rapport scan."""
    for fnb in rapport.get("tous_fnbs", []):
        if fnb.get("ticker") == ticker:
            return fnb.get("prix_cloture")
    return None


# ── Évaluation des signaux à la clôture de J ──────────────────────────────────

def evaluer_signaux_contagion(rapport: dict) -> list[dict]:
    """
    Évalue les conditions de déclenchement à la clôture du jour J.
    Retourne la liste des signaux déclenchés (à exécuter J+1).

    Conditions de déclenchement :
      1. Signal marqué deploye=True
      2. Régime VIX != risk_off  (filtre Maillon 1 — seul filtre appliqué aux signaux de contagion)
      3. z20 de l'émetteur ≤ -seuil_emetteur
      4. Pas déjà en pending pour le même signal_id (évite les doublons)
    """
    regime    = rapport.get("regime_marche", {}).get("regime", "inconnu")
    scan_date = rapport.get("scan_at", "")[:10]  # "YYYY-MM-DD"
    pending   = charger_pending()

    # IDs déjà en attente pour éviter les doublons dans le même scan
    pending_ids = {p["signal_id"] for p in pending if p.get("date_declenchement") == scan_date}

    nouveaux: list[dict] = []

    for sid, cfg in SIGNAUX_CONTAGION.items():
        if not cfg["deploye"]:
            continue  # S5 en veille

        # Filtre Maillon 1 — VIX
        if regime == "risk_off":
            print(f"   ⏸  {sid} ({cfg['label']}) — bloqué par régime risk_off (VIX > 25)")
            continue

        # z20 de l'émetteur
        z20 = _z20_emetteur(rapport, cfg["emetteur"])
        if z20 is None:
            print(f"   ⚠️  {sid} ({cfg['label']}) — z20 émetteur {cfg['emetteur']} indisponible")
            continue

        if z20 > -cfg["seuil_emetteur"]:
            continue  # seuil non atteint — pas de signal

        # Vérifier doublon
        signal_id = f"{sid}_{scan_date}"
        if signal_id in pending_ids:
            print(f"   ℹ️  {sid} — signal déjà en pending pour {scan_date}, ignoré")
            continue

        # Taille ajustée selon régime neutre (PRD §5bis)
        taille = cfg["taille_base"]
        if regime == "neutre":
            taille /= 2.0

        prix_emetteur   = _prix_cloture(rapport, cfg["emetteur"])
        prix_recepteur  = _prix_cloture(rapport, cfg["recepteur"])
        date_execution  = _prochain_jour_bourse(scan_date)

        signal_pending = {
            "signal_id":         signal_id,
            "sid":               sid,
            "label":             cfg["label"],
            "emetteur":          cfg["emetteur"],
            "recepteur":         cfg["recepteur"],
            "direction":         cfg["direction"],
            "niveau":            cfg["niveau"],
            "mecanisme":         cfg["mecanisme"],
            "date_declenchement": scan_date,
            "date_execution":    date_execution,   # J+1
            "date_horizon_max":  _ajouter_jours_bourse(date_execution, cfg["horizon_max_j"] - 1),
            "z20_emetteur":      round(z20, 4),
            "seuil_emetteur":    cfg["seuil_emetteur"],
            "prix_emetteur_J":   prix_emetteur,
            "prix_recepteur_J":  prix_recepteur,   # prix de référence au déclenchement
            "taille_base":       cfg["taille_base"],
            "taille_ajustee":    round(taille, 4),
            "regime_declenchement": regime,
            "statut":            "pending",        # pending → ouvert → fermé
            "vix_declenchement": rapport.get("regime_marche", {}).get("vix"),
        }

        pending.append(signal_pending)
        pending_ids.add(signal_id)
        nouveaux.append(signal_pending)
        print(f"   🎯 {sid} DÉCLENCHÉ ({cfg['label']}) — z20={z20:+.2f} ≤ -{cfg['seuil_emetteur']} "
              f"| taille={taille:.2f}x | exécution J+1 ({date_execution})")

    if nouveaux:
        sauvegarder_pending(pending)

    return nouveaux


# ── Exécution des trades à l'ouverture de J+1 ─────────────────────────────────

def executer_trades_pending(portefeuille: dict, trades_contagion: list[dict], capital: float) -> list[dict]:
    """
    À appeler au premier scan du matin (J+1).
    Ouvre les positions de contagion en attente dont la date_execution == aujourd'hui.
    Retourne la liste des trades ouverts.
    """
    aujourd_hui  = date.today().isoformat()
    pending      = charger_pending()
    encore_pending: list[dict] = []
    ouverts: list[dict] = []

    for signal in pending:
        if signal["statut"] != "pending":
            encore_pending.append(signal)
            continue

        if signal["date_execution"] != aujourd_hui:
            # Pas encore le bon jour — garder en attente
            encore_pending.append(signal)
            continue

        # Vérifier que le récepteur n'est pas déjà en position de contagion
        recepteur = signal["recepteur"]
        cle_position = f"contagion_{signal['signal_id']}"
        if cle_position in portefeuille.get("positions_contagion", {}):
            print(f"   ⚠️  {signal['sid']} — position {cle_position} déjà ouverte, ignoré")
            encore_pending.append(signal)
            continue

        # Récupérer le prix d'ouverture via yfinance (période=1j, intervalle=1m → première bougie)
        prix_ouverture = _obtenir_prix_ouverture(recepteur)
        if prix_ouverture is None:
            print(f"   ⚠️  {signal['sid']} — prix ouverture {recepteur} indisponible, report à demain")
            encore_pending.append(signal)
            continue

        # Calcul du nombre d'unités
        capital_dispo = portefeuille.get("capital_disponible", capital)
        allocation    = capital_dispo * signal["taille_ajustee"] * 0.10  # 10% du capital × taille
        nb_unites     = max(1, int(allocation / prix_ouverture))

        # Coûts d'entrée (spread + slippage — 0 commission Disnat sur FNBs CA)
        spread_slippage = 0.0010  # 0.10% aller-retour (PRD §8.1 — Disnat)
        prix_execution  = round(prix_ouverture * (1 + spread_slippage / 2), 4)
        cout_total      = round(prix_execution * nb_unites, 2)

        if cout_total > capital_dispo:
            print(f"   ⚠️  {signal['sid']} — capital insuffisant ({cout_total:.2f}$ > {capital_dispo:.2f}$)")
            encore_pending.append(signal)
            continue

        # Ouvrir la position
        position = {
            "id":               cle_position,
            "signal_id":        signal["signal_id"],
            "sid":              signal["sid"],
            "label":            signal["label"],
            "ticker":           recepteur,
            "emetteur":         signal["emetteur"],
            "direction":        signal["direction"],
            "niveau":           signal["niveau"],
            "mecanisme":        signal["mecanisme"],
            "statut":           "ouvert",
            "type_trade":       "contagion",

            # Dates
            "date_entree":      datetime.now(EASTERN).isoformat(),
            "date_execution_prevue": aujourd_hui,
            "date_horizon_max": signal["date_horizon_max"],

            # Prix
            "prix_ouverture_J1":  round(prix_ouverture, 4),
            "prix_execution":     prix_execution,
            "prix_recepteur_J":   signal.get("prix_recepteur_J"),   # prix de référence veille

            # Taille
            "nb_unites":          nb_unites,
            "taille_ajustee":     signal["taille_ajustee"],
            "capital_investi":    cout_total,

            # Contexte du déclenchement
            "z20_emetteur_J":     signal["z20_emetteur"],
            "seuil_emetteur":     signal["seuil_emetteur"],
            "prix_emetteur_J":    signal["prix_emetteur_J"],
            "regime_declenchement": signal["regime_declenchement"],
            "vix_declenchement":  signal["vix_declenchement"],

            # Suivi P&L
            "prix_cloture_actuel": prix_execution,
            "pnl_brut_pct":       0.0,
            "pnl_brut_cad":       0.0,
            "jours_ouverts":      0,
        }

        # Initialiser le sous-dict positions_contagion si absent
        if "positions_contagion" not in portefeuille:
            portefeuille["positions_contagion"] = {}

        portefeuille["positions_contagion"][cle_position] = position
        portefeuille["capital_disponible"] = round(capital_dispo - cout_total, 2)

        signal["statut"] = "ouvert"
        signal["prix_execution"] = prix_execution
        signal["nb_unites"] = nb_unites
        signal["cout_total"] = cout_total

        ouverts.append(position)
        trades_contagion.append({**signal, "position": position})

        print(f"   ✅ {signal['sid']} OUVERT — {recepteur} × {nb_unites} u. "
              f"@ {prix_execution:.4f}$ | coût={cout_total:.2f}$")

    sauvegarder_pending(encore_pending)
    return ouverts


# ── Surveillance des positions ouvertes ───────────────────────────────────────

def surveiller_positions_contagion(portefeuille: dict, trades_contagion: list[dict]) -> list[dict]:
    """
    Surveille les positions de contagion ouvertes.
    Ferme si : horizon_max atteint OU prix actuel disponible (fin de journée).
    Retourne la liste des positions fermées dans ce cycle.
    """
    positions = portefeuille.get("positions_contagion", {})
    if not positions:
        return []

    aujourd_hui = date.today().isoformat()
    fermees: list[dict] = []
    a_supprimer: list[str] = []

    for cle, pos in positions.items():
        ticker = pos["ticker"]

        # Prix actuel
        prix_actuel = _obtenir_prix_courant(ticker)
        if prix_actuel is None:
            print(f"   ⚠️  Contagion {cle} — prix {ticker} indisponible, skip")
            continue

        # Mise à jour P&L
        prix_entree  = pos["prix_execution"]
        nb_unites    = pos["nb_unites"]
        pnl_brut_pct = (prix_actuel - prix_entree) / prix_entree * 100
        pnl_brut_cad = (prix_actuel - prix_entree) * nb_unites

        pos["prix_cloture_actuel"] = round(prix_actuel, 4)
        pos["pnl_brut_pct"]        = round(pnl_brut_pct, 4)
        pos["pnl_brut_cad"]        = round(pnl_brut_cad, 2)

        # Calcul jours ouverts
        date_entree  = pos["date_entree"][:10]
        jours_ouverts = _jours_bourse_entre(date_entree, aujourd_hui)
        pos["jours_ouverts"] = jours_ouverts

        # Décision de fermeture
        horizon_atteint = aujourd_hui >= pos["date_horizon_max"]
        raison_fermeture = None

        if horizon_atteint:
            raison_fermeture = f"horizon_max_atteint ({pos['date_horizon_max']})"

        if raison_fermeture:
            # Coûts de sortie
            spread_slippage  = 0.0010
            prix_sortie      = round(prix_actuel * (1 - spread_slippage / 2), 4)
            pnl_net_cad      = round((prix_sortie - prix_entree) * nb_unites, 2)
            pnl_net_pct      = round((prix_sortie - prix_entree) / prix_entree * 100, 4)

            pos["statut"]          = "fermé"
            pos["date_sortie"]     = datetime.now(EASTERN).isoformat()
            pos["prix_sortie"]     = prix_sortie
            pos["raison_sortie"]   = raison_fermeture
            pos["pnl_net_cad"]     = pnl_net_cad
            pos["pnl_net_pct"]     = pnl_net_pct
            pos["gagnant"]         = pnl_net_cad > 0

            # Restituer le capital
            portefeuille["capital_disponible"] = round(
                portefeuille.get("capital_disponible", 0) + prix_sortie * nb_unites, 2
            )

            fermees.append(pos)
            a_supprimer.append(cle)
            trades_contagion.append({**pos})

            icone = "✅" if pos["gagnant"] else "❌"
            print(f"   {icone} {pos['sid']} FERMÉ — {ticker} | P&L={pnl_net_pct:+.2f}% "
                  f"({pnl_net_cad:+.2f}$) | {raison_fermeture}")

    for cle in a_supprimer:
        del portefeuille["positions_contagion"][cle]

    return fermees


# ── Métriques de performance ───────────────────────────────────────────────────

def calculer_metriques_contagion(trades_contagion: list[dict]) -> dict:
    """
    Calcule les métriques de performance pour les signaux de contagion.
    Aligné avec les métriques PRD §9.1 — suivi par signal et global.
    """
    fermes = [t for t in trades_contagion if t.get("statut") == "fermé" and "pnl_net_pct" in t]
    if not fermes:
        return {"n_trades": 0, "message": "Aucun trade de contagion fermé"}

    pnls      = [t["pnl_net_pct"] for t in fermes]
    gagnants  = [t for t in fermes if t.get("gagnant")]
    hit_rate  = len(gagnants) / len(fermes) * 100
    rend_moy  = sum(pnls) / len(pnls)

    # Par signal
    par_signal: dict[str, dict] = {}
    for sid in SIGNAUX_CONTAGION:
        trades_sid = [t for t in fermes if t.get("sid") == sid]
        if not trades_sid:
            continue
        pnls_sid  = [t["pnl_net_pct"] for t in trades_sid]
        wins_sid  = [t for t in trades_sid if t.get("gagnant")]
        par_signal[sid] = {
            "label":       SIGNAUX_CONTAGION[sid]["label"],
            "n_trades":    len(trades_sid),
            "hit_rate":    round(len(wins_sid) / len(trades_sid) * 100, 1),
            "rend_moy":    round(sum(pnls_sid) / len(pnls_sid), 4),
            "rend_total":  round(sum(pnls_sid), 4),
            "niveau":      SIGNAUX_CONTAGION[sid]["niveau"],
            "alerte_erosion": (
                len(wins_sid) / len(trades_sid) < 0.45 and len(trades_sid) >= 5
            ),
        }

    return {
        "n_trades":         len(fermes),
        "hit_rate_pct":     round(hit_rate, 1),
        "rendement_moy_pct": round(rend_moy, 4),
        "rendement_total_pct": round(sum(pnls), 4),
        "n_gagnants":       len(gagnants),
        "n_perdants":       len(fermes) - len(gagnants),
        "par_signal":       par_signal,
    }


# ── Utilitaires calendrier ────────────────────────────────────────────────────

def _prochain_jour_bourse(date_str: str) -> str:
    """Retourne le prochain jour de bourse (lundi-vendredi) après date_str."""
    d = date.fromisoformat(date_str) + timedelta(days=1)
    while d.weekday() >= 5:  # 5=samedi, 6=dimanche
        d += timedelta(days=1)
    return d.isoformat()


def _ajouter_jours_bourse(date_str: str, n: int) -> str:
    """Retourne la date après n jours de bourse."""
    d = date.fromisoformat(date_str)
    ajoutes = 0
    while ajoutes < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            ajoutes += 1
    return d.isoformat()


def _jours_bourse_entre(date_debut: str, date_fin: str) -> int:
    """Compte les jours de bourse entre deux dates (inclusif début, exclusif fin)."""
    d1 = date.fromisoformat(date_debut)
    d2 = date.fromisoformat(date_fin)
    n  = 0
    d  = d1
    while d < d2:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


# ── Récupération des prix ─────────────────────────────────────────────────────

def _obtenir_prix_ouverture(ticker: str) -> float | None:
    """Prix d'ouverture du jour via yfinance (première bougie 1 minute)."""
    try:
        t    = yf.Ticker(ticker)
        hist = t.history(period="1d", interval="1m")
        if not hist.empty:
            return float(hist["Open"].iloc[0])
    except Exception as e:
        print(f"   ⚠️  Prix ouverture {ticker} : {e}")
    return None


def _obtenir_prix_courant(ticker: str) -> float | None:
    """Prix de clôture le plus récent via yfinance."""
    try:
        t    = yf.Ticker(ticker)
        hist = t.history(period="2d", interval="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as e:
        print(f"   ⚠️  Prix courant {ticker} : {e}")
    return None


# ── Point d'entrée autonome (test / diagnostic) ───────────────────────────────

def afficher_statut() -> None:
    """Affiche le statut courant des signaux de contagion — pending + métriques."""
    pending          = charger_pending()
    trades_contagion = charger_trades_contagion()
    metriques        = calculer_metriques_contagion(trades_contagion)

    print("\n" + "=" * 65)
    print("  TMX v2 — Signaux de contagion [PRD v3.0 §5bis]")
    print("=" * 65)

    print("\n  Signaux configurés :")
    for sid, cfg in SIGNAUX_CONTAGION.items():
        statut = "🟢 ACTIF" if cfg["deploye"] else "⏸  VEILLE"
        print(f"    {sid} {statut} — {cfg['label']} "
              f"(seuil={cfg['seuil_emetteur']} é.-t., taille={cfg['taille_base']:.2f}x, "
              f"Niv.{cfg['niveau']})")

    print(f"\n  Pending (en attente J+1) : {len(pending)} signal(s)")
    for p in pending:
        print(f"    {p['sid']} {p['label']} — exécution {p['date_execution']} "
              f"| z20={p['z20_emetteur']:+.2f}")

    print(f"\n  Performance globale : {metriques.get('n_trades', 0)} trade(s) fermé(s)")
    if metriques.get("n_trades", 0) > 0:
        print(f"    Hit rate   : {metriques['hit_rate_pct']:.1f}%")
        print(f"    Rend. moy. : {metriques['rendement_moy_pct']:+.4f}%")
        if metriques.get("par_signal"):
            print("    Par signal :")
            for sid, m in metriques["par_signal"].items():
                alerte = " ⚠️  ÉROSION" if m.get("alerte_erosion") else ""
                print(f"      {sid} {m['label']} : n={m['n_trades']} "
                      f"hit={m['hit_rate']:.0f}% rend={m['rend_moy']:+.4f}%{alerte}")
    print()


if __name__ == "__main__":
    afficher_statut()
