"""
FNBLab — generate_dashboard.py
Appelé par GitHub Actions après scanner.py.
Lit scan_results.json + positions.json et génère index.html.
"""

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

EASTERN = ZoneInfo("America/Toronto")

SECTEURS = {
    "XIU.TO": "Marché large",  "XFN.TO": "Financières",
    "XEG.TO": "Énergie",       "XUT.TO": "Services pub.",
    "XIT.TO": "Technologie",   "XRE.TO": "FPI",
    "XMA.TO": "Matériaux",     "XIN.TO": "International",
    "XHC.TO": "Santé",         "XST.TO": "Consommation",
    "XGD.TO": "Or",            "ZAG.TO": "Obligations",
}

TEMPLATE = open(Path(__file__).parent / "index.html", encoding="utf-8").read() \
    if Path("index.html").exists() else None


def generer_row_fnb(r, regime, filtre_D, cluster_action):
    ticker = r["ticker"]
    z20    = r.get("z20")
    z60    = r.get("z60")
    sma_ok = r.get("dessus_sma50")
    prix   = r.get("prix_cloture", 0)
    rend   = r.get("rendement_jour_pct", 0) or 0
    signal = r.get("signal", False)
    seuil  = r.get("seuil_effectif", 2.0)

    row_class = ' class="signal-row"' if signal else ''

    def z_fmt(z):
        if z is None: return "z-pos", "—"
        t = f"{z:+.2f}"
        if z <= -2.5:  return "z-signal", t
        elif z <= -1.5: return "z-watch",  t
        elif z < 0:    return "z-neg",    t
        else:          return "z-pos",    t

    z20c, z20t = z_fmt(z20)
    z60c, z60t = z_fmt(z60)

    sma_html = ('<span class="sma-ok">✓</span>' if sma_ok else
               ('<span class="sma-warn">✗</span>' if sma_ok is False else "—"))

    reg = regime.get("regime", "inconnu")
    reg_html = {
        "risk_on":  '<span class="badge b-sect">Risk-on</span>',
        "neutre":   '<span class="badge b-watch">Neutre</span>',
        "risk_off": '<span class="badge b-block">Risk-off</span>',
    }.get(reg, '<span class="badge b-watch">—</span>')

    ctx = filtre_D.get("contexte", "")
    fd_html = ("XIU +" if ("positif" in ctx or "stable" in ctx)
               else ("XIU —" if ("systémique" in ctx or "baisse" in ctx)
               else "Zone grise"))

    groq_html = '<span style="color:var(--text3);font-family:var(--mono);font-size:11px;">—</span>'

    if signal:
        profil_base = {"rapide": 1.0, "moyen": 0.75, "lent": 0.5}
        profil = r.get("profil", "moyen")
        base   = profil_base.get(profil, 0.75)
        az20   = abs(z20) if z20 else 2.0
        mult   = 2.0 if az20 >= 3.0 else (1.5 if az20 >= 2.5 else 1.0)
        t = base * mult
        if reg == "neutre":              t /= 2
        if sma_ok is False:              t /= 2
        if z60 is not None and z60 > -1.5: t /= 1.5
        if "positif" in ctx or "stable" in ctx: t /= 1.5
        taille_html = f'<span class="taille-actif">{t:.2f}x</span>'
        action_html = '<span class="badge b-signal">Signal</span>'
    else:
        taille_html = '<span class="taille-na">—</span>'
        action_html = '<span class="badge b-watch">Surveiller</span>'

    if rend > 0.05:
        var_html = f'<span class="var-pos">+{rend:.2f}%</span>'
    elif rend < -0.05:
        var_html = f'<span class="var-neg">{rend:.2f}%</span>'
    else:
        var_html = f'<span class="var-neu">{rend:+.2f}%</span>'

    secteur = SECTEURS.get(ticker, "")
    return f'''<tr{row_class}>
      <td><div class="fnb-name">{ticker}</div><div class="fnb-sector">{secteur}</div></td>
      <td class="r" style="font-family:var(--mono)">{prix:.2f}</td>
      <td class="r">{var_html}</td>
      <td class="r"><span class="{z20c}">{z20t}</span></td>
      <td class="r"><span class="{z60c}">{z60t}</span></td>
      <td class="c">{sma_html}</td>
      <td class="c">{reg_html}</td>
      <td class="c" style="font-size:11px;color:var(--text3)">{fd_html}</td>
      <td>{groq_html}</td>
      <td class="r">{taille_html}</td>
      <td class="c">{action_html}</td>
    </tr>'''


