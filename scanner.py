"""
TMX v2 — Scanner de signaux z-scores  [PRD v3.0]
Calcul des z-scores 20j et 60j sur 12 FNBs (7 actifs + 5 contextuels)

Source de données : yfinance (source unique permanente)
                   Questrade abandonné définitivement (Cloudflare + termes API)

Univers actif (7 FNBs) : XIU, XFN, XUT, XRE, XIN, XHC, XST
Univers contextuel (5 FNBs) : XEG, ZAG, XGD, XIT, XMA
  → z-scores calculés mais aucun signal mean reversion généré
  → chocs ≥ 2,5 é.-t. transmis au module de contagion (contagion.py)

Secrets GitHub requis :
  GH_PAT : Personal Access Token GitHub (scope: repo) — pour les mises à jour du dashboard
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

# ── Univers de trading actif — signaux mean reversion validés (Wilcoxon, 25 ans) ──
# Horizons horizon_j corrigés PRD v3.0 (Wilcoxon) vs v2.2 :
#   XIU : 10 → 20  |  XFN : 15 → 20  |  XUT : 10 → 20 (marginal)
#   XRE : 25 → 20  |  XHC : 15 → 10  |  XST : 10 → 15  |  XIN : 10 ✓ confirmé
# Profils : "rapide" (≤15j) / "moyen" (20j) — profil "lent" retiré (aucun FNB lent actif)
# Blocs : "marche_large" {XIU, XFN, XIN} | "taux" {XRE, XUT} — bloc "metaux" retiré
UNIVERSE_ACTIF = {
    "XIU.TO": {"profil": "moyen",  "seuil_min": 2.0, "horizon_j": 20, "bloc": "marche_large"},
    "XFN.TO": {"profil": "moyen",  "seuil_min": 2.0, "horizon_j": 20, "bloc": "marche_large"},
    "XUT.TO": {"profil": "moyen",  "seuil_min": 2.0, "horizon_j": 20, "bloc": "taux"},
    "XRE.TO": {"profil": "moyen",  "seuil_min": 2.0, "horizon_j": 20, "bloc": "taux"},
    "XIN.TO": {"profil": "rapide", "seuil_min": 2.0, "horizon_j": 10, "bloc": "marche_large"},
    "XHC.TO": {"profil": "rapide", "seuil_min": 2.0, "horizon_j": 10, "bloc": None},
    "XST.TO": {"profil": "rapide", "seuil_min": 2.0, "horizon_j": 15, "bloc": None},
}

# ── Univers contextuel — z-scores calculés, aucun signal mean reversion ──────────
# Ces FNBs n'ont pas de signal Wilcoxon validé (ou sont fondamentalement biaisés).
# Leurs chocs ≥ 2,5 é.-t. alimentent les signaux de contagion (contagion.py).
#   XEG : émetteur contagion vers XFN (S2) et XIU (S5)
#   XRE_ctx → non : XRE est actif; XUT : émetteur contagion vers XIN (S3) et XFN (S4)
#   XIT : 87 % baisses fondamentales (Shopify) — pas de rebond systématique
#   XGD, XMA : aucun signal Wilcoxon validé
#   ZAG : baromètre taux — aucun signal mean reversion validé
UNIVERSE_CONTEXTUEL = {
    "XEG.TO": {"profil": None, "seuil_min": None, "horizon_j": None, "bloc": None},
    "ZAG.TO": {"profil": None, "seuil_min": None, "horizon_j": None, "bloc": "taux"},
    "XGD.TO": {"profil": None, "seuil_min": None, "horizon_j": None, "bloc": "metaux"},
    "XIT.TO": {"profil": None, "seuil_min": None, "horizon_j": None, "bloc": None},
    "XMA.TO": {"profil": None, "seuil_min": None, "horizon_j": None, "bloc": "metaux"},
}

# ── UNIVERSE — fusion pour compatibilité (iteration, téléchargement, dashboard) ─
UNIVERSE = {**UNIVERSE_ACTIF, **UNIVERSE_CONTEXTUEL}

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
    return data


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
    # Profil "lent" retiré en v3.0 — aucun FNB actif n'a ce profil
    # Les FNBs contextuels ne doivent jamais atteindre ce calcul
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

def analyser_fnb(ticker, data, regime_info, filtre_D, jour_bdc, mode):
    cfg    = UNIVERSE[ticker]
    est_contextuel = ticker in UNIVERSE_CONTEXTUEL
    closes = extraire_closes(data, ticker)
    if closes.empty or len(closes) < WINDOW_COURT + 1:
        return {"ticker": ticker, "erreur": f"Données insuffisantes ({len(closes)} jours)",
                "signal": False, "role": "contextuel" if est_contextuel else "actif"}
    rendements     = calculer_rendements(closes)
    z20            = calculer_zscore(rendements, WINDOW_COURT)
    z60            = calculer_zscore(rendements, WINDOW_MOYEN)
    sma_info       = calculer_sma50(closes)
    rendement_jour = float(rendements.iloc[-1]) if len(rendements) > 0 else None

    # ── FNB contextuel : z-scores calculés, signal mean reversion toujours False ──
    if est_contextuel:
        choc_contagion = z20 is not None and z20 <= -2.5
        return {
            "ticker":            ticker,
            "role":              "contextuel",
            "profil":            None,
            "seuil_min_base":    None,
            "seuil_effectif":    None,
            "horizon_j":         None,
            "bloc":              cfg["bloc"],
            "prix_cloture":      float(closes.iloc[-1]),
            "rendement_jour_pct": round(rendement_jour * 100, 4) if rendement_jour else None,
            "z20":               round(z20, 4) if z20 is not None else None,
            "z60":               round(z60, 4) if z60 is not None else None,
            "sma50":             sma_info.get("sma50"),
            "dessus_sma50":      sma_info.get("dessus_sma50"),
            "signal":            False,
            "choc_contagion":    choc_contagion,  # transmis à contagion.py (Phase 2)
            "tags":              [f"role:contextuel", f"bloc:{cfg['bloc'] or 'autre'}",
                                  "choc_contagion:oui" if choc_contagion else "choc_contagion:non"],
        }
    if closes.empty or len(closes) < WINDOW_COURT + 1:
        return {"ticker": ticker, "erreur": f"Données insuffisantes ({len(closes)} jours)", "signal": False}
    rendements     = calculer_rendements(closes)
    z20            = calculer_zscore(rendements, WINDOW_COURT)
    z60            = calculer_zscore(rendements, WINDOW_MOYEN)
    sma_info       = calculer_sma50(closes)
    rendement_jour = float(rendements.iloc[-1]) if len(rendements) > 0 else None
    seuil_effectif = cfg["seuil_min"]
    fnbs_taux      = {"XRE.TO", "XUT.TO", "XFN.TO"}  # ZAG retiré (contextuel en v3.0)
    if jour_bdc["type_bdc"] == "RPM" and ticker in fnbs_taux:
        seuil_effectif += 0.5
    if filtre_D.get("ajustement") == "seuil+0.5_taille÷1.5":
        seuil_effectif += 0.5
    signal_actif = z20 is not None and z20 <= -seuil_effectif
    intraday = {}
    if mode == "live" and signal_actif:
        intraday = calculer_momentum_intraday(ticker)
    tags = [jour_bdc["tag"], regime_info["tag"],
            f"bloc:{cfg['bloc'] or 'autre'}", f"profil:{cfg['profil']}"]
    if z20 is not None:
        az20 = abs(z20)
        tags.append("z20:2.0-2.49" if az20 < 2.5 else ("z20:2.5-2.99" if az20 < 3.0 else "z20:≥3.0"))
    tags.append("z60:confirmé" if (z60 is not None and z60 <= Z60_SEUIL_CONFIRMATION)
                else ("z60:faible" if z60 is not None else "z60:N/A"))
    if sma_info["dessus_sma50"] is not None:
        tags.append("trend:SMA50_dessus" if sma_info["dessus_sma50"] else "trend:SMA50_sous")
    resultat = {
        "ticker": ticker, "role": "actif", "profil": cfg["profil"],
        "seuil_min_base": cfg["seuil_min"], "seuil_effectif": seuil_effectif,
        "horizon_j": cfg["horizon_j"], "bloc": cfg["bloc"],
        "prix_cloture": float(closes.iloc[-1]),
        "rendement_jour_pct": round(rendement_jour * 100, 4) if rendement_jour else None,
        "z20": round(z20, 4) if z20 is not None else None,
        "z60": round(z60, 4) if z60 is not None else None,
        "sma50": sma_info.get("sma50"), "dessus_sma50": sma_info.get("dessus_sma50"),
        "signal": signal_actif, "tags": tags,
    }
    if intraday:
        resultat["intraday"] = intraday
    return resultat


# ── Rapport ────────────────────────────────────────────────────────────────────

def generer_rapport(resultats, regime_info, filtre_D, jour_bdc, cluster_info):
    signaux = [r for r in resultats if r.get("signal")]
    for s in signaux:
        s["tags"].append(cluster_info["tag"])
    maintenant        = datetime.now(EASTERN)
    est_heures_marche = (
        maintenant.weekday() < 5
        and maintenant.hour >= 9
        and (maintenant.hour > 9 or maintenant.minute >= 30)
        and maintenant.hour < 16
    )
    return {
        "scan_at": maintenant.isoformat(),
        "source_donnees": "yfinance (source unique permanente — PRD v3.0)",
        "heures_marche": est_heures_marche,
        "regime_marche": regime_info, "filtre_D": filtre_D,
        "jour_bdc": jour_bdc, "cluster": cluster_info,
        "n_fnbs_scannes": len(resultats), "n_signaux": len(signaux),
        "signaux": signaux, "tous_fnbs": resultats,
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
        print(f"\n  Aucun signal actif sur les {rapport['n_fnbs_scannes']} FNBs scannés.")
    else:
        icone_cluster = "🟢" if n <= 3 else ("🟡" if n <= 6 else "🔴")
        print(f"\n  {icone_cluster} {n} signal(s) — {cluster['action']}")
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
    print(f"\n  {'':2}{'FNB':<10} {'Rôle':<5} {'Z20':>7} {'Z60':>7} {'SMA50':>8} {'Prix':>8}")
    print("  " + "-" * 50)
    for r in rapport["tous_fnbs"]:
        if r.get("erreur"):
            role_str = "[C]" if r.get("role") == "contextuel" else "[A]"
            print(f"  {role_str} {r['ticker']:<10} ERREUR"); continue
        z20_str  = f"{r['z20']:+.2f}" if r["z20"] is not None else "  N/A"
        z60_str  = f"{r['z60']:+.2f}" if r["z60"] is not None else "  N/A"
        sma_str  = "✓" if r.get("dessus_sma50") else ("✗" if r.get("dessus_sma50") is False else "?")
        prix_str = f"{r['prix_cloture']:.2f}" if r.get("prix_cloture") else "N/A"
        role_str = "[C]" if r.get("role") == "contextuel" else "[A]"
        flag     = " ◄ SIGNAL" if r.get("signal") else ""
        contagion_flag = " ◄ CHOC CONTAGION" if r.get("choc_contagion") else ""
        print(f"  {role_str} {r['ticker']:<10} {z20_str:>7} {z60_str:>7} {sma_str:>8} {prix_str:>8}{flag}{contagion_flag}")
    print()


# ── Point d'entrée ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TMX v2 — Scanner z-scores")
    parser.add_argument("--mode", choices=["daily", "live"], default="daily")
    parser.add_argument("--output", default="scan_results.json")
    args, _ = parser.parse_known_args()

    print("=" * 65)
    print("  TMX v2 — Scanner de signaux z-scores")
    print(f"  Mode : {args.mode.upper()}")
    print("=" * 65)

    tickers = list(UNIVERSE.keys())
    data    = telecharger_historique(tickers)

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

    print(f"\n🔎 Analyse des {len(tickers)} FNBs ({len(UNIVERSE_ACTIF)} actifs [A] + {len(UNIVERSE_CONTEXTUEL)} contextuels [C])...")
    resultats = []
    for ticker in tickers:
        r = analyser_fnb(ticker, data, regime_info, filtre_D, jour_bdc, args.mode)
        resultats.append(r)
        z20_str  = f"{r['z20']:+.3f}" if r.get("z20") is not None else "N/A"
        z60_str  = f"{r['z60']:+.3f}" if r.get("z60") is not None else "N/A"
        role_str = "[C]" if r.get("role") == "contextuel" else "[A]"
        flag     = " ◄ SIGNAL" if r.get("signal") else ""
        contagion_flag = " ◄ CHOC CONTAGION" if r.get("choc_contagion") else ""
        print(f"   {role_str} {ticker:<10} z20: {z20_str:>8}  z60: {z60_str:>8}{flag}{contagion_flag}")

    signaux_actifs = [r for r in resultats if r.get("signal")]
    cluster_info   = compter_cluster(signaux_actifs)
    rapport        = generer_rapport(resultats, regime_info, filtre_D, jour_bdc, cluster_info)
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
            action_evaluer, action_surveiller,
            sauvegarder_positions, sauvegarder_trades_log,
        )
        portefeuille = charger_positions()
        trades_log   = charger_trades_log()
        action_evaluer(portefeuille, trades_log, 100_000.0)
        action_surveiller(portefeuille, trades_log)
        sauvegarder_positions(portefeuille)
        sauvegarder_trades_log(trades_log)
        print("   ✅ Simulateur mis à jour")
    except Exception as e:
        print(f"   ⚠️  Simulateur : {e}")

    print()


if __name__ == "__main__":
    main()
