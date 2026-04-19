"""
TMX v2 — Module de notification
Envoie un courriel HTML + SMS quand un signal z-score est détecté.

Secrets GitHub requis :
  GMAIL_USER          : adresse Gmail expéditrice
  GMAIL_APP_PASSWORD  : mot de passe d'application Google (16 caractères)
  NOTIF_EMAIL_1       : destinataire courriel 1
  NOTIF_EMAIL_2       : destinataire courriel 2
  NOTIF_SMS_ROGERS    : {numero}@pcs.rogers.com
  NOTIF_SMS_TELUS     : {numero}@msg.telus.com

Usage (appelé depuis scanner.py) :
  from notifier import envoyer_notifications
  envoyer_notifications(rapport)
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/Toronto")

# ── Constantes PRD (dupliquées ici pour éviter import circulaire) ──────────────

Z60_SEUIL_CONFIRMATION = -1.5

# PRD v3.0 — 7 FNBs actifs uniquement.
# XEG, ZAG, XGD, XIT, XMA retirés (indicateurs contextuels, sans profil de trading).
UNIVERSE_PROFILS = {
    "XIU.TO": {"profil": "moyen"},
    "XFN.TO": {"profil": "moyen"},
    "XUT.TO": {"profil": "moyen"},
    "XRE.TO": {"profil": "moyen"},
    "XIN.TO": {"profil": "rapide"},
    "XHC.TO": {"profil": "rapide"},
    "XST.TO": {"profil": "rapide"},
}


# ── Calcul de taille (autonome, sans dépendance à scanner.py) ─────────────────

def _calculer_taille(
    ticker: str,
    z20: float,
    z60: float | None,
    regime: str,
    filtre_D: dict,
    dessus_sma50: bool | None,
    cluster_action: str,
) -> float:
    """
    Reproduit la logique de calculer_multiplicateur_taille de scanner.py.
    Maintenu ici pour éviter l'import circulaire.
    PRD sections 7.1, 7.2, 7.3.
    """
    profil = UNIVERSE_PROFILS.get(ticker, {}).get("profil", "moyen")
    base = {"rapide": 1.00, "moyen": 0.75, "lent": 0.50}[profil]

    az20 = abs(z20)
    if az20 >= 3.0:
        mult_signal = 2.0
    elif az20 >= 2.5:
        mult_signal = 1.5
    else:
        mult_signal = 1.0

    taille = base * mult_signal

    if regime == "neutre":
        taille /= 2
    if dessus_sma50 is False:
        taille /= 2
    if z60 is not None and z60 > Z60_SEUIL_CONFIRMATION:
        taille /= 1.5
    if filtre_D.get("ajustement") == "seuil+0.5_taille÷1.5":
        taille /= 1.5
    if cluster_action == "reduire_taille_50pct_et_seuil_2.5":
        taille /= 2

    return round(taille, 4)


# ── Bloc contagion HTML ───────────────────────────────────────────────────────

def _construire_bloc_contagion(rapport: dict) -> str:
    """
    Génère un bloc HTML listant les signaux de contagion détectés.
    Retourne une chaîne vide si rapport["signaux_contagion"] est absent ou vide.
    Champs attendus par signal : ticker (émetteur), type_signal, seuil_contagion,
    cible (optionnel), taille (optionnel).
    """
    signaux_c = rapport.get("signaux_contagion", [])
    if not signaux_c:
        return ""

    lignes = ""
    for sc in signaux_c:
        emetteur  = sc.get("ticker", "?")
        type_sig  = sc.get("type_signal", "?")
        seuil_c   = sc.get("seuil_contagion", "?")
        cible     = sc.get("cible", "—")
        taille    = sc.get("taille")
        taille_str = f"{taille:.2f}x" if taille is not None else "—"

        lignes += f"""
        <tr>
          <td style="padding:8px;font-weight:bold;">{emetteur}</td>
          <td style="padding:8px;">{type_sig}</td>
          <td style="padding:8px;text-align:center;">{seuil_c}</td>
          <td style="padding:8px;text-align:center;">{cible}</td>
          <td style="padding:8px;text-align:center;font-weight:bold;">{taille_str}</td>
        </tr>"""

    return f"""
      <div style="background:#fef9e7;padding:10px 16px 0;
                  border:1px solid #f9e79f;margin-top:8px;">
        <p style="margin:0 0 6px;font-size:13px;font-weight:bold;color:#7d6608;">
          ⚡ Signaux de contagion détectés
        </p>
        <table width="100%" cellspacing="0"
               style="border-collapse:collapse;font-size:13px;">
          <thead>
            <tr style="background:#f7dc6f;color:#333;">
              <th style="padding:7px;text-align:left;">Émetteur</th>
              <th style="padding:7px;">Type</th>
              <th style="padding:7px;">Seuil</th>
              <th style="padding:7px;">Cible</th>
              <th style="padding:7px;">Taille</th>
            </tr>
          </thead>
          <tbody>{lignes}</tbody>
        </table>
        <p style="font-size:11px;color:#999;margin:6px 0 8px;">
          Signal de contagion — surveiller uniquement, pas d'action automatique.
        </p>
      </div>"""


# ── Construction du courriel HTML ─────────────────────────────────────────────

def _construire_courriel_html(rapport: dict, blocs_news: dict | None = None) -> str:
    """Génère le corps HTML formaté du courriel d'alerte TMX v2."""

    now     = rapport["scan_at"][:19].replace("T", " ")
    regime  = rapport["regime_marche"]
    cluster = rapport["cluster"]
    bdc     = rapport["jour_bdc"]
    signaux = rapport["signaux"]

    icone_regime = {
        "risk_on":  "🟢",
        "neutre":   "🟡",
        "risk_off": "🔴",
    }.get(regime["regime"], "⚪")

    icone_cluster = "🟢" if cluster["n_signaux"] <= 3 else "🟡"

    # Bloc avertissement BdC
    bloc_bdc = ""
    if bdc["est_jour_bdc"]:
        bloc_bdc = f"""
        <tr>
          <td colspan="7" style="background:#fff3cd;padding:10px;
              border-left:4px solid #ffc107;font-size:13px;">
            ⚠️ <strong>Jour BdC ({bdc['type_bdc']})</strong> — {bdc['regle']}
          </td>
        </tr>"""

    # Lignes de signaux
    lignes_signaux = ""
    for s in signaux:
        z20_str = f"{s['z20']:+.2f}" if s.get("z20") is not None else "N/A"
        z60_str = f"{s['z60']:+.2f}" if s.get("z60") is not None else "N/A"
        sma_str = "✓" if s.get("dessus_sma50") else (
                  "✗" if s.get("dessus_sma50") is False else "?")

        couleur_z20 = "#c0392b" if (
            s.get("z20") is not None and s["z20"] <= -3.0
        ) else "#e67e22"

        taille = _calculer_taille(
            s["ticker"],
            s["z20"],
            s.get("z60"),
            regime["regime"],
            rapport["filtre_D"],
            s.get("dessus_sma50"),
            cluster["action"],
        )

        lignes_signaux += f"""
        <tr style="background:#fdf2f2;">
          <td style="padding:10px;font-weight:bold;font-size:15px;">
            {s['ticker']}
          </td>
          <td style="padding:10px;">{s['profil']}</td>
          <td style="padding:10px;color:{couleur_z20};font-weight:bold;
              font-size:15px;">{z20_str}</td>
          <td style="padding:10px;">{z60_str}</td>
          <td style="padding:10px;text-align:center;">{sma_str}</td>
          <td style="padding:10px;text-align:center;">{s['seuil_effectif']:.1f}</td>
          <td style="padding:10px;font-weight:bold;">{taille:.2f}x</td>
        </tr>"""

    html = f"""
    <html>
    <body style="font-family:Arial,sans-serif;max-width:720px;margin:auto;
                 color:#333;">

      <!-- En-tête -->
      <div style="background:#1a1a2e;color:white;padding:18px 20px;
                  border-radius:6px 6px 0 0;">
        <h2 style="margin:0;font-size:20px;">📈 TMX v2 — Alerte Signal</h2>
        <p style="margin:5px 0 0;font-size:13px;color:#aab;">
          {now} HE
        </p>
      </div>

      <!-- Résumé régime + cluster -->
      <div style="background:#f0f4f8;padding:12px 16px;
                  border:1px solid #d0d9e3;font-size:14px;">
        <span>{icone_regime} <strong>Régime VIX :</strong>
          {regime.get('description', 'inconnu')}
        </span>
        &nbsp;&nbsp;|&nbsp;&nbsp;
        <span>{icone_cluster} <strong>{cluster['n_signaux']} signal(s)</strong>
          — {cluster['action']}
        </span>
      </div>

      <!-- Tableau des signaux -->
      <table width="100%" cellspacing="0"
             style="border-collapse:collapse;border:1px solid #dee2e6;
                    font-size:14px;margin-top:0;">
        <thead>
          <tr style="background:#2c3e50;color:white;">
            <th style="padding:10px;text-align:left;">FNB</th>
            <th style="padding:10px;">Profil</th>
            <th style="padding:10px;">Z20</th>
            <th style="padding:10px;">Z60</th>
            <th style="padding:10px;">SMA50</th>
            <th style="padding:10px;">Seuil</th>
            <th style="padding:10px;">Taille</th>
          </tr>
        </thead>
        <tbody>
          {bloc_bdc}
          {lignes_signaux}
        </tbody>
      </table>

      <!-- Filtre D -->
      <div style="background:#eaf4fb;padding:12px 16px;
                  border:1px solid #bee3f8;font-size:13px;">
        <strong>Filtre D (XIU) :</strong>
        {rapport['filtre_D']['contexte']}
        &nbsp;—&nbsp;
        rendement : {rapport['filtre_D'].get('xiu_rendement_pct', 'N/A')}%
        &nbsp;|&nbsp;
        ajustement : {rapport['filtre_D']['ajustement']}
      </div>

      <!-- Signaux de contagion (rapport["signaux_contagion"]) -->
      {_construire_bloc_contagion(rapport)}

      <!-- Blocs contexte news (un par signal, injectés par news_agent.py) -->
      {"".join((blocs_news or {}).values()) if blocs_news else ""}

      <!-- Pied de page -->
      <p style="font-size:11px;color:#999;margin-top:20px;
                border-top:1px solid #eee;padding-top:10px;">
        TMX v2 — Généré automatiquement le {now} HE.<br>
        La décision finale appartient à l'investisseur.
        Ce message ne constitue pas un conseil financier.
      </p>

    </body>
    </html>
    """
    return html