def generer_positions_html(positions):
    ouvertes = [p for p in positions if p.get("statut") == "ouvert"]
    if not ouvertes:
        return '''<div class="positions-empty">
          <span>[ ]</span>
          Aucune position ouverte. Le premier signal déclenchera l'entrée en paper trading.
        </div>'''
    rows = ""
    for p in ouvertes:
        ticker  = p.get("ticker", "")
        prix_e  = p.get("prix_entree", 0)
        prix_a  = p.get("prix_actuel", prix_e)
        pnl     = (prix_a - prix_e) / prix_e * 100 if prix_e else 0
        date_e  = p.get("date_entree", "")[:10]
        taille  = p.get("taille", 0)
        horizon = p.get("horizon_restant_j", "?")
        pnl_cls = "var-pos" if pnl >= 0 else "var-neg"
        rows += f'''<tr>
          <td><span class="fnb-name">{ticker}</span></td>
          <td style="font-family:var(--mono)">{prix_e:.2f}</td>
          <td style="font-family:var(--mono)">{prix_a:.2f}</td>
          <td><span class="{pnl_cls}">{pnl:+.2f}%</span></td>
          <td style="font-family:var(--mono)">{taille:.2f}x</td>
          <td style="font-family:var(--mono);color:var(--text3)">{date_e}</td>
          <td style="font-family:var(--mono);color:var(--text3)">{horizon}j</td>
        </tr>'''
    return f'''<table>
      <thead><tr>
        <th>FNB</th><th class="r">Prix entrée</th><th class="r">Prix actuel</th>
        <th class="r">P&amp;L</th><th class="r">Taille</th>
        <th>Date entrée</th><th>Horizon</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>'''


def generer_status_pills(rapport):
    regime  = rapport.get("regime_marche", {})
    bdc     = rapport.get("jour_bdc", {})
    n_sig   = rapport.get("n_signaux", 0)
    source  = rapport.get("source_donnees", "yfinance")
    vix     = regime.get("vix", "?")
    reg     = regime.get("regime", "inconnu")

    vix_pill = {
        "risk_on":  f'<span class="status-pill sp-green">VIX {vix} — Risk-on</span>',
        "neutre":   f'<span class="status-pill sp-amber">VIX {vix} — Neutre</span>',
        "risk_off": f'<span class="status-pill sp-red">VIX {vix} — Risk-off</span>',
    }.get(reg, f'<span class="status-pill sp-gray">VIX {vix}</span>')

    sig_pill = ('<span class="status-pill sp-gray">Aucun signal</span>' if n_sig == 0
                else f'<span class="status-pill sp-amber">{n_sig} signal(s) actif(s)</span>')

    src_pill = f'<span class="status-pill sp-gray">Source : {source[:35]}</span>'

    bdc_pill = (f'<span class="status-pill sp-amber">Jour BdC : {bdc["type_bdc"]}</span>'
                if bdc.get("est_jour_bdc") else "")

    return vix_pill + sig_pill + src_pill + bdc_pill


