"""
TMX v2 — Module de notification  [PRD v3.0]
Envoie un courriel HTML + SMS pour :
  - Signaux mean reversion détectés (FNBs actifs)
  - Chocs de contagion en pending J+1 (FNBs contextuels ≥ 2,5σ)
  - Alerte fraîcheur des données yfinance

Changements v2.1 → v3.0 :
  - UNIVERSE_PROFILS aligné (profils Wilcoxon, FNBs contextuels)
  - Profil "lent" retiré de _calculer_taille
  - Section contagion dans le courriel (chocs XRE/XUT/XEG/XIT)
  - Alerte fraîcheur envoyée même sans signal mean reversion
  - Sujet du courriel adapté selon le type d'événement

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

# ── Profils FNB v3.0 (dupliqués ici pour éviter import circulaire) ────────────
# Horizons corrigés par Wilcoxon (25 ans, 2001-2026)
# Profil "lent" retiré — aucun FNB actif lent en v3.0
# Flag "actif" : False = indicateur contextuel, aucune position mean reversion

UNIVERSE_PROFILS = {
    # FNBs actifs — trading mean reversion
    "XIU.TO": {"profil": "moyen",  "actif": True},
    "XFN.TO": {"profil": "moyen",  "actif": True},
    "XUT.TO": {"profil": "moyen",  "actif": True},
    "XRE.TO": {"profil": "moyen",  "actif": True},
    "XIN.TO": {"profil": "rapide", "actif": True},
    "XHC.TO": {"profil": "rapide", "actif": True},
    "XST.TO": {"profil": "rapide", "actif": True},
    # FNBs contextuels — z-scores calculés, chocs alimentent la contagion
    "XEG.TO": {"profil": None, "actif": False},
    "ZAG.TO": {"profil": None, "actif": False},
    "XGD.TO": {"profil": None, "actif": False},
    "XIT.TO": {"profil": None, "actif": False},
    "XMA.TO": {"profil": None, "actif": False},
}


# ── Constante locale ──────────────────────────────────────────────────────────
Z60_SEUIL_CONFIRMATION = -1.5

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
    PRD sections 7.1, 7.2, 7.3 — profil "lent" retiré en v3.0.
    """
    cfg = UNIVERSE_PROFILS.get(ticker, {})
    # Les FNBs contextuels ne génèrent pas de signal mean reversion
    if not cfg.get("actif", True) or cfg.get("profil") is None:
        return 0.0

    profil = cfg["profil"]
    base = {"rapide": 1.00, "moyen": 0.75}[profil]

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


# ── Section contagion pour le courriel ────────────────────────────────────────

# Table de correspondance émetteur → signaux contagion (PRD v3.0 §5bis)
# S2 : XEG chute ≥ 2,5 é.-t. → Short XFN J+1 (co-dépendance crédit-énergie, stabilité tridécennale)
# S5 : XEG chute ≥ 3,0 é.-t. → Short XIU J+1 (Niv.3 — EN VEILLE, n=14, ne pas déployer)
_CONTAGION_LABELS = {
    "XRE.TO": [("S1", "XIN.TO", "Achat XIN J+1",  "Niv.1 · p perm.=0,000")],
    "XUT.TO": [("S3", "XIN.TO", "Achat XIN J+1",  "Niv.1 · p perm.=0,002"),
               ("S4", "XFN.TO", "Achat XFN J+1",  "Niv.1 · p perm.<0,001")],
    "XEG.TO": [("S2", "XFN.TO", "Short XFN J+1",  "Niv.2 · stabilité tridécennale"),
               ("S5", "XIU.TO", "Short XIU J+1 ⚠", "Niv.3 — EN VEILLE, non déployé")],
}


