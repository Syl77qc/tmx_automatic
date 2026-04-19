"""
TMX v2 — Scanner de signaux z-scores  (PRD v3.0)
Phase 1, item 2 : Calcul des z-scores 20j et 60j sur les 12 FNBs

Source de données permanente : yfinance (PRD v3.0 — C7)
  Questrade abandonné définitivement (blocage Cloudflare, conditions API).
  Le code Questrade est conservé mais ne s'active qu'en présence du secret.

Garde de fraîcheur (PRD v3.0 — C7) :
  Si la dernière date des données ≠ date du jour → alerte console + courriel.

Secrets GitHub requis :
  GMAIL_USER          : adresse Gmail expéditrice (pour alertes fraîcheur)
  GMAIL_APP_PASSWORD  : mot de passe d'application Google
  NOTIF_EMAIL_1       : destinataire courriel 1
  NOTIF_EMAIL_2       : destinataire courriel 2 (optionnel)
  QUESTRADE_REFRESH_TOKEN : (obsolète — conservé pour compatibilité)
  GH_PAT              : Personal Access Token GitHub (scope: repo)
"""

import json
import os
import argparse
import warnings
import urllib.request
import urllib.error
import urllib.parse
import base64
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore", category=FutureWarning)

EASTERN = ZoneInfo("America/Toronto")

# ── PRD v3.0 — C1 + C2 : Univers réduit à 7 FNBs actifs, horizons Wilcoxon corrigés ──

# FNBs actifs — signal mean reversion validé, positions ouvertes par le simulateur
UNIVERSE = {
    "XIU.TO": {"profil": "moyen",  "seuil_min": 2.0, "horizon_j": 20, "bloc": "marche_large"},
    "XFN.TO": {"profil": "moyen",  "seuil_min": 2.0, "horizon_j": 20, "bloc": "marche_large"},
    "XUT.TO": {"profil": "moyen",  "seuil_min": 2.0, "horizon_j": 20, "bloc": "taux"},
    "XRE.TO": {"profil": "moyen",  "seuil_min": 2.0, "horizon_j": 20, "bloc": "taux"},
    "XIN.TO": {"profil": "rapide", "seuil_min": 2.0, "horizon_j": 10, "bloc": "marche_large"},
    "XHC.TO": {"profil": "rapide", "seuil_min": 2.0, "horizon_j": 10, "bloc": None},
    "XST.TO": {"profil": "rapide", "seuil_min": 2.0, "horizon_j": 15, "bloc": None},
}

# FNBs contextuels — z-scores calculés, pas de position mean reversion.
# Leurs chocs ≥ seuil activent les signaux de contagion (PRD section 5bis).
UNIVERSE_CONTEXTUEL = {
    "XEG.TO": {"seuil_contagion": 2.5, "bloc": None},      # émetteur S2, S5
    "ZAG.TO": {"seuil_contagion": 2.5, "bloc": "taux"},
    "XGD.TO": {"seuil_contagion": 2.5, "bloc": "metaux"},
    "XIT.TO": {"seuil_contagion": 2.5, "bloc": None},
    "XMA.TO": {"seuil_contagion": 2.5, "bloc": "metaux"},
}

VIX_RISK_ON            = 16.0
VIX_RISK_OFF           = 25.0
WINDOW_COURT           = 20
WINDOW_MOYEN           = 60
Z60_SEUIL_CONFIRMATION = -1.5
JOURS_HISTORIQUE       = 100

# ── Questrade API ──────────────────────────────────────────────────────────────

QUESTRADE_SYMBOLS = {
    "XIU.TO": "XIU", "XFN.TO": "XFN", "XEG.TO": "XEG",
    "XUT.TO": "XUT", "XIT.TO": "XIT", "XRE.TO": "XRE",
    "XMA.TO": "XMA", "XIN.TO": "XIN", "XHC.TO": "XHC",
    "XST.TO": "XST", "XGD.TO": "XGD", "ZAG.TO": "ZAG",
}


def _questrade_auth(refresh_token: str) -> dict | None:
    url = "https://login.questrade.com/oauth2/token"
    payload = urllib.parse.urlencode({
        "grant_type":    "refresh_token",
        "refresh_token": refresh_token,
    }).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return {
            "access_token":      data["access_token"],
            "api_server":        data["api_server"].rstrip("/"),
            "new_refresh_token": data["refresh_token"],
        }
    except urllib.error.HTTPError as e:
        try:
            corps = e.read().decode("utf-8", errors="replace")
        except Exception:
            corps = "(corps illisible)"
        print(f"   ⚠️  Questrade auth échouée : HTTP {e.code} {e.reason}")
        print(f"   ⚠️  URL appelée : {url}")
        print(f"   ⚠️  Réponse Questrade : {corps[:400]}")
        print(f"   ⚠️  Token utilisé (10 premiers chars) : {refresh_token[:10]}...")
        return None
    except urllib.error.URLError as e:
        print(f"   ⚠️  Questrade auth — erreur réseau : {e.reason}")
        return None
    except Exception as e:
        print(f"   ⚠️  Questrade auth — erreur inattendue : {type(e).__name__} : {e}")
        return None


