"""
FNBLab — Générateur de dashboard HTML
Produit dashboard.html à partir de scan_results.json
"""

TEMPLATE = '''<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FNBLab — Dashboard TMX v2</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Fraunces:ital,wght@0,300;0,400;0,500;1,300&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root {
  --bg:        #0d0f11;
  --bg2:       #131619;
  --bg3:       #1a1e22;
  --bg4:       #21262d;
  --border:    rgba(255,255,255,0.07);
  --border2:   rgba(255,255,255,0.12);
  --text:      #e8e4dd;
  --text2:     #8a8880;
  --text3:     #555250;
  --green:     #4ade80;
  --green-bg:  rgba(74,222,128,0.08);
  --amber:     #f59e0b;
  --amber-bg:  rgba(245,158,11,0.08);
  --red:       #f87171;
  --red-bg:    rgba(248,113,113,0.08);
  --blue:      #60a5fa;
  --blue-bg:   rgba(96,165,250,0.08);
  --accent:    #e8c97e;
  --mono:      'DM Mono', monospace;
  --display:   'Fraunces', Georgia, serif;
  --sans:      'DM Sans', system-ui, sans-serif;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body {
  font-family: var(--sans);
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
  line-height: 1.6;
  min-height: 100vh;
}

/* ── Nav ── */
nav {
  position: sticky; top: 0; z-index: 100;
  background: rgba(13,15,17,0.92);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
  padding: 0 32px;
  display: flex; align-items: center;
  height: 52px; gap: 0;
}
.nav-brand {
  font-family: var(--display);
  font-size: 17px; font-weight: 500;
  color: var(--accent);
  letter-spacing: -0.01em;
  margin-right: 32px;
  text-decoration: none;
}
.nav-links { display: flex; gap: 2px; flex: 1; }
.nav-links a {
  font-size: 12px; font-weight: 400;
  color: var(--text2);
  padding: 6px 12px;
  border-radius: 6px;
  text-decoration: none;
  transition: color 0.15s, background 0.15s;
}
.nav-links a:hover { color: var(--text); background: var(--bg3); }
.nav-links a.active { color: var(--text); background: var(--bg3); }
.nav-right {
  font-family: var(--mono);
  font-size: 11px; color: var(--text3);
  display: flex; align-items: center; gap: 8px;
}
.pulse {
  width: 6px; height: 6px; border-radius: 50%;
  background: {PULSE_COLOR};
  animation: pulse 2s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

/* ── Layout ── */
.page { max-width: 1280px; margin: 0 auto; padding: 32px 32px 80px; }

/* ── Hero ── */
.hero {
  display: flex; align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 28px;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--border);
}
.hero-title {
  font-family: var(--display);
  font-size: 28px; font-weight: 300;
  font-style: italic;
  color: var(--text);
  line-height: 1.2;
}
.hero-title span { color: var(--accent); font-style: normal; font-weight: 500; }
.hero-meta {
  font-family: var(--mono);
  font-size: 11px; color: var(--text3);
  text-align: right; line-height: 2;
}

/* ── Status bar ── */
.status-bar {
  display: flex; gap: 8px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}
.status-pill {
  font-family: var(--mono);
  font-size: 11px; font-weight: 500;
  padding: 5px 12px;
  border-radius: 20px;
  border: 1px solid;
  letter-spacing: 0.03em;
}
.sp-green { color: var(--green); border-color: rgba(74,222,128,0.25); background: var(--green-bg); }
.sp-amber { color: var(--amber); border-color: rgba(245,158,11,0.25); background: var(--amber-bg); }
.sp-red   { color: var(--red);   border-color: rgba(248,113,113,0.25); background: var(--red-bg); }
.sp-blue  { color: var(--blue);  border-color: rgba(96,165,250,0.25);  background: var(--blue-bg); }
.sp-gray  { color: var(--text2); border-color: var(--border2); background: var(--bg3); }

/* ── Métriques ── */
.metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 28px;
}
.metric {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px 18px;
  position: relative;
  overflow: hidden;
}
.metric::before {
  content: '';
  position: absolute; top: 0; left: 0; right: 0;
  height: 2px;
  background: var(--accent);
  opacity: 0.3;
}
.metric-label {
  font-size: 10px; font-weight: 500;
  color: var(--text3);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 8px;
}
.metric-value {
  font-family: var(--mono);
  font-size: 26px; font-weight: 500;
  color: var(--text);
  line-height: 1;
  margin-bottom: 4px;
}
.metric-sub {
  font-size: 11px; color: var(--text3);
}
.metric-ok .metric-value { color: var(--green); }
.metric-warn .metric-value { color: var(--amber); }

/* ── Section headers ── */
.section-header {
  display: flex; align-items: baseline;
  gap: 12px; margin-bottom: 14px;
}
.section-title-text {
  font-family: var(--display);
  font-size: 16px; font-weight: 400;
  color: var(--text);
}
.section-sub {
  font-size: 11px; color: var(--text3);
  font-family: var(--mono);
}

/* ── Tableau FNBs ── */
.table-wrap {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  margin-bottom: 28px;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
thead tr {
  border-bottom: 1px solid var(--border);
}
thead th {
  font-family: var(--mono);
  font-size: 10px; font-weight: 500;
  color: var(--text3);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 10px 14px;
  text-align: left;
  white-space: nowrap;
  background: var(--bg3);
}
thead th.r { text-align: right; }
thead th.c { text-align: center; }
.th-group {
  font-size: 9px; color: var(--text3);
  letter-spacing: 0.1em;
  padding: 4px 14px 0;
  background: var(--bg3);
  border-bottom: none;
}
tbody tr {
  border-bottom: 1px solid var(--border);
  transition: background 0.1s;
}
tbody tr:last-child { border-bottom: none; }
tbody tr:hover { background: rgba(255,255,255,0.02); }
tbody tr.signal-row { background: rgba(245,158,11,0.04); }
tbody tr.signal-row:hover { background: rgba(245,158,11,0.07); }
td {
  padding: 10px 14px;
  color: var(--text);
  vertical-align: middle;
  white-space: nowrap;
}
td.r { text-align: right; }
td.c { text-align: center; }

.fnb-name {
  font-family: var(--mono);
  font-size: 12px; font-weight: 500;
  color: var(--text);
}
.fnb-sector {
  font-size: 10px; color: var(--text3);
  margin-top: 1px;
}

.z-signal { color: var(--amber); font-family: var(--mono); font-weight: 500; }
.z-watch  { color: var(--text2); font-family: var(--mono); }
.z-neg    { color: var(--red);   font-family: var(--mono); }
.z-pos    { color: var(--text3); font-family: var(--mono); }

.sma-ok   { color: var(--green); font-size: 13px; }
.sma-warn { color: var(--red);   font-size: 13px; }

.badge {
  display: inline-block;
  font-family: var(--mono);
  font-size: 10px; font-weight: 500;
  padding: 2px 8px;
  border-radius: 4px;
  letter-spacing: 0.03em;
}
.b-signal  { background: rgba(245,158,11,0.15); color: var(--amber); border: 1px solid rgba(245,158,11,0.3); }
.b-watch   { background: var(--bg4); color: var(--text3); border: 1px solid var(--border); }
.b-block   { background: rgba(248,113,113,0.1); color: var(--red); border: 1px solid rgba(248,113,113,0.25); }
.b-sect    { background: rgba(74,222,128,0.08); color: var(--green); border: 1px solid rgba(74,222,128,0.2); }
.b-fond    { background: rgba(248,113,113,0.08); color: var(--red); border: 1px solid rgba(248,113,113,0.2); }
.b-sys     { background: var(--bg4); color: var(--text2); border: 1px solid var(--border2); }

.taille-actif { font-family: var(--mono); color: var(--amber); font-weight: 500; }
.taille-na    { font-family: var(--mono); color: var(--text3); }

.var-pos { color: var(--green); font-family: var(--mono); }
.var-neg { color: var(--red);   font-family: var(--mono); }
.var-neu { color: var(--text3); font-family: var(--mono); }

/* ── Positions ouvertes ── */
.positions-wrap {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  margin-bottom: 28px;
}
.positions-empty {
  padding: 32px;
  text-align: center;
  color: var(--text3);
  font-size: 12px;
}
.positions-empty span {
  display: block;
  font-family: var(--mono);
  font-size: 18px;
  margin-bottom: 8px;
  opacity: 0.3;
}

/* ── Guide de décision ── */
.guide-wrap {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  margin-bottom: 28px;
}
.guide-header {
  padding: 18px 24px;
  border-bottom: 1px solid var(--border);
  background: var(--bg3);
}
.guide-title {
  font-family: var(--display);
  font-size: 18px; font-weight: 400;
  color: var(--text);
  margin-bottom: 4px;
}
.guide-desc { font-size: 11px; color: var(--text3); }
.guide-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
}
.guide-col {
  padding: 24px;
  border-right: 1px solid var(--border);
}
.guide-col:last-child { border-right: none; }
.guide-type {
  display: flex; align-items: center; gap: 10px;
  margin-bottom: 14px;
}
.guide-dot {
  width: 10px; height: 10px;
  border-radius: 50%; flex-shrink: 0;
}
.dot-sect { background: var(--amber); }
.dot-fond { background: var(--red); }
.dot-sys  { background: var(--text3); }
.guide-type-name {
  font-family: var(--mono);
  font-size: 13px; font-weight: 500;
  letter-spacing: 0.05em;
}
.sect-color { color: var(--amber); }
.fond-color { color: var(--red); }
.sys-color  { color: var(--text3); }
.guide-subtitle {
  font-size: 10px; color: var(--text3);
  margin-top: 2px;
}
.guide-desc-text {
  font-size: 12px; color: var(--text2);
  line-height: 1.6; margin-bottom: 14px;
}
.guide-example {
  background: var(--bg3);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 11px; color: var(--text2);
  line-height: 1.5;
  margin-bottom: 14px;
}
.guide-action {
  border-radius: 8px;
  padding: 12px 14px;
  font-size: 12px;
  line-height: 1.5;
}
.ga-sect { background: var(--green-bg); border: 1px solid rgba(74,222,128,0.2); }
.ga-fond { background: var(--red-bg);   border: 1px solid rgba(248,113,113,0.2); }
.ga-sys  { background: var(--bg4);      border: 1px solid var(--border); }
.ga-title {
  font-family: var(--mono);
  font-size: 11px; font-weight: 500;
  margin-bottom: 4px;
}
.ga-sect .ga-title { color: var(--green); }
.ga-fond .ga-title { color: var(--red); }
.ga-sys  .ga-title { color: var(--text3); }
.ga-text { font-size: 11px; color: var(--text3); }
.guide-fnbs {
  display: flex; flex-wrap: wrap; gap: 4px;
  margin-top: 12px;
}
.guide-fnb-pill {
  font-family: var(--mono);
  font-size: 10px; padding: 2px 7px;
  border-radius: 4px;
  background: var(--bg4);
  border: 1px solid var(--border);
  color: var(--text3);
}
.guide-fnb-pill.warn {
  background: rgba(248,113,113,0.08);
  border-color: rgba(248,113,113,0.2);
  color: var(--red);
}
.guide-agent {
  padding: 16px 24px;
  border-top: 1px solid var(--border);
  background: var(--bg3);
  font-size: 11px; color: var(--text3);
  line-height: 1.6;
}
.guide-agent strong { color: var(--text2); }

/* ── Définitions ── */
.defs-wrap {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  margin-bottom: 28px;
}
.defs-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0;
}
.def-item {
  padding: 18px 20px;
  border-right: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
}
.def-item:nth-child(3n) { border-right: none; }
.def-item:nth-last-child(-n+3) { border-bottom: none; }
.def-label {
  font-family: var(--mono);
  font-size: 12px; font-weight: 500;
  color: var(--accent);
  margin-bottom: 4px;
}
.def-text {
  font-size: 11px; color: var(--text3);
  line-height: 1.55;
}
.def-text strong { color: var(--text2); }

/* ── Disclaimer ── */
.disclaimer {
  margin-top: 48px;
  padding: 20px 24px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg2);
  font-size: 11px;
  color: var(--text3);
  line-height: 1.7;
}
.disclaimer strong { color: var(--text2); }

/* ── Footer ── */
footer {
  margin-top: 32px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  color: var(--text3);
}
.footer-brand {
  font-family: var(--display);
  font-size: 14px;
  color: var(--accent);
  font-style: italic;
}
</style>
</head>
<body>

<nav>
  <a class="nav-brand" href="#">FNBLab</a>
  <div class="nav-links">
    <a href="#dashboard" class="active">Dashboard</a>
    <a href="#">Système</a>
    <a href="#">Recherche</a>
    <a href="#">Résultats</a>
    <a href="#">À propos</a>
  </div>
  <div class="nav-right">
    <div class="pulse"></div>
    Dernière mise à jour : {SCAN_AT}
  </div>
</nav>

<div class="page" id="dashboard">

  <div class="hero">
    <div>
      <div class="hero-title">
        Tableau de bord<br>
        <span>TMX v2</span> — Mean reversion sur FNBs canadiens
      </div>
    </div>
    <div class="hero-meta">
      {SCAN_DATE}<br>
      Source : {SOURCE}<br>
      Mode : {MODE}
    </div>
  </div>

  <div class="status-bar">
    {STATUS_PILLS}
  </div>

  <div class="metrics">
    <div class="metric">
      <div class="metric-label">Trades complétés</div>
      <div class="metric-value">{TRADES_COMPLETES}</div>
      <div class="metric-sub">Cible : 30 pour validation</div>
    </div>
    <div class="metric {HIT_RATE_CLASS}">
      <div class="metric-label">Hit rate</div>
      <div class="metric-value">{HIT_RATE}</div>
      <div class="metric-sub">Cible : ≥ 60%</div>
    </div>
    <div class="metric">
      <div class="metric-label">Positions ouvertes</div>
      <div class="metric-value">{POSITIONS_OUVERTES}</div>
      <div class="metric-sub">Paper trading actif</div>
    </div>
    <div class="metric {DRAWDOWN_CLASS}">
      <div class="metric-label">Drawdown max</div>
      <div class="metric-value">{DRAWDOWN}</div>
      <div class="metric-sub">Limite : &lt; 15%</div>
    </div>
  </div>

  <div class="section-header">
    <div class="section-title-text">Les 12 FNBs</div>
    <div class="section-sub">Scan complet · {N_FNBS} FNBs analysés · {N_SIGNAUX} signal(s) actif(s)</div>
  </div>

  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>FNB</th>
          <th class="r">Prix</th>
          <th class="r">Var.</th>
          <th class="r">Z20</th>
          <th class="r">Z60</th>
          <th class="c">SMA50</th>
          <th class="c">Régime</th>
          <th class="c">Filtre D</th>
          <th>Groq</th>
          <th class="r">Taille</th>
          <th class="c">Action</th>
        </tr>
      </thead>
      <tbody>
        {ROWS_FNBS}
      </tbody>
    </table>
  </div>

  <div class="section-header">
    <div class="section-title-text">Positions ouvertes</div>
    <div class="section-sub">Paper trading · Simulateur JSON interne</div>
  </div>

  <div class="positions-wrap">
    {POSITIONS_HTML}
  </div>

  <div class="section-header" style="margin-top:28px;">
    <div class="section-title-text">Définitions</div>
    <div class="section-sub">Guide de lecture du tableau</div>
  </div>

  <div class="defs-wrap">
    <div class="defs-grid">
      <div class="def-item">
        <div class="def-label">Z20</div>
        <div class="def-text">Z-score sur <strong>20 jours</strong> — mesure à combien d'écarts-types le rendement d'aujourd'hui s'éloigne de la moyenne des 20 derniers jours. Signal déclenché si ≤ −2.0 é.-t.</div>
      </div>
      <div class="def-item">
        <div class="def-label">Z60</div>
        <div class="def-text">Z-score sur <strong>60 jours</strong> — confirmation du signal sur un horizon plus long. Si Z60 ≤ −1.5, le signal est confirmé et la taille n'est pas réduite.</div>
      </div>
      <div class="def-item">
        <div class="def-label">SMA50</div>
        <div class="def-text">Moyenne mobile sur <strong>50 jours</strong>. ✓ = prix au-dessus (tendance haussière, signal fiable). ✗ = prix en dessous (tendance baissière, taille divisée par 2).</div>
      </div>
      <div class="def-item">
        <div class="def-label">Régime VIX</div>
        <div class="def-text">État du marché selon le VIX. <strong>Risk-on</strong> (&lt;16) = taille normale. <strong>Neutre</strong> (16–25) = taille ÷2. <strong>Risk-off</strong> (&gt;25) = pause.</div>
      </div>
      <div class="def-item">
        <div class="def-label">Filtre D</div>
        <div class="def-text">Contexte XIU (marché large). Si XIU est stable ou positif pendant la baisse du FNB, c'est une correction sectorielle isolée — signal plus fiable mais seuil +0.5 et taille ÷1.5.</div>
      </div>
      <div class="def-item">
        <div class="def-label">Groq</div>
        <div class="def-text">Classification de l'agent IA (Groq llama-3.3-70b) basée sur les actualités des 24h. <strong>SECTORIEL</strong> = rebond probable. <strong>FONDAMENTAL</strong> = prudence. <strong>SYSTÉMIQUE</strong> = déjà bloqué.</div>
      </div>
      <div class="def-item">
        <div class="def-label">Taille</div>
        <div class="def-text">Multiplicateur de position final après tous les ajustements. Base selon profil (Rapide 1x, Moyen 0.75x, Lent 0.5x) × profondeur signal × ajustements cumulatifs.</div>
      </div>
      <div class="def-item">
        <div class="def-label">Action</div>
        <div class="def-text"><strong>Signal</strong> = tous les filtres passent, agir selon la taille calculée. <strong>Surveiller</strong> = pas de signal aujourd'hui. <strong>Bloqué</strong> = signal détecté mais filtre actif l'empêche.</div>
      </div>
      <div class="def-item">
        <div class="def-label">Var.</div>
        <div class="def-text">Variation du prix par rapport à la <strong>clôture précédente</strong>. Note : les données proviennent de yfinance (J−1) sauf si Questrade API disponible.</div>
      </div>
    </div>
  </div>

  <div class="section-header" style="margin-top:28px;">
    <div class="section-title-text">Les 3 types de baisse — Quoi faire?</div>
    <div class="section-sub">Basé sur l'analyse de 978 événements z-score ≥ 2 é.-t. (2016–2025)</div>
  </div>

  <div class="guide-wrap">
    <div class="guide-grid">
      <div class="guide-col">
        <div class="guide-type">
          <div class="guide-dot dot-sect"></div>
          <div>
            <div class="guide-type-name sect-color">SECTORIEL</div>
            <div class="guide-subtitle">Tout le secteur baisse ensemble</div>
          </div>
        </div>
        <div class="guide-desc-text">Réaction émotionnelle ou mécanique du marché à une nouvelle macro ou sectorielle. Les titres dans le FNB baissent <em>tous</em> dans des proportions similaires — aucun n'est spécialement visé.</div>
        <div class="guide-example">
          WTI perd 4% après une décision OPEP+ décevante → CNQ, Suncor, Cenovus baissent tous de 5–8% → <strong>XEG déclenche z = −3.1</strong>
        </div>
        <div class="guide-action ga-sect">
          <div class="ga-title">ACHETER — selon taille calculée</div>
          <div class="ga-text">Rebond historiquement fiable · Meilleur terrain pour TMX v2</div>
        </div>
        <div class="guide-fnbs">
          <span class="guide-fnb-pill">XEG 82%</span>
          <span class="guide-fnb-pill">XGD 72%</span>
          <span class="guide-fnb-pill">XFN 70%</span>
          <span class="guide-fnb-pill">XUT 68%</span>
          <span class="guide-fnb-pill">ZAG 70%</span>
        </div>
      </div>

      <div class="guide-col">
        <div class="guide-type">
          <div class="guide-dot dot-fond"></div>
          <div>
            <div class="guide-type-name fond-color">FONDAMENTAL</div>
            <div class="guide-subtitle">Un titre lourd a une mauvaise nouvelle</div>
          </div>
        </div>
        <div class="guide-desc-text">Un titre qui pèse lourd dans le FNB baisse de façon <em>disproportionnée</em> par rapport aux autres — publications trimestrielles décevantes, guidance réduite, annonce défavorable. La baisse peut <strong>persister</strong> si la nouvelle est réellement mauvaise.</div>
        <div class="guide-example">
          Shopify annonce des résultats trimestriels décevants → SHOP baisse de 12%, CSU et CGI bougent peu → <strong>XIT déclenche z = −3.0</strong>
        </div>
        <div class="guide-action ga-fond">
          <div class="ga-title">PRUDENCE — vérifier les nouvelles</div>
          <div class="ga-text">Rebond non garanti · Consulter le verdict Groq avant d'agir</div>
        </div>
        <div class="guide-fnbs">
          <span class="guide-fnb-pill warn">XIT 87% ⚠</span>
          <span class="guide-fnb-pill">XHC 20%</span>
          <span class="guide-fnb-pill">XGD 7%</span>
          <span class="guide-fnb-pill">XFN 2%</span>
        </div>
      </div>

      <div class="guide-col">
        <div class="guide-type">
          <div class="guide-dot dot-sys"></div>
          <div>
            <div class="guide-type-name sys-color">SYSTÉMIQUE</div>
            <div class="guide-subtitle">Tout le marché s'effondre en même temps</div>
          </div>
        </div>
        <div class="guide-desc-text">Crise globale — COVID, crash financier, tarifs Trump. Tout baisse simultanément : banques, mines d'or, énergie, technologie. Le FNB ne baisse pas pour ses propres raisons — il suit simplement la marée générale.</div>
        <div class="guide-example">
          Annonce de tarifs douaniers massifs → XIU, XFN, XEG, XIT, XGD baissent tous ≥ 3% → <strong>7+ FNBs en signal simultané</strong>
        </div>
        <div class="guide-action ga-sys">
          <div class="ga-title">DÉJÀ BLOQUÉ</div>
          <div class="ga-text">Filtre cluster 7+ et VIX s'en occupent dans le scanner</div>
        </div>
        <div class="guide-fnbs">
          <span class="guide-fnb-pill">Tous les FNBs</span>
          <span class="guide-fnb-pill">VIX &gt; 25</span>
          <span class="guide-fnb-pill">Cluster 7+</span>
        </div>
      </div>
    </div>

    <div class="guide-agent">
      <strong>Agent news TMX v2 :</strong> Dès qu'un z-score ≤ −2 est détecté par le scanner, l'agent consulte Yahoo Finance RSS + Google News et soumet le contexte à Groq (llama-3.3-70b). Groq classifie automatiquement la baisse dans l'une des trois catégories ci-dessus et injecte un résumé de 3–5 lignes dans la notification courriel + SMS. <strong>La décision finale appartient toujours à l'investisseur.</strong>
    </div>
  </div>

  <div class="disclaimer">
    <strong>Avis important — Ce site ne constitue pas un conseil financier.</strong><br>
    FNBLab est un projet de recherche personnel documentant la construction et le suivi d'un système de mean reversion sur FNBs canadiens (TSX). Toutes les positions affichées sont du <em>paper trading</em> (simulation) et n'impliquent aucune transaction réelle. Les performances passées ne garantissent pas les performances futures. Les informations présentées sont fournies à titre éducatif uniquement. Avant de prendre toute décision d'investissement, consultez un conseiller financier agréé. L'auteur ne peut être tenu responsable des décisions prises sur la base de ce site.
  </div>

</div>

<footer style="max-width:1280px; margin:0 auto; padding: 0 32px 40px;">
  <span class="footer-brand">FNBLab</span>
  <span>TMX v2 · Paper trading · {SCAN_YEAR} · <a href="https://github.com/Syl77qc/tmx_automatic" style="color:var(--text3); text-decoration:none;">GitHub</a></span>
  <span>Ce site ne constitue pas un conseil financier</span>
</footer>

</body>
</html>'''