def _construire_section_contagion_html(chocs: list[dict]) -> str:
    """
    Génère le bloc HTML listant les chocs contagion détectés (pending J+1).
    chocs : liste de dicts FNB avec choc_contagion=True issus de rapport["tous_fnbs"]
    """
    if not chocs:
        return ""

    lignes = ""
    for fnb in chocs:
        ticker = fnb["ticker"]
        z20    = fnb.get("z20")
        z20_str = f"{z20:+.2f}" if z20 is not None else "?"
        signaux_associes = _CONTAGION_LABELS.get(ticker, [])

        for sid, recepteur, action, note in signaux_associes:
            lignes += f"""
        <tr style="background:#f0f7ff;">
          <td style="padding:9px;font-weight:bold;font-size:14px;
                     color:#1a56db;">{ticker}</td>
          <td style="padding:9px;color:#c0392b;font-weight:bold;">
            {z20_str}</td>
          <td style="padding:9px;font-family:monospace;font-size:12px;
                     color:#6366f1;">{sid}</td>
          <td style="padding:9px;">→ <strong>{recepteur}</strong></td>
          <td style="padding:9px;color:#059669;">{action}</td>
          <td style="padding:9px;font-size:11px;color:#6b7280;">{note}</td>
        </tr>"""

    if not lignes:
        return ""

    return f"""
      <!-- Signaux de contagion -->
      <div style="background:#eff6ff;padding:10px 14px;margin-top:12px;
                  border-left:4px solid #3b82f6;font-size:13px;font-weight:bold;
                  color:#1e40af;">
        ⚡ Signaux de contagion J+1 détectés
      </div>
      <table width="100%" cellspacing="0"
             style="border-collapse:collapse;border:1px solid #bfdbfe;
                    font-size:13px;margin-top:0;">
        <thead>
          <tr style="background:#1e40af;color:white;">
            <th style="padding:9px;text-align:left;">Émetteur</th>
            <th style="padding:9px;">Z20</th>
            <th style="padding:9px;">Signal</th>
            <th style="padding:9px;">Récepteur</th>
            <th style="padding:9px;">Action J+1</th>
            <th style="padding:9px;">Note</th>
          </tr>
        </thead>
        <tbody>{lignes}</tbody>
      </table>
      <div style="font-size:11px;color:#6b7280;padding:6px 14px;
                  background:#eff6ff;border:1px solid #bfdbfe;border-top:none;">
        Les signaux de contagion sont gérés automatiquement par contagion.py.
        Exécution à l'ouverture J+1 si le régime VIX le permet.
      </div>"""


def _construire_alerte_fraicheur_html(fraicheur: dict) -> str:
    """Génère le bloc HTML d'alerte fraîcheur des données yfinance."""
    if not fraicheur.get("alerte"):
        return ""

    fnbs_perimes = fraicheur.get("fnbs_perimes", [])
    lignes = "".join(
        f'<li style="font-family:monospace;">{t} — dernière date : '
        f'{fraicheur["details"].get(t, {}).get("derniere_date", "?")}</li>'
        for t in fnbs_perimes
    )

    return f"""
      <!-- Alerte fraîcheur -->
      <div style="background:#fff1f2;padding:12px 16px;margin-top:12px;
                  border-left:4px solid #ef4444;font-size:13px;color:#991b1b;">
        🚨 <strong>ALERTE DONNÉES PÉRIMÉES</strong><br>
        Les données yfinance suivantes ne correspondent pas à la date d'aujourd'hui.
        Les signaux calculés ce cycle sont potentiellement incorrects.<br><br>
        <ul style="margin:6px 0 0 16px;padding:0;">{lignes}</ul>
      </div>"""


# ── Construction du courriel HTML ─────────────────────────────────────────────

