"""
TMX v2 — Agent de contexte news
Déclenché automatiquement par scanner.py quand z-score ≤ -2.

Flux :
  1. Charge la composition du FNB depuis etf_composition.json
  2. Fetch les flux RSS (Yahoo Finance + Google News) — sources gratuites
  3. Filtre les articles des dernières 24h pertinents pour ce FNB
  4. Appelle Groq (llama-3.3-70b) avec un prompt ciblé TMX v2
  5. Retourne un bloc texte HTML + une version SMS courte

Secrets GitHub requis :
  GROQ_API_KEY : clé API Groq (console.groq.com)

Usage depuis scanner.py :
  from news_agent import obtenir_contexte_news
  bloc_html, bloc_sms = obtenir_contexte_news(ticker, z20, rapport)
"""

import os
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────

GROQ_API_URL  = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL    = "llama-3.3-70b-versatile"
GROQ_MAX_TOKENS = 400

# Chemin vers le fichier de composition des FNBs
ETF_COMPOSITION_PATH = Path(__file__).parent / "etf_composition.json"

# Fenêtre temporelle pour les articles RSS (en heures)
FENETRE_HEURES = 24

# Nombre maximum d'articles à envoyer à Groq
MAX_ARTICLES = 12

# Délai entre les requêtes RSS (politesse)
DELAI_RSS_SEC = 1.0


# ── Chargement de la composition des FNBs ─────────────────────────────────────

def charger_composition(ticker: str) -> dict:
    """
    Charge les métadonnées du FNB depuis etf_composition.json.
    Retourne un dict vide si le ticker n'est pas trouvé.
    """
    try:
        with open(ETF_COMPOSITION_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get(ticker, {})
    except FileNotFoundError:
        print(f"   ⚠️  etf_composition.json introuvable — agent news désactivé.")
        return {}
    except json.JSONDecodeError as e:
        print(f"   ⚠️  Erreur lecture etf_composition.json : {e}")
        return {}


# ── Fetch RSS ──────────────────────────────────────────────────────────────────

def _fetch_rss(url: str, timeout: int = 8) -> list[dict]:
    """
    Télécharge et parse un flux RSS.
    Retourne une liste de { title, link, pubDate, source }.
    """
    try:
        headers = {
            "User-Agent": "TMX-v2-NewsAgent/1.0 (financial research bot)"
        }
        req  = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            contenu = resp.read()

        root = ET.fromstring(contenu)

        # Chercher les items dans le namespace standard ou Atom
        items = root.findall(".//item")
        if not items:
            items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

        articles = []
        for item in items:
            titre   = item.findtext("title", "") or \
                      item.findtext("{http://www.w3.org/2005/Atom}title", "")
            lien    = item.findtext("link", "") or \
                      item.findtext("{http://www.w3.org/2005/Atom}link", "")
            pub_date = item.findtext("pubDate", "") or \
                       item.findtext("{http://www.w3.org/2005/Atom}published", "")

            # Nettoyer le titre (enlever CDATA et espaces)
            titre = titre.strip().replace("\n", " ")

            if titre:
                articles.append({
                    "title":   titre,
                    "link":    lien.strip(),
                    "pubDate": pub_date.strip(),
                })

        return articles

    except urllib.error.URLError as e:
        print(f"   ⚠️  RSS inaccessible ({url[:60]}...) : {e.reason}")
        return []
    except ET.ParseError as e:
        print(f"   ⚠️  Erreur parsing RSS ({url[:60]}...) : {e}")
        return []
    except Exception as e:
        print(f"   ⚠️  Erreur inattendue RSS : {e}")
        return []


def _est_recent(pub_date_str: str, heures: int = FENETRE_HEURES) -> bool:
    """
    Vérifie si un article est publié dans les N dernières heures.
    Retourne True si la date est absente (on garde l'article par défaut).
    """
    if not pub_date_str:
        return True

    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
    ]

    for fmt in formats:
        try:
            pub = datetime.strptime(pub_date_str, fmt)
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            seuil = datetime.now(timezone.utc) - timedelta(hours=heures)
            return pub >= seuil
        except ValueError:
            continue

    # Format non reconnu — on garde l'article
    return True