def _github_update_secret(repo: str, secret_name: str, secret_value: str, gh_pat: str) -> bool:
    try:
        url_key = f"https://api.github.com/repos/{repo}/actions/secrets/public-key"
        headers = {
            "Authorization": f"token {gh_pat}",
            "Accept": "application/vnd.github+json",
        }
        req = urllib.request.Request(url_key, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            key_data = json.loads(resp.read())
        key_id      = key_data["key_id"]
        pub_key_b64 = key_data["key"]
        try:
            from nacl import encoding, public as nacl_public
            pub_key_bytes = base64.b64decode(pub_key_b64)
            sealed_box    = nacl_public.SealedBox(nacl_public.PublicKey(pub_key_bytes))
            encrypted     = sealed_box.encrypt(secret_value.encode("utf-8"))
            encrypted_b64 = base64.b64encode(encrypted).decode("utf-8")
        except ImportError:
            print("   ⚠️  PyNaCl non installé — rotation token skippée.")
            return False
        url_secret = f"https://api.github.com/repos/{repo}/actions/secrets/{secret_name}"
        payload = json.dumps({
            "encrypted_value": encrypted_b64,
            "key_id": key_id,
        }).encode("utf-8")
        req2 = urllib.request.Request(
            url_secret, data=payload, headers=headers, method="PUT"
        )
        with urllib.request.urlopen(req2, timeout=10) as resp2:
            return resp2.status in (201, 204)
    except Exception as e:
        print(f"   ⚠️  Mise à jour GitHub Secret échouée : {e}")
        return False


def _questrade_get_closes(auth: dict, tickers: list[str], jours: int) -> pd.DataFrame | None:
    try:
        access_token = auth["access_token"]
        api_server   = auth["api_server"]
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type":  "application/json",
        }
        fin   = date.today()
        debut = fin - timedelta(days=jours)
        symbol_ids = {}
        for ticker in tickers:
            sym = QUESTRADE_SYMBOLS.get(ticker, ticker.replace(".TO", ""))
            url = f"{api_server}/v1/symbols/search?prefix={sym}&exchange=TSX"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            symbols = data.get("symbols", [])
            if symbols:
                symbol_ids[ticker] = symbols[0]["symbolId"]
        if not symbol_ids:
            return None
        all_closes = {}
        for ticker, sym_id in symbol_ids.items():
            url = (
                f"{api_server}/v1/markets/candles/{sym_id}"
                f"?startTime={debut.isoformat()}T00:00:00-05:00"
                f"&endTime={fin.isoformat()}T23:59:59-05:00"
                f"&interval=OneDay"
            )
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            candles = data.get("candles", [])
            if candles:
                closes = {
                    pd.Timestamp(c["start"][:10]): c["close"]
                    for c in candles if c.get("close")
                }
                all_closes[ticker] = closes
        if not all_closes:
            return None
        dfs = {}
        for ticker, closes_dict in all_closes.items():
            s = pd.Series(closes_dict, name="Close")
            s.index = pd.DatetimeIndex(s.index)
            dfs[ticker] = pd.DataFrame({"Close": s})
        combined = pd.concat(dfs, axis=1)
        combined.columns = pd.MultiIndex.from_tuples(
            [(ticker, "Close") for ticker in dfs.keys()]
        )
        combined = combined.dropna(how="all")
        return combined
    except Exception as e:
        print(f"   ⚠️  Questrade données échouées : {e}")
        return None


# ── Téléchargement des données ─────────────────────────────────────────────────

def telecharger_historique(tickers: list[str], jours: int = JOURS_HISTORIQUE) -> pd.DataFrame:
    refresh_token = os.environ.get("QUESTRADE_REFRESH_TOKEN", "")
    gh_pat        = os.environ.get("GH_PAT", "")
    repo          = os.environ.get("GITHUB_REPOSITORY", "")

    print(f"   🔑 QUESTRADE_REFRESH_TOKEN : {'✅ présent' if refresh_token else '❌ ABSENT'}")
    print(f"   🔑 GH_PAT                  : {'✅ présent' if gh_pat else '❌ ABSENT'}")
    print(f"   🔑 GITHUB_REPOSITORY       : {repo or '❌ ABSENT'}")

    if refresh_token:
        print(f"\n📥 Téléchargement des données ({jours} jours) via Questrade API...")
        auth = _questrade_auth(refresh_token)
        if auth:
            new_token = auth["new_refresh_token"]
            if gh_pat and repo and new_token != refresh_token:
                ok = _github_update_secret(repo, "QUESTRADE_REFRESH_TOKEN", new_token, gh_pat)
                if ok:
                    print("   🔄 Refresh token Questrade renouvelé automatiquement.")
                else:
                    print("   ⚠️  Rotation token échouée — token actuel encore valide.")
            data = _questrade_get_closes(auth, tickers, jours)
            if data is not None and len(data) >= WINDOW_COURT:
                print(f"   ✅ {len(data)} jours récupérés via Questrade (temps réel)")
                return data
            else:
                print("   ⚠️  Données Questrade insuffisantes — bascule sur yfinance.")
        else:
            print("   ⚠️  Authentification Questrade échouée — bascule sur yfinance.")
    else:
        print(f"\n📥 Téléchargement des données ({jours} jours) via yfinance...")

    fin   = date.today()
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
    data = data.dropna(how="all")
    n_jours = len(data)
    print(f"   ✅ {n_jours} jours de bourse récupérés via yfinance ({debut} → {fin})")
    if n_jours < WINDOW_MOYEN:
        print(f"   ⚠️  {n_jours} jours < {WINDOW_MOYEN} requis pour z-score 60j — résultats partiels")

    # ── Garde de fraîcheur (PRD v3.0 — C7) ──────────────────────────────────
    # Vérifier que chaque FNB a bien des données du jour courant.
    # Les marchés canadiens ferment à 16h HE — après 16h15 on attend le prix de clôture.
    # En dehors des heures de marché (week-end, avant ouverture) on vérifie le dernier
    # jour de bourse disponible vs la date de la dernière entrée dans le DataFrame.
    maintenant_et   = datetime.now(EASTERN)
    est_jour_bourse = maintenant_et.weekday() < 5  # lundi=0 … vendredi=4
    apres_cloture   = maintenant_et.hour >= 16

    # La dernière date attendue : aujourd'hui si c'est un jour de bourse et après 16h,
    # sinon on ne déclenche pas l'alerte (données du dernier jour de bourse = normales).
    if est_jour_bourse and apres_cloture:
        fnbs_perimes = []
        for ticker in tickers:
            try:
                closes = data[ticker]["Close"].dropna()
                if closes.empty:
                    fnbs_perimes.append((ticker, "aucune donnée"))
                    continue
                derniere_date = closes.index[-1].date()
                if derniere_date != fin:
                    fnbs_perimes.append((ticker, str(derniere_date)))
            except KeyError:
                fnbs_perimes.append((ticker, "colonne absente"))

        if fnbs_perimes:
            print("\n" + "!" * 65)
            print("  🚨 ALERTE FRAÎCHEUR DONNÉES yfinance")
            for t, d in fnbs_perimes:
                print(f"     {t:<10} dernière date disponible : {d}  (attendu : {fin})")
            print("!" * 65 + "\n")
            _envoyer_alerte_fraicheur(fnbs_perimes, fin)
        else:
            print(f"   ✅ Fraîcheur confirmée — toutes les données sont à jour ({fin})")
    else:
        print(f"   ℹ️  Garde fraîcheur non déclenchée "
              f"({'hors heures de clôture' if est_jour_bourse else 'hors jour de bourse'})")

    return data