print("Template chargé OK — longueur:", len(TEMPLATE))

import json
from datetime import datetime
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/Toronto")

SECTEURS = {
    "XIU.TO": "Marché large",  "XFN.TO": "Financières",
    "XEG.TO": "Énergie",       "XUT.TO": "Services pub.",
    "XIT.TO": "Technologie",   "XRE.TO": "FPI",
    "XMA.TO": "Matériaux",     "XIN.TO": "International",
    "XHC.TO": "Santé",         "XST.TO": "Consommation",
    "XGD.TO": "Or",            "ZAG.TO": "Obligations",
}

def generer_row_fnb(r, regime, filtre_D, cluster_action):
    ticker = r["ticker"]
    z20    = r.get("z20")
    z60    = r.get("z60")
    sma_ok = r.get("dessus_sma50")
    prix   = r.get("prix_cloture", 0)
    rend   = r.get("rendement_jour_pct", 0) or 0
    signal = r.get("signal", False)
    seuil  = r.get("seuil_effectif", 2.0)

    # Classe de ligne
    row_class = ' class="signal-row"' if signal else ''

    # Z-score classe
    def z_class(z, seuil=2.0):
        if z is None: return "z-pos", "—"
        txt = f"{z:+.2f}"
        if z <= -seuil:    return "z-signal", txt
        elif z <= -1.5:    return "z-watch",  txt
        elif z < 0:        return "z-neg",    txt
        else:              return "z-pos",    txt

    z20c, z20t = z_class(z20, seuil)
    z60c, z60t = z_class(z60, 1.5)

    sma_html = f'<span class="sma-ok">✓</span>' if sma_ok else (
               f'<span class="sma-warn">✗</span>' if sma_ok is False else "—")

    # Régime pill
    reg = regime.get("regime", "inconnu")
    if reg == "risk_on":
        reg_html = '<span class="badge b-sect">Risk-on</span>'
    elif reg == "neutre":
        reg_html = '<span class="badge b-watch">Neutre</span>'
    else:
        reg_html = '<span class="badge b-block">Risk-off</span>'

    # Filtre D
    ctx = filtre_D.get("contexte", "")
    if "positif" in ctx or "stable" in ctx:
        fd_html = "XIU +"
    elif "systémique" in ctx or "baisse" in ctx:
        fd_html = "XIU —"
    else:
        fd_html = "Zone grise"

    # Groq (placeholder — sera rempli par news_agent)
    groq_html = '<span class="b-na" style="color:var(--text3);font-family:var(--mono);font-size:11px;">—</span>'

    # Taille
    if signal:
        # Calcul simplifié
        profil_base = {"rapide": 1.0, "moyen": 0.75, "lent": 0.5}
        profil = r.get("profil", "moyen")
        base   = profil_base.get(profil, 0.75)
        az20   = abs(z20) if z20 else 2.0
        mult   = 2.0 if az20 >= 3.0 else (1.5 if az20 >= 2.5 else 1.0)
        t = base * mult
        if reg == "neutre":   t /= 2
        if sma_ok is False:   t /= 2
        if z60 is not None and z60 > -1.5: t /= 1.5
        if "positif" in ctx or "stable" in ctx: t /= 1.5
        taille_html = f'<span class="taille-actif">{t:.2f}x</span>'
    else:
        taille_html = '<span class="taille-na">—</span>'

    # Action
    if signal:
        action_html = '<span class="badge b-signal">Signal</span>'
    else:
        action_html = '<span class="badge b-watch">Surveiller</span>'

    # Variation
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
    if not positions:
        return '''<div class="positions-empty">
          <span>[ ]</span>
          Aucune position ouverte en ce moment.
          Le premier signal déclenchera l'entrée en paper trading.
        </div>'''

    rows = ""
    for p in positions:
        ticker = p.get("ticker", "")
        prix_e = p.get("prix_entree", 0)
        prix_a = p.get("prix_actuel", prix_e)
        pnl    = (prix_a - prix_e) / prix_e * 100 if prix_e else 0
        date_e = p.get("date_entree", "")[:10]
        taille = p.get("taille", 0)
        horizon = p.get("horizon_restant_j", "?")
        pnl_class = "var-pos" if pnl >= 0 else "var-neg"
        rows += f'''<tr>
          <td><span class="fnb-name">{ticker}</span></td>
          <td style="font-family:var(--mono)">{prix_e:.2f}</td>
          <td style="font-family:var(--mono)">{prix_a:.2f}</td>
          <td><span class="{pnl_class}">{pnl:+.2f}%</span></td>
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
    cluster = rapport.get("cluster", {})
    bdc     = rapport.get("jour_bdc", {})
    n_sig   = rapport.get("n_signaux", 0)
    source  = rapport.get("source_donnees", "yfinance")

    vix = regime.get("vix", "?")
    reg = regime.get("regime", "inconnu")
    if reg == "risk_on":
        vix_pill = f'<span class="status-pill sp-green">VIX {vix} — Risk-on</span>'
    elif reg == "neutre":
        vix_pill = f'<span class="status-pill sp-amber">VIX {vix} — Neutre</span>'
    else:
        vix_pill = f'<span class="status-pill sp-red">VIX {vix} — Risk-off</span>'

    if n_sig == 0:
        sig_pill = '<span class="status-pill sp-gray">Aucun signal</span>'
    else:
        sig_pill = f'<span class="status-pill sp-amber">{n_sig} signal(s) actif(s)</span>'

    src_pill = f'<span class="status-pill sp-gray">Source : {source[:30]}</span>'

    bdc_pill = ""
    if bdc.get("est_jour_bdc"):
        bdc_pill = f'<span class="status-pill sp-amber">Jour BdC : {bdc["type_bdc"]}</span>'

    return vix_pill + sig_pill + src_pill + bdc_pill


def generer_dashboard(rapport, positions=None):
    now      = datetime.now(EASTERN)
    scan_at  = rapport.get("scan_at", now.isoformat())[:16].replace("T", " ")
    scan_date = now.strftime("%A %d %B %Y").capitalize()
    scan_year = str(now.year)
    source   = rapport.get("source_donnees", "yfinance")
    mode     = "LIVE" if rapport.get("heures_marche") else "DAILY"
    regime   = rapport.get("regime_marche", {})
    filtre_D = rapport.get("filtre_D", {})
    cluster  = rapport.get("cluster", {})
    n_fnbs   = rapport.get("n_fnbs_scannes", 12)
    n_sig    = rapport.get("n_signaux", 0)

    # Pulse color
    reg = regime.get("regime", "inconnu")
    pulse_color = "#4ade80" if reg == "risk_on" else ("#f59e0b" if reg == "neutre" else "#f87171")

    # Status pills
    status_pills = generer_status_pills(rapport)

    # Métriques (paper trading — à alimenter depuis positions.json)
    trades_completes = len([p for p in (positions or []) if p.get("statut") == "ferme"])
    pos_ouvertes     = len([p for p in (positions or []) if p.get("statut") == "ouvert"])

    hit_rate     = "—"
    hit_class    = ""
    drawdown     = "—"
    dd_class     = ""

    trades_fermes = [p for p in (positions or []) if p.get("statut") == "ferme"]
    if trades_fermes:
        gagnants = [p for p in trades_fermes if p.get("rendement_pct", 0) > 0]
        hr = len(gagnants) / len(trades_fermes) * 100
        hit_rate  = f"{hr:.0f}%"
        hit_class = "metric-ok" if hr >= 60 else "metric-warn"
        rends = [p.get("rendement_pct", 0) for p in trades_fermes]
        dd = min(0, min(rends)) if rends else 0
        drawdown = f"{dd:.1f}%"
        dd_class = "metric-ok" if abs(dd) < 15 else "metric-warn"

    # Lignes du tableau
    tous_fnbs = rapport.get("tous_fnbs", [])
    rows = "\n".join([
        generer_row_fnb(r, regime, filtre_D, cluster.get("action","normal"))
        for r in tous_fnbs
        if not r.get("erreur")
    ])

    # Positions
    pos_html = generer_positions_html([p for p in (positions or []) if p.get("statut") == "ouvert"])

    html = TEMPLATE.replace("{SCAN_AT}", scan_at)
    html = html.replace("{SCAN_DATE}", scan_date)
    html = html.replace("{SCAN_YEAR}", scan_year)
    html = html.replace("{SOURCE}", source[:40])
    html = html.replace("{MODE}", mode)
    html = html.replace("{PULSE_COLOR}", pulse_color)
    html = html.replace("{STATUS_PILLS}", status_pills)
    html = html.replace("{TRADES_COMPLETES}", str(trades_completes))
    html = html.replace("{HIT_RATE}", hit_rate)
    html = html.replace("{HIT_RATE_CLASS}", hit_class)
    html = html.replace("{POSITIONS_OUVERTES}", str(pos_ouvertes))
    html = html.replace("{DRAWDOWN}", drawdown)
    html = html.replace("{DRAWDOWN_CLASS}", dd_class)
    html = html.replace("{N_FNBS}", str(n_fnbs))
    html = html.replace("{N_SIGNAUX}", str(n_sig))
    html = html.replace("{ROWS_FNBS}", rows)
    html = html.replace("{POSITIONS_HTML}", pos_html)

    return html


# ── Données de test (simulées) ─────────────────────────────────────────────────
rapport_test = {
    "scan_at": datetime.now(EASTERN).isoformat(),
    "source_donnees": "yfinance (fallback)",
    "heures_marche": True,
    "regime_marche": {"vix": 19.2, "regime": "neutre",
        "description": "VIX 19.2 entre 16.0-25.0 — tailles réduites",
        "tag": "regime:VIX_neutre"},
    "filtre_D": {"xiu_rendement_pct": 0.65, "contexte": "XIU_stable_ou_positif",
        "ajustement": "seuil+0.5_taille÷1.5"},
    "jour_bdc": {"est_jour_bdc": False, "type_bdc": None, "tag": "boc:non_BdC", "regle": None},
    "cluster": {"n_signaux": 1, "action": "normal", "tag": "cluster:1_3"},
    "n_fnbs_scannes": 12, "n_signaux": 1,
    "signaux": [],
    "tous_fnbs": [
        {"ticker":"XIU.TO","profil":"rapide","seuil_effectif":3.0,"prix_cloture":49.48,"rendement_jour_pct":0.65,"z20":0.51,"z60":0.62,"dessus_sma50":True,"signal":False},
        {"ticker":"XFN.TO","profil":"moyen","seuil_effectif":3.0,"prix_cloture":80.40,"rendement_jour_pct":0.61,"z20":0.29,"z60":0.57,"dessus_sma50":True,"signal":False},
        {"ticker":"XEG.TO","profil":"lent","seuil_effectif":3.0,"prix_cloture":25.49,"rendement_jour_pct":-0.43,"z20":-3.22,"z60":-3.62,"dessus_sma50":True,"signal":True},
        {"ticker":"XUT.TO","profil":"rapide","seuil_effectif":3.0,"prix_cloture":36.10,"rendement_jour_pct":0.45,"z20":0.75,"z60":0.86,"dessus_sma50":True,"signal":False},
        {"ticker":"XIT.TO","profil":"rapide","seuil_effectif":3.0,"prix_cloture":64.43,"rendement_jour_pct":-1.32,"z20":0.47,"z60":0.59,"dessus_sma50":True,"signal":False},
        {"ticker":"XRE.TO","profil":"lent","seuil_effectif":3.0,"prix_cloture":16.17,"rendement_jour_pct":-0.31,"z20":0.84,"z60":1.10,"dessus_sma50":True,"signal":False},
        {"ticker":"XMA.TO","profil":"moyen","seuil_effectif":3.0,"prix_cloture":49.15,"rendement_jour_pct":-0.62,"z20":0.61,"z60":0.56,"dessus_sma50":True,"signal":False},
        {"ticker":"XIN.TO","profil":"rapide","seuil_effectif":3.0,"prix_cloture":44.65,"rendement_jour_pct":-0.22,"z20":0.01,"z60":0.10,"dessus_sma50":True,"signal":False},
        {"ticker":"XHC.TO","profil":"moyen","seuil_effectif":3.0,"prix_cloture":67.84,"rendement_jour_pct":-1.28,"z20":-1.18,"z60":-1.27,"dessus_sma50":False,"signal":False},
        {"ticker":"XST.TO","profil":"rapide","seuil_effectif":3.0,"prix_cloture":64.68,"rendement_jour_pct":-1.51,"z20":-0.51,"z60":-0.55,"dessus_sma50":False,"signal":False},
        {"ticker":"XGD.TO","profil":"moyen","seuil_effectif":3.0,"prix_cloture":61.35,"rendement_jour_pct":0.81,"z20":0.46,"z60":0.42,"dessus_sma50":True,"signal":False},
        {"ticker":"ZAG.TO","profil":"lent","seuil_effectif":3.0,"prix_cloture":13.71,"rendement_jour_pct":-0.07,"z20":-0.40,"z60":-0.50,"dessus_sma50":False,"signal":False},
    ]
}

html = generer_dashboard(rapport_test, positions=[])
with open("/home/claude/fnblab/dashboard.html", "w", encoding="utf-8") as f:
    f.write(html)
print(f"✅ dashboard.html généré — {len(html):,} caractères")