# ── Construction du SMS ────────────────────────────────────────────────────────

def _construire_sms(rapport: dict) -> str:
    """
    Génère un message ultra-court pour SMS (160 caractères max).
    Format : TMX [icone] [FNB z=XX] | [FNB z=XX]
    """
    signaux = rapport["signaux"]
    regime  = rapport["regime_marche"]

    icone = {"risk_on": "🟢", "neutre": "🟡", "risk_off": "🔴"}.get(
        regime["regime"], "⚪"
    )

    parties = []
    for s in signaux:
        z20_str = f"{s['z20']:+.1f}" if s.get("z20") is not None else "?"
        parties.append(f"{s['ticker']} z={z20_str}")

    corps = " | ".join(parties)
    msg   = f"TMX v2 {icone} {corps}"

    return msg[:160]


# ── Point d'entrée principal ───────────────────────────────────────────────────

def envoyer_notifications(rapport: dict) -> bool:
    """
    Envoie courriel HTML + SMS si des signaux qualifiés sont présents.
    Appelle news_agent.py pour enrichir chaque signal avec le contexte actualité.

    Conditions de blocage (PRD section 5) :
      - Aucun signal détecté
      - Cluster 7+ FNBs (action = "bloquer")

    Retourne True si au moins un envoi a réussi.
    """

    # Vérifications préalables
    if rapport.get("n_signaux", 0) == 0:
        print("   ℹ️  Aucun signal — notifications non envoyées.")
        return False

    if rapport.get("cluster", {}).get("action") == "bloquer":
        print("   ⛔ Notifications bloquées — cluster 7+ FNBs (PRD filtre A).")
        return False

    # ── Appel à l'agent news pour chaque signal ───────────────────────────────
    blocs_news_html = {}   # { ticker: bloc_html }
    blocs_news_sms  = {}   # { ticker: bloc_sms  }

    try:
        from news_agent import obtenir_contexte_news

        for signal in rapport.get("signaux", []):
            ticker = signal["ticker"]
            z20    = signal["z20"]

            if z20 is None:
                continue

            bloc_html, bloc_sms = obtenir_contexte_news(ticker, z20, rapport)
            if bloc_html:
                blocs_news_html[ticker] = bloc_html
            if bloc_sms:
                blocs_news_sms[ticker] = bloc_sms

    except ImportError:
        print("   ⚠️  news_agent.py introuvable — notifications sans contexte news.")
    except Exception as e:
        print(f"   ⚠️  Erreur agent news : {e} — notifications sans contexte news.")

    # ── Lecture des secrets ───────────────────────────────────────────────────
    gmail_user     = os.environ.get("GMAIL_USER", "")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    email_1        = os.environ.get("NOTIF_EMAIL_1", "")
    email_2        = os.environ.get("NOTIF_EMAIL_2", "")
    sms_rogers     = os.environ.get("NOTIF_SMS_ROGERS", "")
    sms_telus      = os.environ.get("NOTIF_SMS_TELUS", "")

    if not gmail_user or not gmail_password:
        print("   ❌ GMAIL_USER ou GMAIL_APP_PASSWORD manquant dans les secrets.")
        return False

    # ── Construction des messages ─────────────────────────────────────────────
    html_body = _construire_courriel_html(rapport, blocs_news_html)
    sms_body  = _construire_sms(rapport)

    # Enrichir le SMS avec les verdicts news si disponibles
    if blocs_news_sms:
        verdicts = " | ".join(blocs_news_sms.values())
        sms_body = (sms_body + " | " + verdicts)[:160]

    now_str = datetime.now(EASTERN).strftime("%Y-%m-%d %H:%M")
    sujet_courriel = (
        f"🚨 TMX v2 — {rapport['n_signaux']} signal(s) — {now_str} HE"
    )
    sujet_sms = f"TMX v2 — {rapport['n_signaux']} signal(s)"

    # ── Liste des destinataires ───────────────────────────────────────────────
    destinataires = []
    if email_1:
        destinataires.append({"adresse": email_1, "type": "courriel"})
    if email_2:
        destinataires.append({"adresse": email_2, "type": "courriel"})
    if sms_rogers:
        destinataires.append({"adresse": sms_rogers, "type": "sms"})
    if sms_telus:
        destinataires.append({"adresse": sms_telus, "type": "sms"})

    if not destinataires:
        print("   ❌ Aucun destinataire configuré dans les secrets.")
        return False

    # ── Envoi ─────────────────────────────────────────────────────────────────
    succes = False
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as serveur:
            serveur.login(gmail_user, gmail_password)

            for dest in destinataires:
                est_sms = dest["type"] == "sms"

                msg = MIMEMultipart("alternative")
                msg["From"]    = gmail_user
                msg["To"]      = dest["adresse"]
                msg["Subject"] = sujet_sms if est_sms else sujet_courriel

                corps     = sms_body  if est_sms else html_body
                mime_type = "plain"   if est_sms else "html"
                msg.attach(MIMEText(corps, mime_type, "utf-8"))

                serveur.sendmail(gmail_user, dest["adresse"], msg.as_string())
                type_label = "SMS  " if est_sms else "Email"
                print(f"   ✅ {type_label} → {dest['adresse']}")
                succes = True

    except smtplib.SMTPAuthenticationError:
        print("   ❌ Erreur d'authentification Gmail — vérifie GMAIL_APP_PASSWORD.")
    except smtplib.SMTPException as e:
        print(f"   ❌ Erreur SMTP : {e}")
    except Exception as e:
        print(f"   ❌ Erreur inattendue : {e}")

    return succes