def _envoyer_alerte_fraicheur(fnbs_perimes: list[tuple], date_attendue: date):
    """
    Déclenche une notification courriel via notifier.py lorsque des données
    yfinance sont périmées (PRD v3.0 — C7 : garde de fraîcheur).

    Forge un rapport minimal compatible avec envoyer_notifications() sans
    modifier notifier.py.
    """
    maintenant = datetime.now(EASTERN)
    liste_fnbs = ", ".join(f"{t} ({d})" for t, d in fnbs_perimes)

    # Rapport minimal qui passe les vérifications de envoyer_notifications()
    # On injecte un faux signal pour forcer l'envoi (n_signaux > 0, cluster non bloquant)
    rapport_fraicheur = {
        "scan_at":       maintenant.isoformat(),
        "source_donnees": "yfinance",
        "heures_marche": True,
        "regime_marche": {
            "vix": None,
            "regime": "inconnu",
            "description": "N/A — alerte fraîcheur",
            "tag": "regime:inconnu",
        },
        "filtre_D": {
            "xiu_rendement_pct": None,
            "contexte": "N/A — alerte fraîcheur",
            "ajustement": "aucun",
        },
        "jour_bdc":  {"est_jour_bdc": False, "type_bdc": None, "tag": "boc:non_BdC", "regle": None},
        "cluster":   {"n_signaux": 1, "action": "normal", "tag": "cluster:fraicheur"},
        "n_fnbs_scannes": len(fnbs_perimes),
        "n_signaux": 1,
        # Signal synthétique portant l'information d'alerte
        "signaux": [{
            "ticker":          "ALERTE_FRAICHEUR",
            "profil":          "N/A",
            "seuil_min_base":  0.0,
            "seuil_effectif":  0.0,
            "horizon_j":       0,
            "bloc":            None,
            "prix_cloture":    0.0,
            "rendement_jour_pct": None,
            "z20":             -9.99,   # valeur sentinelle visible dans le courriel
            "z60":             None,
            "sma50":           None,
            "dessus_sma50":    None,
            "signal":          True,
            "tags":            [f"FRAICHEUR:{date_attendue}", f"fnbs:{liste_fnbs}"],
        }],
        "tous_fnbs": [],
    }

    try:
        from notifier import envoyer_notifications
        print("   📬 Envoi alerte fraîcheur par courriel...")
        envoyer_notifications(rapport_fraicheur)
    except Exception as e:
        print(f"   ⚠️  Alerte fraîcheur — envoi courriel échoué : {e}")