def generer_dashboard(rapport, positions=None):
    positions = positions or []
    now       = datetime.now(EASTERN)
    scan_at   = rapport.get("scan_at", now.isoformat())[:16].replace("T", " ")
    scan_date = now.strftime("%A %d %B %Y").capitalize()
    scan_year = str(now.year)
    source    = rapport.get("source_donnees", "yfinance")
    mode      = "LIVE" if rapport.get("heures_marche") else "DAILY"
    regime    = rapport.get("regime_marche", {})
    filtre_D  = rapport.get("filtre_D", {})
    cluster   = rapport.get("cluster", {})
    n_fnbs    = rapport.get("n_fnbs_scannes", 12)
    n_sig     = rapport.get("n_signaux", 0)

    reg = regime.get("regime", "inconnu")
    pulse_color = {"risk_on": "#4ade80", "neutre": "#f59e0b", "risk_off": "#f87171"}.get(reg, "#888")

    trades_fermes   = [p for p in positions if p.get("statut") == "ferme"]
    trades_completes = len(trades_fermes)
    pos_ouvertes    = len([p for p in positions if p.get("statut") == "ouvert"])

    hit_rate  = "—"; hit_class  = ""
    drawdown  = "—"; dd_class   = ""
    if trades_fermes:
        gagnants  = [p for p in trades_fermes if p.get("rendement_pct", 0) > 0]
        hr        = len(gagnants) / len(trades_fermes) * 100
        hit_rate  = f"{hr:.0f}%"
        hit_class = "metric-ok" if hr >= 60 else "metric-warn"
        rends     = [p.get("rendement_pct", 0) for p in trades_fermes]
        dd        = min(0, min(rends))
        drawdown  = f"{dd:.1f}%"
        dd_class  = "metric-ok" if abs(dd) < 15 else "metric-warn"

    rows     = "\n".join([generer_row_fnb(r, regime, filtre_D, cluster.get("action", "normal"))
                          for r in rapport.get("tous_fnbs", []) if not r.get("erreur")])
    pos_html = generer_positions_html(positions)
    status   = generer_status_pills(rapport)

    # Lire le template depuis index.html existant
    template_path = Path("index.html")
    if not template_path.exists():
        print("❌ index.html introuvable — impossible de générer le dashboard")
        return False

    html = template_path.read_text(encoding="utf-8")

    # Remplacements
    replacements = {
        "2026-04-11 07:58": scan_at,
        "Saturday 11 april 2026": scan_date,
        "yfinance (fallback)": source[:40],
        "LIVE": mode,
        "DAILY": mode,
    }

    # Injection dynamique via marqueurs
    # On remplace le contenu entre les balises tbody du tableau FNBs
    import re

    # Status pills
    html = re.sub(
        r'(<div class="status-bar">)(.*?)(</div>)',
        lambda m: m.group(1) + status + m.group(3),
        html, flags=re.DOTALL
    )

    # Métriques
    html = html.replace(
        ">0<\n          <div class=\"metric-sub\">Cible : 30 pour validation</div>",
        f">{trades_completes}<\n          <div class=\"metric-sub\">Cible : 30 pour validation</div>"
    )

    # Tableau FNBs — remplacer le tbody
    html = re.sub(
        r'(<tbody>)(.*?)(</tbody>)',
        lambda m: m.group(1) + rows + m.group(3),
        html, flags=re.DOTALL
    )

    # Positions
    html = re.sub(
        r'(<div class="positions-wrap">)(.*?)(</div>\s*\n\s*<div class="section-header")',
        lambda m: m.group(1) + "\n    " + pos_html + "\n  </div>\n\n  " + m.group(3)[6:],
        html, flags=re.DOTALL
    )

    # Scan_at dans le nav
    html = re.sub(
        r'Dernière mise à jour : [\d\- :]+',
        f'Dernière mise à jour : {scan_at}',
        html
    )

    # Pulse color
    html = re.sub(
        r'background: #[0-9a-f]{6};\s*animation: pulse',
        f'background: {pulse_color}; animation: pulse',
        html
    )

    Path("index.html").write_text(html, encoding="utf-8")
    print(f"✅ index.html mis à jour — {len(html):,} chars — {n_sig} signal(s)")
    return True


if __name__ == "__main__":
    # Lire scan_results.json
    scan_path = Path("scan_results.json")
    if not scan_path.exists():
        print("❌ scan_results.json introuvable")
        exit(1)

    rapport = json.loads(scan_path.read_text(encoding="utf-8"))

    # Lire positions.json si disponible
    pos_path = Path("positions.json")
    positions = []
    if pos_path.exists():
        try:
            data = json.loads(pos_path.read_text(encoding="utf-8"))
            positions = data if isinstance(data, list) else data.get("positions", [])
        except Exception as e:
            print(f"⚠️  positions.json illisible : {e}")

    ok = generer_dashboard(rapport, positions)
    exit(0 if ok else 1)