def collecter_articles(composition: dict, ticker: str) -> list[str]:
    """
    Fetch les flux RSS pertinents pour ce FNB.
    Retourne une liste de titres d'articles récents.
    """
    mots_cles = composition.get("mots_cles_rss", [])
    if not mots_cles:
        mots_cles = [ticker, "Canadian stock market"]

    titres_collectes = []
    urls_fetched = set()

    for mot_cle in mots_cles[:4]:  # Max 4 requêtes RSS par FNB
        # Google News RSS (gratuit, pas de clé)
        query_encoded = urllib.parse.quote(mot_cle)
        url_google = (
            f"https://news.google.com/rss/search?"
            f"q={query_encoded}&hl=en-CA&gl=CA&ceid=CA:en"
        )

        if url_google not in urls_fetched:
            articles = _fetch_rss(url_google)
            urls_fetched.add(url_google)

            for art in articles:
                if _est_recent(art["pubDate"]) and art["title"]:
                    titres_collectes.append(art["title"])

            time.sleep(DELAI_RSS_SEC)

    # Yahoo Finance RSS pour le ticker spécifique
    ticker_clean = ticker.replace(".TO", "")
    url_yahoo = f"https://finance.yahoo.com/rss/headline?s={ticker_clean}.TO"

    if url_yahoo not in urls_fetched:
        articles_yahoo = _fetch_rss(url_yahoo)
        for art in articles_yahoo:
            if _est_recent(art["pubDate"]) and art["title"]:
                titres_collectes.append(art["title"])

    # Déduplications et nettoyage
    titres_uniques = list(dict.fromkeys(titres_collectes))

    print(f"   📰 {len(titres_uniques)} articles RSS collectés pour {ticker}")
    return titres_uniques[:MAX_ARTICLES]


# ── Appel Groq ────────────────────────────────────────────────────────────────

def _construire_prompt(
    ticker: str,
    z20: float,
    composition: dict,
    titres_articles: list[str],
    regime: str,
) -> str:
    """
    Construit le prompt envoyé à Groq.
    Ciblé sur la classification TMX v2 : SECTORIEL / FONDAMENTAL / SYSTÉMIQUE.
    """
    nom_fnb        = composition.get("nom", ticker)
    secteur        = composition.get("secteur", "inconnu")
    verdict_hist   = composition.get("classification_historique", {})
    pct_sectoriel  = verdict_hist.get("sectoriel_pct", "?")
    pct_fondamental = verdict_hist.get("fondamental_pct", "?")
    risque_fond    = composition.get("risque_fondamental", "inconnu")

    holdings = composition.get("holdings", [])
    titres_lourds = ", ".join(
        f"{h['nom']} ({h['poids_pct']}%)"
        for h in holdings[:3]
    ) if holdings else "composition inconnue"

    articles_str = "\n".join(f"- {t}" for t in titres_articles) \
                   if titres_articles else "Aucun article trouvé dans les dernières 24h."

    prompt = f"""Tu es un analyste financier spécialisé dans les FNBs canadiens (TSX).

CONTEXTE DU SIGNAL TMX v2 :
- FNB : {ticker} — {nom_fnb}
- Secteur : {secteur}
- Z-score actuel : {z20:+.2f} (seuil = -2.0 é.-t.)
- Titres lourds : {titres_lourds}
- Régime VIX : {regime}
- Historique : {pct_sectoriel}% des baisses passées sont SECTORIELLES, {pct_fondamental}% FONDAMENTALES
- Risque fondamental historique : {risque_fond}

ACTUALITÉS DES DERNIÈRES 24H (titres RSS) :
{articles_str}

TA TÂCHE :
1. Identifie la cause PROBABLE de cette baisse de {z20:+.2f} é.-t. parmi :
   - SECTORIEL : réaction de tout le secteur (prix pétrole, taux, rotation)
   - FONDAMENTAL : mauvaise nouvelle sur un titre lourd spécifique (résultats, annonce)
   - SYSTÉMIQUE : crise générale de marché (mais peu probable si tu es appelé ici)

2. Résume en EXACTEMENT 3-4 phrases courtes en français :
   - Quelle est la cause probable ?
   - Quel(s) titre(s) ou facteur(s) macro expliquer la baisse ?
   - Est-ce un choc temporaire ou potentiellement persistant ?

3. Termine par une ligne : "Verdict : [SECTORIEL/FONDAMENTAL/SYSTÉMIQUE] — [rebond probable/prudence/déjà bloqué]"

IMPORTANT : Sois concis et factuel. Pas de conseils d'investissement. Maximum 100 mots."""

    return prompt