def _construire_courriel_html(rapport: dict, blocs_news: dict | None = None) -> str:
    """Génère le corps HTML formaté du courriel d'alerte TMX v2."""

    now     = rapport["scan_at"][:19].replace("T", " ")
    regime  = rapport["regime_marche"]
    cluster = rapport["cluster"]
    bdc     = rapport["jour_bdc"]
    signaux = rapport["signaux"]

    # Chocs contagion (FNBs contextuels avec choc_contagion=True)
    chocs_contagion = [
        fnb for fnb in rapport.get("tous_fnbs", [])
        if fnb.get("choc_contagion") and fnb.get("role") == "contextuel"
    ]

    # Alerte fraîcheur
    fraicheur = rapport.get("fraicheur", {})

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

    # Lignes de signaux mean reversion
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
          <td style="padding:10px;">{s.get('profil', '—')}</td>
          <td style="padding:10px;color:{couleur_z20};font-weight:bold;
              font-size:15px;">{z20_str}</td>
          <td style="padding:10px;">{z60_str}</td>
          <td style="padding:10px;text-align:center;">{sma_str}</td>
          <td style="padding:10px;text-align:center;">{s.get('seuil_effectif', '—')}</td>
          <td style="padding:10px;font-weight:bold;">{taille:.2f}x</td>
        </tr>"""

    # Titre de l'en-tête selon le type d'événement
    if fraicheur.get("alerte") and not signaux and not chocs_contagion:
        titre_header = "🚨 TMX v2 — Données périmées"
    elif signaux and chocs_contagion:
        titre_header = "📈 TMX v2 — Signal + Contagion"
    elif chocs_contagion and not signaux:
        titre_header = "⚡ TMX v2 — Signal de contagion J+1"
    else:
        titre_header = "📈 TMX v2 — Alerte Signal"

    html = f"""
    <html>
    <body style="font-family:Arial,sans-serif;max-width:720px;margin:auto;
                 color:#333;">

      <!-- En-tête -->
      <div style="background:#1a1a2e;color:white;padding:18px 20px;
                  border-radius:6px 6px 0 0;">
        <h2 style="margin:0;font-size:20px;">{titre_header}</h2>
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
        <span>{icone_cluster} <strong>{cluster['n_signaux']} signal(s) MR</strong>
          — {cluster['action']}
        </span>
        {"&nbsp;&nbsp;|&nbsp;&nbsp;⚡ <strong>" + str(len(chocs_contagion)) + " choc(s) contagion</strong>" if chocs_contagion else ""}
      </div>

      {"<!-- Alerte fraîcheur -->" + _construire_alerte_fraicheur_html(fraicheur) if fraicheur.get("alerte") else ""}

      {"<!-- Tableau signaux MR -->" if signaux else ""}
      {"<table width='100%' cellspacing='0' style='border-collapse:collapse;border:1px solid #dee2e6;font-size:14px;margin-top:12px;'><thead><tr style='background:#2c3e50;color:white;'><th style='padding:10px;text-align:left;'>FNB</th><th style='padding:10px;'>Profil</th><th style='padding:10px;'>Z20</th><th style='padding:10px;'>Z60</th><th style='padding:10px;'>SMA50</th><th style='padding:10px;'>Seuil</th><th style='padding:10px;'>Taille</th></tr></thead><tbody>" + bloc_bdc + lignes_signaux + "</tbody></table>" if signaux else ""}

      <!-- Filtre D -->
      {"<div style='background:#eaf4fb;padding:12px 16px;border:1px solid #bee3f8;font-size:13px;margin-top:8px;'><strong>Filtre D (XIU) :</strong> " + rapport['filtre_D']['contexte'] + " &nbsp;—&nbsp; rendement : " + str(rapport['filtre_D'].get('xiu_rendement_pct', 'N/A')) + "% &nbsp;|&nbsp; ajustement : " + rapport['filtre_D']['ajustement'] + "</div>" if signaux else ""}

      <!-- Section contagion -->
      {_construire_section_contagion_html(chocs_contagion)}

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
    Format MR : TMX [icone] [FNB z=XX] | [FNB z=XX]
    Format contagion : TMX ⚡ XRE→XIN J+1 | XUT→XFN J+1
    """
    signaux = rapport["signaux"]
    regime  = rapport["regime_marche"]
    chocs   = [
        fnb for fnb in rapport.get("tous_fnbs", [])
        if fnb.get("choc_contagion") and fnb.get("role") == "contextuel"
    ]

    icone = {"risk_on": "🟢", "neutre": "🟡", "risk_off": "🔴"}.get(
        regime["regime"], "⚪"
    )

    parties = []
    for s in signaux:
        z20_str = f"{s['z20']:+.1f}" if s.get("z20") is not None else "?"
        parties.append(f"{s['ticker']} z={z20_str}")

    # Ajouter les chocs contagion en résumé court
    for fnb in chocs:
        ticker = fnb["ticker"]
        for sid, recepteur, _, _ in _CONTAGION_LABELS.get(ticker, []):
            parties.append(f"⚡{sid}:{ticker[:3]}→{recepteur[:3]}")

    # Alerte fraîcheur
    if rapport.get("alerte_fraicheur"):
        parties.insert(0, "🚨DONNÉES PÉRIMÉES")

    corps = " | ".join(parties)
    msg   = f"TMX v2 {icone} {corps}"

    return msg[:160]


# ── Point d'entrée principal ───────────────────────────────────────────────────

def envoyer_notifications(rapport: dict) -> bool:
    """
    Envoie courriel HTML + SMS si au moins une condition est remplie :
      - Signaux mean reversion détectés (FNBs actifs)
      - Chocs de contagion en pending J+1 (FNBs contextuels ≥ 2,5σ)
      - Alerte fraîcheur des données yfinance

    Condition de blocage (PRD section 5) :
      - Cluster 7+ FNBs (action = "bloquer") — bloque les MR seulement,
        pas les alertes fraîcheur ni les signaux de contagion

    Retourne True si au moins un envoi a réussi.
    """

    n_signaux_mr = rapport.get("n_signaux", 0)
    alerte_fraicheur = rapport.get("alerte_fraicheur", False)
    chocs_contagion  = [
        fnb for fnb in rapport.get("tous_fnbs", [])
        if fnb.get("choc_contagion") and fnb.get("role") == "contextuel"
    ]
    cluster_bloque = rapport.get("cluster", {}).get("action") == "bloquer"

    # Rien à envoyer ?
    if not alerte_fraicheur and not chocs_contagion and n_signaux_mr == 0:
        print("   ℹ️  Aucun signal, choc contagion ou alerte fraîcheur — notifications non envoyées.")
        return False

    if cluster_bloque and not alerte_fraicheur and not chocs_contagion:
        print("   ⛔ Notifications MR bloquées — cluster 7+ FNBs (PRD filtre A).")
        return False

    if cluster_bloque and n_signaux_mr > 0:
        print("   ⛔ Signaux MR bloqués (cluster 7+) — contagion/fraîcheur envoyés quand même.")

    # ── Appel à l'agent news pour chaque signal MR ────────────────────────────
    blocs_news_html = {}
    blocs_news_sms  = {}

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

    if blocs_news_sms:
        verdicts = " | ".join(blocs_news_sms.values())
        sms_body = (sms_body + " | " + verdicts)[:160]

    # Sujet adapté selon le type d'événement
    now_str = datetime.now(EASTERN).strftime("%Y-%m-%d %H:%M")
    if alerte_fraicheur and n_signaux_mr == 0 and not chocs_contagion:
        sujet_courriel = f"🚨 TMX v2 — Données périmées — {now_str} HE"
        sujet_sms      = "TMX v2 — Données périmées"
    elif chocs_contagion and n_signaux_mr == 0:
        n_c = len(chocs_contagion)
        sujet_courriel = f"⚡ TMX v2 — {n_c} choc(s) contagion J+1 — {now_str} HE"
        sujet_sms      = f"TMX v2 — {n_c} contagion J+1"
    elif chocs_contagion and n_signaux_mr > 0:
        sujet_courriel = f"📈⚡ TMX v2 — {n_signaux_mr} signal(s) + {len(chocs_contagion)} contagion — {now_str} HE"
        sujet_sms      = f"TMX v2 — MR+contagion"
    else:
        sujet_courriel = f"🚨 TMX v2 — {n_signaux_mr} signal(s) — {now_str} HE"
        sujet_sms      = f"TMX v2 — {n_signaux_mr} signal(s)"

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