def telecharger_vix() -> float | None:
    try:
        vix = yf.Ticker("^VIX")
        hist = vix.history(period="2d", interval="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as e:
        print(f"   ⚠️  Impossible de récupérer le VIX : {e}")
    return None


def telecharger_intraday(ticker: str, interval: str = "5m") -> pd.DataFrame:
    try:
        t = yf.Ticker(ticker)
        return t.history(period="1d", interval=interval)
    except Exception:
        return pd.DataFrame()


# ── Calculs z-scores ───────────────────────────────────────────────────────────

def extraire_closes(data: pd.DataFrame, ticker: str) -> pd.Series:
    try:
        return data[ticker]["Close"].dropna()
    except KeyError:
        return pd.Series(dtype=float)


def calculer_rendements(closes: pd.Series) -> pd.Series:
    return closes.pct_change().dropna()


def calculer_zscore(rendements: pd.Series, fenetre: int) -> float | None:
    if len(rendements) < fenetre + 1:
        return None
    rendement_jour = rendements.iloc[-1]
    historique     = rendements.iloc[-(fenetre + 1):-1]
    moyenne        = historique.mean()
    ecart_type     = historique.std(ddof=1)
    if ecart_type == 0 or np.isnan(ecart_type):
        return None
    return float((rendement_jour - moyenne) / ecart_type)


def calculer_sma50(closes: pd.Series) -> dict:
    if len(closes) < 50:
        return {"sma50": None, "dessus_sma50": None}
    sma50       = float(closes.iloc[-50:].mean())
    prix_actuel = float(closes.iloc[-1])
    return {
        "sma50":        round(sma50, 4),
        "prix_actuel":  round(prix_actuel, 4),
        "dessus_sma50": prix_actuel >= sma50,
    }


def calculer_momentum_intraday(ticker: str) -> dict:
    data_5m = telecharger_intraday(ticker)
    if data_5m.empty or len(data_5m) < 2:
        return {"momentum_intraday_pct": None, "velocite_1h_pct": None, "source": "indisponible"}
    prix_ouverture = float(data_5m["Open"].iloc[0])
    prix_actuel    = float(data_5m["Close"].iloc[-1])
    momentum       = (prix_actuel - prix_ouverture) / prix_ouverture * 100
    n_bougies_1h   = min(12, len(data_5m))
    prix_1h_avant  = float(data_5m["Close"].iloc[-n_bougies_1h])
    velocite       = (prix_actuel - prix_1h_avant) / prix_1h_avant * 100
    return {
        "momentum_intraday_pct": round(momentum, 4),
        "velocite_1h_pct":       round(velocite, 4),
        "source":                "yfinance_5m",
    }


# ── Régime de marché ───────────────────────────────────────────────────────────

def determiner_regime_vix(vix: float | None) -> dict:
    if vix is None:
        return {"vix": None, "regime": "inconnu", "description": "VIX indisponible", "tag": "regime:inconnu"}
    if vix < VIX_RISK_ON:
        return {"vix": round(vix,2), "regime": "risk_on",
                "description": f"VIX {vix:.1f} < {VIX_RISK_ON} — opération normale",
                "tag": "regime:VIX_risk_on"}
    elif vix <= VIX_RISK_OFF:
        return {"vix": round(vix,2), "regime": "neutre",
                "description": f"VIX {vix:.1f} entre {VIX_RISK_ON}-{VIX_RISK_OFF} — tailles réduites",
                "tag": "regime:VIX_neutre"}
    else:
        return {"vix": round(vix,2), "regime": "risk_off",
                "description": f"VIX {vix:.1f} > {VIX_RISK_OFF} — pause ou signaux extrêmes seulement",
                "tag": "regime:VIX_risk_off"}


# ── Filtre D ───────────────────────────────────────────────────────────────────

def determiner_filtre_D(data: pd.DataFrame) -> dict:
    closes_xiu = extraire_closes(data, "XIU.TO")
    if len(closes_xiu) < 2:
        return {"xiu_rendement_pct": None, "contexte": "indisponible", "ajustement": "aucun"}
    rendement_xiu = float((closes_xiu.iloc[-1] - closes_xiu.iloc[-2]) / closes_xiu.iloc[-2] * 100)
    if rendement_xiu >= 0:
        return {"xiu_rendement_pct": round(rendement_xiu,4),
                "contexte": "XIU_stable_ou_positif", "ajustement": "seuil+0.5_taille÷1.5"}
    elif rendement_xiu < -0.5:
        return {"xiu_rendement_pct": round(rendement_xiu,4),
                "contexte": "XIU_en_baisse_systémique", "ajustement": "règles_normales"}
    else:
        return {"xiu_rendement_pct": round(rendement_xiu,4),
                "contexte": "zone_grise", "ajustement": "log_observation"}


# ── Cluster ────────────────────────────────────────────────────────────────────

def compter_cluster(signaux: list[dict]) -> dict:
    n = len(signaux)
    if n <= 3:
        return {"n_signaux": n, "action": "normal", "tag": "cluster:1_3"}
    elif n <= 6:
        return {"n_signaux": n, "action": "reduire_taille_50pct_et_seuil_2.5", "tag": "cluster:4_6"}
    else:
        return {"n_signaux": n, "action": "bloquer", "tag": "cluster:7+"}


# ── Calendrier BdC ─────────────────────────────────────────────────────────────

DATES_BDC_RPM      = {"2026-01-28", "2026-04-29", "2026-07-15", "2026-10-28"}
DATES_BDC_SANS_RPM = {"2026-03-18", "2026-06-10", "2026-09-02", "2026-12-09"}

def verifier_jour_bdc() -> dict:
    aujourd_hui = date.today().strftime("%Y-%m-%d")
    if aujourd_hui in DATES_BDC_RPM:
        return {"est_jour_bdc": True, "type_bdc": "RPM", "tag": "boc:RPM",
                "regle": "Attendre 10h00 HE. Seuil +0.5 é.-t. pour XRE, XUT, XFN, ZAG."}
    elif aujourd_hui in DATES_BDC_SANS_RPM:
        return {"est_jour_bdc": True, "type_bdc": "sans_RPM", "tag": "boc:sans_RPM",
                "regle": "Règles normales — ZAG tend à être positif ces jours."}
    else:
        return {"est_jour_bdc": False, "type_bdc": None, "tag": "boc:non_BdC", "regle": None}


# ── Taille de position ─────────────────────────────────────────────────────────

def calculer_multiplicateur_taille(
    ticker: str, z20: float, z60: float | None,
    regime: str, filtre_D: dict, dessus_sma50: bool | None, cluster_action: str,
) -> dict:
    cfg    = UNIVERSE[ticker]
    profil = cfg["profil"]
    # PRD v3.0 — section 7.2 : profils "rapide" (1.0x) et "moyen" (0.75x) uniquement
    base   = {"rapide": 1.00, "moyen": 0.75}[profil]
    az20   = abs(z20)
    if az20 >= 3.0:
        mult_signal, bucket_z20 = 2.0, "z20:≥3.0"
    elif az20 >= 2.5:
        mult_signal, bucket_z20 = 1.5, "z20:2.5-2.99"
    else:
        mult_signal, bucket_z20 = 1.0, "z20:2.0-2.49"
    taille      = base * mult_signal
    ajustements = []
    if regime == "neutre":
        taille /= 2; ajustements.append("régime_neutre÷2")
    if dessus_sma50 is False:
        taille /= 2; ajustements.append("sous_SMA50÷2")
    if z60 is not None and z60 > Z60_SEUIL_CONFIRMATION:
        taille /= 1.5; ajustements.append("z60_faible÷1.5")
    if filtre_D.get("ajustement") == "seuil+0.5_taille÷1.5":
        taille /= 1.5; ajustements.append("filtreD_XIU_stable÷1.5")
    if cluster_action == "reduire_taille_50pct_et_seuil_2.5":
        taille /= 2; ajustements.append("cluster_4_6÷2")
    tag_z60 = ("z60:N/A" if z60 is None
               else ("z60:confirmé" if z60 <= Z60_SEUIL_CONFIRMATION else "z60:faible"))
    return {"taille_finale": round(taille,4), "base_profil": base,
            "mult_signal": mult_signal, "ajustements": ajustements,
            "bucket_z20": bucket_z20, "tag_z60": tag_z60}


# ── Analyse FNB ────────────────────────────────────────────────────────────────

def analyser_fnb(ticker, data, regime_info, filtre_D, jour_bdc, mode,
                 contextuel: bool = False):
    """
    Analyse un FNB et retourne son résultat z-score.

    Si contextuel=True (UNIVERSE_CONTEXTUEL) : z-scores calculés mais
    signal mean reversion toujours False (PRD v3.0 — C1, section 5 Maillon 2).
    """
    if contextuel:
        cfg_source = UNIVERSE_CONTEXTUEL[ticker]
        profil_str = "contextuel"
        bloc_str   = cfg_source.get("bloc")
    else:
        cfg_source = UNIVERSE[ticker]
        profil_str = cfg_source["profil"]
        bloc_str   = cfg_source["bloc"]

    closes = extraire_closes(data, ticker)
    if closes.empty or len(closes) < WINDOW_COURT + 1:
        return {"ticker": ticker, "erreur": f"Données insuffisantes ({len(closes)} jours)",
                "signal": False, "contextuel": contextuel}
    rendements     = calculer_rendements(closes)
    z20            = calculer_zscore(rendements, WINDOW_COURT)
    z60            = calculer_zscore(rendements, WINDOW_MOYEN)
    sma_info       = calculer_sma50(closes)
    rendement_jour = float(rendements.iloc[-1]) if len(rendements) > 0 else None

    if contextuel:
        # Les contextuels n'ont pas de seuil mean reversion ni de signal
        seuil_effectif = cfg_source.get("seuil_contagion", 2.5)
        signal_actif   = False
        intraday       = {}
    else:
        seuil_effectif = cfg_source["seuil_min"]
        fnbs_taux      = {"XRE.TO", "XUT.TO", "XFN.TO"}
        if jour_bdc["type_bdc"] == "RPM" and ticker in fnbs_taux:
            seuil_effectif += 0.5
        if filtre_D.get("ajustement") == "seuil+0.5_taille÷1.5":
            seuil_effectif += 0.5
        signal_actif = z20 is not None and z20 <= -seuil_effectif
        intraday = {}
        if mode == "live" and signal_actif:
            intraday = calculer_momentum_intraday(ticker)

    tags = [jour_bdc["tag"], regime_info["tag"],
            f"bloc:{bloc_str or 'autre'}", f"profil:{profil_str}"]
    if contextuel:
        tags.append("role:contextuel")
    if z20 is not None:
        az20 = abs(z20)
        tags.append("z20:2.0-2.49" if az20 < 2.5 else ("z20:2.5-2.99" if az20 < 3.0 else "z20:≥3.0"))
    tags.append("z60:confirmé" if (z60 is not None and z60 <= Z60_SEUIL_CONFIRMATION)
                else ("z60:faible" if z60 is not None else "z60:N/A"))
    if sma_info["dessus_sma50"] is not None:
        tags.append("trend:SMA50_dessus" if sma_info["dessus_sma50"] else "trend:SMA50_sous")

    if contextuel:
        resultat = {
            "ticker":              ticker,
            "profil":              "contextuel",
            "contextuel":          True,
            "seuil_contagion":     seuil_effectif,
            "seuil_min_base":      seuil_effectif,   # compat. notifier.py
            "seuil_effectif":      seuil_effectif,
            "horizon_j":           None,
            "bloc":                bloc_str,
            "prix_cloture":        float(closes.iloc[-1]),
            "rendement_jour_pct":  round(rendement_jour * 100, 4) if rendement_jour else None,
            "z20":                 round(z20, 4) if z20 is not None else None,
            "z60":                 round(z60, 4) if z60 is not None else None,
            "sma50":               sma_info.get("sma50"),
            "dessus_sma50":        sma_info.get("dessus_sma50"),
            "signal":              False,   # jamais de signal mean reversion
            "tags":                tags,
        }
    else:
        resultat = {
            "ticker":              ticker,
            "profil":              profil_str,
            "contextuel":          False,
            "seuil_min_base":      cfg_source["seuil_min"],
            "seuil_effectif":      seuil_effectif,
            "horizon_j":           cfg_source["horizon_j"],
            "bloc":                bloc_str,
            "prix_cloture":        float(closes.iloc[-1]),
            "rendement_jour_pct":  round(rendement_jour * 100, 4) if rendement_jour else None,
            "z20":                 round(z20, 4) if z20 is not None else None,
            "z60":                 round(z60, 4) if z60 is not None else None,
            "sma50":               sma_info.get("sma50"),
            "dessus_sma50":        sma_info.get("dessus_sma50"),
            "signal":              signal_actif,
            "tags":                tags,
        }
        if intraday:
            resultat["intraday"] = intraday
    return resultat


# ── Signaux de contagion inter-FNB (PRD v3.0 — C3, section 5bis) ──────────────

# Définition des 5 signaux validés (PRD section 5bis)
# Format : (émetteur, seuil_déclencheur, cible, direction, niveau, description)
SIGNAUX_CONTAGION = [
    # S1 — XRE → XIN | Niveau 1 | p=0.000 | Prioritaire
    {
        "id":          "S1",
        "emetteur":    "XRE.TO",
        "seuil":       2.5,
        "cible":       "XIN.TO",
        "direction":   "long",
        "niveau":      1,
        "taille_base": 0.75,   # 75% de la position de base (Niveau 1)
        "deployer":    True,
        "description": "XRE chute ≥ 2.5 é.-t. → acheter XIN J+1",
    },
    # S2 — XEG → XFN | Niveau 2 | stabilité tridécennale | Phase 2
    {
        "id":          "S2",
        "emetteur":    "XEG.TO",
        "seuil":       2.5,
        "cible":       "XFN.TO",
        "direction":   "short",
        "niveau":      2,
        "taille_base": 0.50,   # 50% de la position de base (Niveau 2)
        "deployer":    True,
        "description": "XEG chute ≥ 2.5 é.-t. → shorter XFN J+1",
    },
    # S3 — XUT → XIN | Niveau 1 | p=0.002 | Surveiller érosion 2021-26
    {
        "id":          "S3",
        "emetteur":    "XUT.TO",
        "seuil":       2.5,
        "cible":       "XIN.TO",
        "direction":   "long",
        "niveau":      1,
        "taille_base": 0.75,
        "deployer":    True,
        "description": "XUT chute ≥ 2.5 é.-t. → acheter XIN J+1",
    },
    # S4 — XUT → XFN | Niveau 1 | p<0.001 | Phase 2
    {
        "id":          "S4",
        "emetteur":    "XUT.TO",
        "seuil":       2.5,
        "cible":       "XFN.TO",
        "direction":   "long",
        "niveau":      1,
        "taille_base": 0.75,
        "deployer":    True,
        "description": "XUT chute ≥ 2.5 é.-t. → acheter XFN J+1",
    },
    # S5 — XEG → XIU | Niveau 3 | n=14 — NE PAS DÉPLOYER
    {
        "id":          "S5",
        "emetteur":    "XEG.TO",
        "seuil":       3.0,
        "cible":       "XIU.TO",
        "direction":   "short",
        "niveau":      3,
        "taille_base": 0.0,    # Niveau 3 = ne pas déployer
        "deployer":    False,  # Bloqué jusqu'à 2 ans de validation out-of-sample
        "description": "XEG chute ≥ 3.0 é.-t. → shorter XIU J+1 (VEILLE — ne pas déployer)",
    },
]

FICHIER_CONTAGION_PENDING = Path("contagion_pending.json")


def detecter_signaux_contagion(
    resultats_actifs: list[dict],
    resultats_contextuels: list[dict],
    regime_info: dict,
) -> list[dict]:
    """
    Détecte les chocs sur les FNBs émetteurs (actifs ET contextuels) et génère
    des signaux de contagion conditionnels J+1.

    PRD v3.0 section 5bis :
      - Filtre : régime VIX Maillon 1 uniquement (pas les filtres A-G)
      - Niveau 3 → loggué mais déployer=False (ne pas ouvrir de position)
      - Résultat écrit dans contagion_pending.json pour lecture le lendemain matin
    """
    # Construire un index z20 par ticker (actifs + contextuels)
    z20_par_ticker: dict[str, float | None] = {}
    for r in resultats_actifs + resultats_contextuels:
        if not r.get("erreur"):
            z20_par_ticker[r["ticker"]] = r.get("z20")

    regime = regime_info.get("regime", "inconnu")
    maintenant = datetime.now(EASTERN)
    signaux_detectes = []

    for sig_def in SIGNAUX_CONTAGION:
        emetteur = sig_def["emetteur"]
        z20_em   = z20_par_ticker.get(emetteur)

        if z20_em is None:
            continue

        # Choc détecté si z20 de l'émetteur ≤ -seuil (baisse anormale)
        if z20_em > -sig_def["seuil"]:
            continue

        # Filtre régime VIX (Maillon 1 uniquement — PRD 5bis)
        if regime == "risk_off":
            print(f"   ⛔ Contagion {sig_def['id']} détecté mais bloqué — régime risk_off")
            continue

        # Ajustement taille régime neutre
        taille = sig_def["taille_base"]
        ajustements = []
        if regime == "neutre":
            taille /= 2
            ajustements.append("régime_neutre÷2")

        signal_contagion = {
            "id_signal":   sig_def["id"],
            "emetteur":    emetteur,
            "z20_emetteur": round(z20_em, 4),
            "seuil_declenche": sig_def["seuil"],
            "cible":       sig_def["cible"],
            "direction":   sig_def["direction"],
            "niveau":      sig_def["niveau"],
            "deployer":    sig_def["deployer"],
            "taille_finale": round(taille, 4),
            "ajustements": ajustements,
            "description": sig_def["description"],
            "regime_au_signal": regime,
            "date_signal": maintenant.date().isoformat(),
            "date_entree_cible": (maintenant.date() + timedelta(days=1)).isoformat(),
            "horizon_j":   1,       # entrée J+1 ouverture, sortie J+1 clôture
            "horizon_max_j": 4,     # max 1 + 3 jours additionnels si non profitable
            "type_signal": "contagion",
        }
        signaux_detectes.append(signal_contagion)

        emoji = "🔴" if not sig_def["deployer"] else ("🟡" if sig_def["niveau"] == 2 else "🟢")
        print(f"   {emoji} Contagion {sig_def['id']} : {emetteur} z20={z20_em:+.2f} "
              f"→ {sig_def['cible']} ({sig_def['direction'].upper()}) "
              f"taille={taille:.2f}x "
              f"{'[VEILLE — non déployé]' if not sig_def['deployer'] else ''}")

    return signaux_detectes


def ecrire_contagion_pending(signaux: list[dict]):
    """
    Persiste les signaux de contagion détectés dans contagion_pending.json.
    Ce fichier est lu le lendemain matin par simulateur.action_evaluer_contagion().
    """
    payload = {
        "genere_le":      datetime.now(EASTERN).isoformat(),
        "n_signaux":      len(signaux),
        "signaux":        signaux,
    }
    with open(FICHIER_CONTAGION_PENDING, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    print(f"   💾 {len(signaux)} signal(s) de contagion sauvegardé(s) → {FICHIER_CONTAGION_PENDING}")


# ── Rapport ────────────────────────────────────────────────────────────────────

def generer_rapport(resultats_actifs, resultats_contextuels,
                    regime_info, filtre_D, jour_bdc, cluster_info,
                    signaux_contagion=None):
    signaux = [r for r in resultats_actifs if r.get("signal")]
    for s in signaux:
        s["tags"].append(cluster_info["tag"])
    maintenant        = datetime.now(EASTERN)
    est_heures_marche = (
        maintenant.weekday() < 5
        and maintenant.hour >= 9
        and (maintenant.hour > 9 or maintenant.minute >= 30)
        and maintenant.hour < 16
    )
    tous_fnbs = resultats_actifs + resultats_contextuels
    return {
        "scan_at":           maintenant.isoformat(),
        "source_donnees":    "yfinance (source permanente — PRD v3.0)",
        "heures_marche":     est_heures_marche,
        "regime_marche":     regime_info,
        "filtre_D":          filtre_D,
        "jour_bdc":          jour_bdc,
        "cluster":           cluster_info,
        "n_fnbs_actifs":     len(resultats_actifs),
        "n_fnbs_contextuels": len(resultats_contextuels),
        "n_fnbs_scannes":    len(tous_fnbs),
        "n_signaux":         len(signaux),
        "signaux":           signaux,
        "tous_fnbs":         tous_fnbs,
        "signaux_contagion": signaux_contagion or [],
        "n_signaux_contagion": len(signaux_contagion or []),
    }


def afficher_console(rapport):
    now     = rapport["scan_at"][:19].replace("T", " ")
    regime  = rapport["regime_marche"]
    bdc     = rapport["jour_bdc"]
    cluster = rapport["cluster"]
    print("\n" + "=" * 65)
    print(f"  TMX v2 — Scan z-scores   {now}")
    print("=" * 65)
    icone_regime = {"risk_on": "🟢", "neutre": "🟡", "risk_off": "🔴"}.get(regime["regime"], "⚪")
    print(f"\n  {icone_regime} Régime VIX : {regime.get('description', 'inconnu')}")
    if bdc["est_jour_bdc"]:
        print(f"  ⚠️  Jour BdC ({bdc['type_bdc']}) : {bdc['regle']}")
    n = cluster["n_signaux"]
    if n == 0:
        print(f"\n  Aucun signal mean reversion sur les {rapport['n_fnbs_actifs']} FNBs actifs.")
    else:
        icone_cluster = "🟢" if n <= 3 else ("🟡" if n <= 6 else "🔴")
        print(f"\n  {icone_cluster} {n} signal(s) mean reversion — {cluster['action']}")
    if rapport["signaux"]:
        print(f"\n  {'FNB':<10} {'Profil':<8} {'Z20':>7} {'Z60':>7} {'SMA50':>8} {'Seuil':>7} {'Taille':>8}")
        print("  " + "-" * 58)
        for s in rapport["signaux"]:
            z20_str = f"{s['z20']:+.2f}" if s["z20"] is not None else "  N/A"
            z60_str = f"{s['z60']:+.2f}" if s["z60"] is not None else "  N/A"
            sma_str = "✓" if s.get("dessus_sma50") else ("✗" if s.get("dessus_sma50") is False else "?")
            taille_info = calculer_multiplicateur_taille(
                s["ticker"], s["z20"], s["z60"],
                rapport["regime_marche"]["regime"], rapport["filtre_D"],
                s.get("dessus_sma50"), cluster["action"],
            )
            print(f"  {s['ticker']:<10} {s['profil']:<8} {z20_str:>7} {z60_str:>7} "
                  f"{sma_str:>8} {s['seuil_effectif']:>7.1f} {taille_info['taille_finale']:.2f}x")

    # Tableau complet — actifs
    print(f"\n  ── FNBs actifs ({rapport['n_fnbs_actifs']}) ──")
    print(f"  {'FNB':<10} {'Z20':>7} {'Z60':>7} {'SMA50':>8} {'Prix':>8}")
    print("  " + "-" * 45)
    for r in rapport["tous_fnbs"]:
        if r.get("contextuel"):
            continue
        if r.get("erreur"):
            print(f"  {r['ticker']:<10} ERREUR"); continue
        z20_str  = f"{r['z20']:+.2f}" if r["z20"] is not None else "  N/A"
        z60_str  = f"{r['z60']:+.2f}" if r["z60"] is not None else "  N/A"
        sma_str  = "✓" if r.get("dessus_sma50") else ("✗" if r.get("dessus_sma50") is False else "?")
        prix_str = f"{r['prix_cloture']:.2f}" if r.get("prix_cloture") else "N/A"
        flag     = " ◄ SIGNAL" if r.get("signal") else ""
        print(f"  {r['ticker']:<10} {z20_str:>7} {z60_str:>7} {sma_str:>8} {prix_str:>8}{flag}")

    # Tableau contextuels
    print(f"\n  ── FNBs contextuels ({rapport['n_fnbs_contextuels']}) — z-scores de surveillance ──")
    print(f"  {'FNB':<10} {'Z20':>7} {'Z60':>7} {'Prix':>8}")
    print("  " + "-" * 36)
    for r in rapport["tous_fnbs"]:
        if not r.get("contextuel"):
            continue
        if r.get("erreur"):
            print(f"  {r['ticker']:<10} ERREUR"); continue
        z20_str  = f"{r['z20']:+.2f}" if r["z20"] is not None else "  N/A"
        z60_str  = f"{r['z60']:+.2f}" if r["z60"] is not None else "  N/A"
        prix_str = f"{r['prix_cloture']:.2f}" if r.get("prix_cloture") else "N/A"
        print(f"  {r['ticker']:<10} {z20_str:>7} {z60_str:>7} {prix_str:>8}")

    # Signaux de contagion détectés
    sc = rapport.get("signaux_contagion", [])
    if sc:
        print(f"\n  ── Signaux de contagion détectés : {len(sc)} ──")
        for s in sc:
            deployer_str = "→ EN ATTENTE J+1" if s["deployer"] else "→ VEILLE (non déployé)"
            print(f"  {s['id_signal']} {s['description']} {deployer_str}")
    else:
        print("\n  Aucun signal de contagion détecté.")

    print()


# ── Point d'entrée ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TMX v2 — Scanner z-scores")
    parser.add_argument("--mode", choices=["daily", "live"], default="daily")
    parser.add_argument("--output", default="scan_results.json")
    args, _ = parser.parse_known_args()

    print("=" * 65)
    print("  TMX v2 — Scanner de signaux z-scores  (PRD v3.0)")
    print(f"  Mode : {args.mode.upper()}")
    print("=" * 65)

    # ── Téléchargement des données (actifs + contextuels) ─────────────────────
    tickers_actifs      = list(UNIVERSE.keys())
    tickers_contextuels = list(UNIVERSE_CONTEXTUEL.keys())
    tous_tickers        = tickers_actifs + tickers_contextuels

    data = telecharger_historique(tous_tickers)

    # ── VIX + Régime ──────────────────────────────────────────────────────────
    print("\n📊 Récupération du VIX...")
    vix         = telecharger_vix()
    regime_info = determiner_regime_vix(vix)
    print(f"   {regime_info['description']}")

    filtre_D = determiner_filtre_D(data)
    print(f"\n🔍 Filtre D (XIU) : {filtre_D['contexte']} "
          f"(rendement : {filtre_D.get('xiu_rendement_pct', 'N/A')}%)")

    jour_bdc = verifier_jour_bdc()
    if jour_bdc["est_jour_bdc"]:
        print(f"\n⚠️  Jour BdC détecté : {jour_bdc['type_bdc']}")

    # ── Analyse — FNBs actifs ─────────────────────────────────────────────────
    print(f"\n🔎 Analyse des {len(tickers_actifs)} FNBs actifs...")
    resultats_actifs = []
    for ticker in tickers_actifs:
        r = analyser_fnb(ticker, data, regime_info, filtre_D, jour_bdc, args.mode,
                         contextuel=False)
        resultats_actifs.append(r)
        z20_str = f"{r['z20']:+.3f}" if r.get("z20") is not None else "N/A"
        z60_str = f"{r['z60']:+.3f}" if r.get("z60") is not None else "N/A"
        flag    = " ◄ SIGNAL" if r.get("signal") else ""
        print(f"   {ticker:<10} z20: {z20_str:>8}  z60: {z60_str:>8}{flag}")

    # ── Analyse — FNBs contextuels ────────────────────────────────────────────
    print(f"\n🔎 Analyse des {len(tickers_contextuels)} FNBs contextuels...")
    resultats_contextuels = []
    for ticker in tickers_contextuels:
        r = analyser_fnb(ticker, data, regime_info, filtre_D, jour_bdc, args.mode,
                         contextuel=True)
        resultats_contextuels.append(r)
        z20_str = f"{r['z20']:+.3f}" if r.get("z20") is not None else "N/A"
        z60_str = f"{r['z60']:+.3f}" if r.get("z60") is not None else "N/A"
        print(f"   {ticker:<10} z20: {z20_str:>8}  z60: {z60_str:>8}  [contextuel]")

    # ── Cluster (mean reversion uniquement) ───────────────────────────────────
    signaux_actifs = [r for r in resultats_actifs if r.get("signal")]
    cluster_info   = compter_cluster(signaux_actifs)

    # ── Signaux de contagion ──────────────────────────────────────────────────
    print("\n🔗 Détection des signaux de contagion...")
    signaux_contagion = detecter_signaux_contagion(
        resultats_actifs, resultats_contextuels, regime_info
    )
    if signaux_contagion:
        ecrire_contagion_pending(signaux_contagion)
    else:
        print("   Aucun signal de contagion détecté.")
        # Écrire un fichier vide pour signaler que le scan s'est bien exécuté
        ecrire_contagion_pending([])

    # ── Rapport + console ─────────────────────────────────────────────────────
    rapport = generer_rapport(
        resultats_actifs, resultats_contextuels,
        regime_info, filtre_D, jour_bdc, cluster_info,
        signaux_contagion,
    )
    afficher_console(rapport)

    output_path = Path(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(rapport, f, ensure_ascii=False, indent=2, default=str)
    print(f"  📄 Rapport sauvegardé : {output_path.resolve()}")

    # ── Notifications ──────────────────────────────────────────────────────────
    print("\n📬 Envoi des notifications...")
    try:
        from notifier import envoyer_notifications
        envoyer_notifications(rapport)
    except Exception as e:
        print(f"   ⚠️  Notifications : {e}")

    # ── Simulateur paper trading ───────────────────────────────────────────────
    print("\n📊 Mise à jour du simulateur paper trading...")
    try:
        from simulateur import (
            charger_positions, charger_trades_log,
            action_evaluer_contagion, action_evaluer, action_surveiller,
            sauvegarder_positions, sauvegarder_trades_log,
        )
        portefeuille = charger_positions()
        trades_log   = charger_trades_log()
        # 1. Contagion en premier (trades J+1 issus du scan précédent)
        action_evaluer_contagion(portefeuille, trades_log)
        # 2. Mean reversion (signaux du scan courant)
        action_evaluer(portefeuille, trades_log, 100_000.0)
        # 3. Surveillance des positions ouvertes
        action_surveiller(portefeuille, trades_log)
        sauvegarder_positions(portefeuille)
        sauvegarder_trades_log(trades_log)
        print("   ✅ Simulateur mis à jour")
    except Exception as e:
        print(f"   ⚠️  Simulateur : {e}")

    print()


if __name__ == "__main__":
    main()