def appeler_groq(prompt: str) -> str | None:
    """
    Envoie le prompt à l'API Groq et retourne le texte généré.
    """
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        print("   ⚠️  GROQ_API_KEY absente — analyse news désactivée.")
        return None

    payload = json.dumps({
        "model": GROQ_MODEL,
        "max_tokens": GROQ_MAX_TOKENS,
        "temperature": 0.2,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }).encode("utf-8")

    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {groq_key}",
    }

    try:
        req  = urllib.request.Request(GROQ_API_URL, data=payload, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        return data["choices"][0]["message"]["content"].strip()

    except urllib.error.HTTPError as e:
        corps = e.read().decode("utf-8", errors="replace")
        print(f"   ❌ Groq HTTP {e.code} : {corps[:200]}")
        return None
    except Exception as e:
        print(f"   ❌ Erreur Groq : {e}")
        return None


# ── Construction des blocs de sortie ──────────────────────────────────────────

def _extraire_verdict(texte_groq: str) -> tuple[str, str]:
    """
    Extrait le type (SECTORIEL/FONDAMENTAL/SYSTÉMIQUE) et l'action
    depuis la réponse Groq.
    Retourne (type_baisse, couleur_hex).
    """
    texte_upper = texte_groq.upper()

    if "FONDAMENTAL" in texte_upper:
        return "FONDAMENTAL", "#ef4444"
    elif "SYSTÉMIQUE" in texte_upper or "SYSTEMIQUE" in texte_upper:
        return "SYSTÉMIQUE", "#6b7280"
    else:
        return "SECTORIEL", "#f59e0b"


def _construire_bloc_html(
    ticker: str,
    z20: float,
    texte_groq: str,
    type_baisse: str,
    couleur: str,
    n_articles: int,
) -> str:
    """Génère le bloc HTML à injecter dans le courriel notifier.py."""

    icone_verdict = {
        "SECTORIEL":   "🟡",
        "FONDAMENTAL": "🔴",
        "SYSTÉMIQUE":  "⚫",
    }.get(type_baisse, "⚪")

    action_verdict = {
        "SECTORIEL":   "Rebond probable — signal fiable pour TMX v2",
        "FONDAMENTAL": "⚠️ Prudence — vérifier les nouvelles avant d'agir",
        "SYSTÉMIQUE":  "Géré par les filtres cluster/VIX du scanner",
    }.get(type_baisse, "")

    # Échapper les caractères HTML dans le texte Groq
    texte_safe = texte_groq \
        .replace("&", "&amp;") \
        .replace("<", "&lt;") \
        .replace(">", "&gt;")

    return f"""
    <div style="background:#0d1117;border:1px solid {couleur}40;border-left:4px solid {couleur};
                border-radius:0 6px 6px 0;padding:14px 16px;margin-top:12px;font-size:13px;">

      <div style="display:flex;justify-content:space-between;align-items:center;
                  margin-bottom:10px;">
        <div>
          <span style="font-family:monospace;font-weight:700;color:{couleur};font-size:14px;">
            {icone_verdict} CONTEXTE NEWS — {ticker} (z = {z20:+.2f})
          </span>
        </div>
        <span style="background:{couleur}20;border:1px solid {couleur}40;color:{couleur};
                     font-size:11px;padding:2px 8px;border-radius:4px;font-family:monospace;">
          {type_baisse}
        </span>
      </div>

      <div style="color:#cbd5e1;line-height:1.65;margin-bottom:10px;">
        {texte_safe}
      </div>

      <div style="background:{couleur}10;border:1px solid {couleur}25;border-radius:4px;
                  padding:6px 10px;font-size:11px;color:{couleur};">
        {action_verdict}
      </div>

      <div style="margin-top:8px;font-size:10px;color:#475569;">
        Source : Yahoo Finance RSS + Google News · {n_articles} articles analysés ·
        Classifié par Groq llama-3.3-70b
      </div>

    </div>
    """


def _construire_bloc_sms(
    ticker: str,
    z20: float,
    type_baisse: str,
    texte_groq: str,
) -> str:
    """Génère la version ultra-courte pour SMS (160 caractères max)."""

    # Extraire la première phrase significative
    lignes = [l.strip() for l in texte_groq.split("\n") if l.strip()]
    premiere_phrase = lignes[0][:80] if lignes else "Voir courriel."

    icones = {"SECTORIEL": "🟡", "FONDAMENTAL": "🔴", "SYSTÉMIQUE": "⚫"}
    icone  = icones.get(type_baisse, "⚪")

    msg = f"{icone}{type_baisse[:5]} {ticker} z={z20:+.1f} | {premiere_phrase}"
    return msg[:160]


# ── Point d'entrée principal ───────────────────────────────────────────────────

def obtenir_contexte_news(
    ticker: str,
    z20: float,
    rapport: dict,
) -> tuple[str, str]:
    """
    Point d'entrée appelé depuis scanner.py.

    Paramètres :
      ticker  : ex. "XEG.TO"
      z20     : z-score 20j du signal (valeur négative)
      rapport : dict complet généré par generer_rapport() dans scanner.py

    Retourne :
      (bloc_html, bloc_sms) — à injecter dans notifier.py
      En cas d'erreur, retourne deux chaînes vides.
    """
    print(f"\n   🔍 Agent news → {ticker} (z = {z20:+.2f})")

    regime = rapport.get("regime_marche", {}).get("regime", "inconnu")

    # 1. Charger la composition
    composition = charger_composition(ticker)
    if not composition:
        print(f"   ⚠️  Composition de {ticker} introuvable — analyse news ignorée.")
        return "", ""

    verdict_hist = composition.get("classification_historique", {})
    print(f"   📊 Historique : {verdict_hist.get('sectoriel_pct', '?')}% sectoriel, "
          f"{verdict_hist.get('fondamental_pct', '?')}% fondamental")

    # 2. Fetch RSS
    titres_articles = collecter_articles(composition, ticker)

    # 3. Appel Groq
    print(f"   🤖 Envoi à Groq ({GROQ_MODEL})...")
    prompt = _construire_prompt(ticker, z20, composition, titres_articles, regime)
    texte_groq = appeler_groq(prompt)

    if not texte_groq:
        # Fallback : bloc basé sur l'historique uniquement, sans Groq
        pct_s = verdict_hist.get("sectoriel_pct", 0)
        type_baisse = "SECTORIEL" if pct_s >= 60 else "FONDAMENTAL"
        couleur     = "#f59e0b" if type_baisse == "SECTORIEL" else "#ef4444"
        texte_groq  = (
            f"Analyse Groq indisponible. "
            f"Sur la base des données historiques ({pct_s}% sectoriel), "
            f"la baisse de {ticker} est probablement {type_baisse.lower()}. "
            f"Verdict : {type_baisse} — consulter les nouvelles manuellement."
        )
        print(f"   ⚠️  Fallback historique utilisé.")
    else:
        print(f"   ✅ Groq : réponse reçue ({len(texte_groq)} caractères)")

    # 4. Extraire le verdict et construire les blocs
    type_baisse, couleur = _extraire_verdict(texte_groq)

    bloc_html = _construire_bloc_html(
        ticker, z20, texte_groq, type_baisse, couleur, len(titres_articles)
    )
    bloc_sms = _construire_bloc_sms(ticker, z20, type_baisse, texte_groq)

    print(f"   ✅ Verdict : {type_baisse}")

    return bloc_html, bloc_sms
