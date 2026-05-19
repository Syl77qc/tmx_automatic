#!/usr/bin/env python3
"""
tmx_generate_signaux.py — FNBLab TMX v2
Génère signaux.html à partir des signaux Granger qualité + yfinance.
Usage : python tmx_generate_signaux.py
        → génère signaux.html dans le même dossier
        → met à jour signal_history.json
"""

import json, os, sys, math
from datetime import datetime, timedelta, date
from pathlib import Path

# ── Dépendances ────────────────────────────────────────────────────────────────
try:
    import yfinance as yf
    import pandas as pd
    import numpy as np
except ImportError:
    print("pip install yfinance pandas numpy")
    sys.exit(1)

# ── Configuration ──────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
SIGNALS_CSV  = SCRIPT_DIR / "phase6_granger_top_signals.csv"
HISTORY_JSON = SCRIPT_DIR / "signal_history.json"
OUTPUT_HTML  = SCRIPT_DIR / "signaux.html"

# 14 ETFs du sous-univers Phase 6
ETFS = ["ENCC","U-UN","XEG","XFN","XGD","XIU",
        "XQQ","XRE","XSP","XST","XUT","XWD","ZAG","ZEB"]

ETF_NAMES = {
    "ENCC": "Oil & Gas Covered Call",
    "U-UN": "Sprott Uranium",
    "XEG":  "Énergie TSX",
    "XFN":  "Financières TSX",
    "XGD":  "Or global",
    "XIU":  "S&P/TSX 60",
    "XQQ":  "NASDAQ 100 CAD",
    "XRE":  "REIT TSX",
    "XSP":  "S&P 500 CAD couvert",
    "XST":  "Consommation de base",
    "XUT":  "Services publics",
    "XWD":  "MSCI Monde",
    "ZAG":  "Obligations agrégées",
    "ZEB":  "Banques égal-pondéré",
}

SEUIL_SIGNAL   = -1.0   # σ pour activer un signal (cause)
SEUIL_ZSCORE   = -1.5   # z-score 20j de l'effet pour confirmation
WINDOW_HIST    = 252    # jours pour σ historique
WINDOW_ZSCORE  = 20     # jours pour z-score mean-reversion

# ── Chargement des signaux qualité ─────────────────────────────────────────────
def load_signals():
    if not SIGNALS_CSV.exists():
        print(f"ERREUR : {SIGNALS_CSV} introuvable.")
        print("Copiez phase6_granger_top_signals.csv dans le même dossier que ce script.")
        sys.exit(1)
    df = pd.read_csv(SIGNALS_CSV)
    return df.sort_values("sharpe_signal", ascending=False).reset_index(drop=True)

# ── Fetch yfinance ─────────────────────────────────────────────────────────────
def fetch_prices(etfs, days=300):
    tickers = [f"{e}.TO" for e in etfs]
    end   = datetime.today()
    start = end - timedelta(days=days)
    print(f"  Fetch yfinance : {len(tickers)} ETFs, {days} jours...")
    raw = yf.download(tickers, start=start.strftime("%Y-%m-%d"),
                      end=end.strftime("%Y-%m-%d"),
                      auto_adjust=True, progress=False)
    close = raw["Close"].copy()
    close.columns = [c.replace(".TO","") for c in close.columns]
    close.index = pd.to_datetime(close.index)
    close = close.ffill().dropna(how="all")
    print(f"  {len(close)} jours chargés, dernière date : {close.index[-1].date()}")
    return close

# ── Calcul des indicateurs ─────────────────────────────────────────────────────
def compute_indicators(close):
    returns = np.log(close / close.shift(1))

    indicators = {}
    for sym in close.columns:
        if sym not in close.columns:
            continue
        ret = returns[sym].dropna()
        if len(ret) < 30:
            indicators[sym] = {}
            continue

        # Rendement cumulatif sur 1, 2, 3, 4, 5 jours
        cum = {}
        for lag in range(1, 6):
            cum[lag] = ret.iloc[-lag:].sum() if len(ret) >= lag else float("nan")

        # σ historique (WINDOW_HIST jours)
        sigma = ret.iloc[-WINDOW_HIST:].std() if len(ret) >= WINDOW_HIST else ret.std()

        # Z-score 20 jours mean-reversion
        recent = ret.iloc[-WINDOW_ZSCORE:]
        mu20   = recent.mean()
        sd20   = recent.std()
        today_ret = ret.iloc[-1]
        zscore_20 = (today_ret - mu20) / sd20 if sd20 > 0 else 0.0

        # Z-score 60 jours
        recent60 = ret.iloc[-60:]
        mu60 = recent60.mean()
        sd60 = recent60.std()
        zscore_60 = (today_ret - mu60) / sd60 if sd60 > 0 else 0.0

        # Prix et variation
        prix      = float(close[sym].iloc[-1])
        prix_prev = float(close[sym].iloc[-2]) if len(close) > 1 else prix
        var_pct   = (prix / prix_prev - 1) * 100

        indicators[sym] = {
            "prix":      round(prix, 2),
            "var_pct":   round(var_pct, 2),
            "sigma":     float(sigma),
            "cum":       cum,
            "zscore_20": round(zscore_20, 2),
            "zscore_60": round(zscore_60, 2),
        }
    return indicators

# ── Évaluation des signaux Granger ─────────────────────────────────────────────
def evaluate_signals(signals_df, indicators):
    actifs, veille = [], []

    for _, row in signals_df.iterrows():
        cause  = row["cause"]
        effect = row["effect"]
        lag    = int(row["lag"])

        if cause not in indicators or effect not in indicators:
            continue
        ic = indicators[cause]
        ie = indicators[effect]
        if not ic or not ie:
            continue

        cum_cause = ic["cum"].get(lag, float("nan"))
        sigma_c   = ic["sigma"]

        # Signal actif si cause a chuté > |SEUIL_SIGNAL| × σ sur lag jours
        if math.isnan(cum_cause) or sigma_c == 0:
            continue

        seuil_abs = SEUIL_SIGNAL * sigma_c * math.sqrt(lag)
        actif     = cum_cause < seuil_abs
        confirmé  = ie["zscore_20"] < SEUIL_ZSCORE

        entry = {
            "cause":      cause,
            "effect":     effect,
            "lag":        lag,
            "win_rate":   round(float(row["win_rate"]) * 100, 1),
            "sharpe":     round(float(row["sharpe_signal"]), 2),
            "avg_ret":    round(float(row["avg_return_pct"]), 4),
            "n_signals":  int(row["n_signals"]),
            "cum_cause":  round(cum_cause * 100, 3),
            "seuil":      round(seuil_abs * 100, 3),
            "zscore_eff": ie["zscore_20"],
            "prix_eff":   ie["prix"],
            "var_eff":    ie["var_pct"],
            "confirmé":   confirmé,
        }

        if actif:
            actifs.append(entry)
        else:
            veille.append(entry)

    # Trier actifs : confirmés d'abord, puis par Sharpe
    actifs.sort(key=lambda x: (-int(x["confirmé"]), -x["sharpe"]))
    veille.sort(key=lambda x: -x["sharpe"])
    return actifs, veille

# ── Historique des signaux ─────────────────────────────────────────────────────
def load_history():
    if HISTORY_JSON.exists():
        with open(HISTORY_JSON, "r") as f:
            return json.load(f)
    return []

def update_history(history, actifs, close, today_str):
    # Ajouter les nouveaux signaux actifs
    existing = {(h["date"], h["cause"], h["effect"], h["lag"])
                for h in history}

    for s in actifs:
        key = (today_str, s["cause"], s["effect"], s["lag"])
        if key not in existing:
            history.append({
                "date":       today_str,
                "cause":      s["cause"],
                "effect":     s["effect"],
                "lag":        s["lag"],
                "win_rate":   s["win_rate"],
                "sharpe":     s["sharpe"],
                "zscore_eff": s["zscore_eff"],
                "cum_cause":  s["cum_cause"],
                "prix_eff":   s["prix_eff"],
                "ret_realise":None,   # à remplir dans lag jours
            })

    # Remplir les rendements réalisés
    close_idx = close.index
    for h in history:
        if h["ret_realise"] is not None:
            continue
        try:
            entry_date = pd.Timestamp(h["date"])
            target_idx = close_idx.searchsorted(entry_date) + h["lag"]
            if target_idx < len(close_idx):
                sym = h["effect"]
                if sym in close.columns:
                    p0 = close.loc[entry_date, sym] if entry_date in close.index else None
                    pt = float(close.iloc[target_idx][sym])
                    if p0 and p0 > 0:
                        h["ret_realise"] = round((pt / float(p0) - 1) * 100, 4)
        except Exception:
            pass

    with open(HISTORY_JSON, "w") as f:
        json.dump(history, f, indent=2, default=str)
    return history

# ── Stats performance ──────────────────────────────────────────────────────────
def compute_perf(history):
    df = pd.DataFrame(history)
    if df.empty or "ret_realise" not in df.columns:
        return []
    df = df.dropna(subset=["ret_realise"])
    if df.empty:
        return []
    grp = df.groupby(["cause","effect","lag"])
    rows = []
    for (c, e, l), g in grp:
        n   = len(g)
        wr  = (g["ret_realise"] > 0).mean() * 100
        avg = g["ret_realise"].mean()
        rows.append({
            "cause": c, "effect": e, "lag": l,
            "n": n, "wr_realise": round(wr, 1),
            "avg_ret": round(avg, 4)
        })
    rows.sort(key=lambda x: -x["wr_realise"])
    return rows

# ── Génération HTML ────────────────────────────────────────────────────────────
NAVBAR = """
<nav class="navbar">
  <a class="brand" href="index.html">FNBLab</a>
  <div class="nav-links">
    <a href="intro.html">Présentation</a>
    <a href="index.html">Dashboard</a>
    <a href="systeme.html">Système</a>
    <a href="fondements.html">Fondements théoriques</a>
    <a href="analyses.html">Analyses quantitatives</a>
    <a href="resultats.html">Résultats</a>
    <a href="contagion.html">Contagion</a>
    <a href="signaux.html" class="active">Signaux</a>
    <a href="apropos.html">À propos</a>
  </div>
</nav>"""

CSS = """
<style>
  :root {
    --navy:   #1A1A2E;
    --navy2:  #16213E;
    --orange: #ED7D31;
    --blue:   #4472C4;
    --green:  #2ECC71;
    --red:    #E74C3C;
    --yellow: #F1C40F;
    --text:   #E8E8F0;
    --muted:  #9999BB;
    --card:   #1E1E35;
    --border: #2A2A45;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #0D0D1A;
    color: var(--text);
    font-family: 'Segoe UI', system-ui, sans-serif;
    font-size: 14px;
    line-height: 1.5;
  }
  .navbar {
    background: var(--navy);
    padding: 0 24px;
    display: flex;
    align-items: center;
    gap: 8px;
    border-bottom: 2px solid var(--orange);
    flex-wrap: wrap;
  }
  .navbar .brand {
    font-size: 18px;
    font-weight: 700;
    color: var(--orange);
    text-decoration: none;
    padding: 14px 16px 14px 0;
    letter-spacing: 1px;
  }
  .navbar .nav-links { display: flex; flex-wrap: wrap; gap: 2px; }
  .navbar a {
    color: var(--muted);
    text-decoration: none;
    padding: 16px 12px;
    font-size: 13px;
    transition: color .2s;
  }
  .navbar a:hover, .navbar a.active { color: #fff; }
  .navbar a.active {
    border-bottom: 3px solid var(--orange);
    color: var(--orange);
    font-weight: 600;
  }

  .container { max-width: 1280px; margin: 0 auto; padding: 28px 20px; }

  .page-title {
    font-size: 22px;
    font-weight: 700;
    color: #fff;
    margin-bottom: 4px;
  }
  .page-sub {
    color: var(--muted);
    font-size: 13px;
    margin-bottom: 28px;
  }

  /* Stats pills */
  .stats-row {
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
    margin-bottom: 28px;
  }
  .stat-pill {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 20px;
    min-width: 150px;
    text-align: center;
  }
  .stat-pill .val {
    font-size: 26px;
    font-weight: 700;
    color: var(--orange);
    line-height: 1.1;
  }
  .stat-pill .lbl { font-size: 11px; color: var(--muted); margin-top: 4px; }

  /* Sections */
  .section {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    margin-bottom: 28px;
    overflow: hidden;
  }
  .section-header {
    background: var(--navy2);
    padding: 14px 20px;
    display: flex;
    align-items: center;
    gap: 10px;
    border-bottom: 1px solid var(--border);
  }
  .section-header h2 {
    font-size: 15px;
    font-weight: 600;
    color: #fff;
  }
  .section-header .badge-count {
    background: var(--orange);
    color: #fff;
    border-radius: 20px;
    padding: 2px 9px;
    font-size: 12px;
    font-weight: 700;
  }
  .section-body { padding: 0; overflow-x: auto; }

  /* Tables */
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  thead th {
    background: var(--navy);
    color: var(--muted);
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: .5px;
    padding: 10px 14px;
    text-align: left;
    white-space: nowrap;
  }
  tbody tr { border-bottom: 1px solid var(--border); transition: background .15s; }
  tbody tr:hover { background: rgba(255,255,255,.03); }
  tbody td { padding: 10px 14px; vertical-align: middle; }
  tbody tr:last-child { border-bottom: none; }

  .empty-row td {
    text-align: center;
    color: var(--muted);
    padding: 32px;
    font-style: italic;
  }

  /* Badges */
  .badge {
    display: inline-block;
    border-radius: 5px;
    padding: 3px 9px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: .3px;
    white-space: nowrap;
  }
  .badge-actif-fort   { background: #1a3a2a; color: var(--green); border: 1px solid #2ECC71; }
  .badge-actif-mod    { background: #2a2a1a; color: var(--yellow); border: 1px solid var(--yellow); }
  .badge-confirme     { background: #1a2a3a; color: #74b9ff; border: 1px solid #74b9ff; }
  .badge-veille       { background: #1e1e35; color: var(--muted); border: 1px solid var(--border); }

  /* Arrow */
  .arrow { color: var(--orange); font-weight: 700; padding: 0 4px; }

  .pos { color: var(--green); }
  .neg { color: var(--red); }
  .neu { color: var(--muted); }

  /* Tooltip */
  .tip { border-bottom: 1px dashed var(--muted); cursor: help; }

  /* Footer */
  .footer {
    text-align: center;
    padding: 28px 20px;
    color: var(--muted);
    font-size: 12px;
    border-top: 1px solid var(--border);
    margin-top: 10px;
  }
  .footer a { color: var(--muted); }

  /* Date stamp */
  .date-stamp {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: var(--navy2);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 5px 12px;
    font-size: 12px;
    color: var(--muted);
    margin-bottom: 20px;
  }
  .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--green);
         box-shadow: 0 0 6px var(--green); display: inline-block; }

  @media (max-width: 700px) {
    .stats-row { gap: 8px; }
    .stat-pill { min-width: 100px; padding: 10px 14px; }
    .stat-pill .val { font-size: 20px; }
  }
</style>"""

def fmt_pct(v, decimals=2):
    cls = "pos" if v > 0 else ("neg" if v < 0 else "neu")
    sign = "+" if v > 0 else ""
    return f'<span class="{cls}">{sign}{v:.{decimals}f}%</span>'

def fmt_z(v):
    cls = "neg" if v < -1.5 else ("pos" if v > 1.5 else "neu")
    sign = "+" if v > 0 else ""
    return f'<span class="{cls}">{sign}{v:.2f}</span>'

def build_actifs_table(actifs):
    if not actifs:
        return """<table><thead><tr>
          <th>Statut</th><th>Cause</th><th>Effet</th><th>Lag</th>
          <th>Cumul cause</th><th>Z-score effet</th><th>Prix effet</th>
          <th>WR théorique</th><th>Sharpe</th>
        </tr></thead><tbody>
        <tr class="empty-row"><td colspan="9">Aucun signal actif aujourd'hui</td></tr>
        </tbody></table>"""

    rows = ""
    for s in actifs:
        badge = ('<span class="badge badge-actif-fort">⬤ FORT</span>'
                 if s["confirmé"] else
                 '<span class="badge badge-actif-mod">◆ MODÉRÉ</span>')
        conf  = ('<span class="badge badge-confirme">✓ Confirmé</span>'
                 if s["confirmé"] else "—")
        rows += f"""<tr>
          <td>{badge}</td>
          <td><strong>{s['cause']}</strong><br>
              <small style="color:var(--muted)">{ETF_NAMES.get(s['cause'],'')}</small></td>
          <td class="arrow">→</td>
          <td><strong>{s['effect']}</strong><br>
              <small style="color:var(--muted)">{ETF_NAMES.get(s['effect'],'')}</small></td>
          <td style="text-align:center"><strong>{s['lag']}j</strong></td>
          <td>{fmt_pct(s['cum_cause'],3)}<br>
              <small style="color:var(--muted)">seuil {fmt_pct(s['seuil'],3)}</small></td>
          <td>{fmt_z(s['zscore_eff'])}<br><small>{conf}</small></td>
          <td>{fmt_pct(s['var_eff'])}<br>
              <small style="color:var(--muted)">{s['prix_eff']:.2f}$</small></td>
          <td class="pos">{s['win_rate']:.1f}%</td>
          <td><strong>{s['sharpe']:.2f}</strong></td>
        </tr>"""

    return f"""<table>
      <thead><tr>
        <th>Statut</th><th>Cause</th><th></th><th>Effet</th><th>Lag</th>
        <th title="Rendement cumulé cause sur lag jours">Cumul cause</th>
        <th title="Z-score 20j de l'effet">Z-score effet</th>
        <th>Prix / Var.</th>
        <th>WR théo.</th><th>Sharpe</th>
      </tr></thead>
      <tbody>{rows}</tbody></table>"""

def build_veille_table(veille, limit=20):
    rows = ""
    for s in veille[:limit]:
        rows += f"""<tr>
          <td><span class="badge badge-veille">VEILLE</span></td>
          <td>{s['cause']}</td>
          <td class="arrow">→</td>
          <td>{s['effect']}</td>
          <td style="text-align:center">{s['lag']}j</td>
          <td>{fmt_pct(s['cum_cause'],3)}<br>
              <small style="color:var(--muted)">seuil {fmt_pct(s['seuil'],3)}</small></td>
          <td>{fmt_z(s['zscore_eff'])}</td>
          <td class="pos">{s['win_rate']:.1f}%</td>
          <td>{s['sharpe']:.2f}</td>
        </tr>"""

    return f"""<table>
      <thead><tr>
        <th>Statut</th><th>Cause</th><th></th><th>Effet</th><th>Lag</th>
        <th>Cumul cause</th><th>Z-score effet</th>
        <th>WR théo.</th><th>Sharpe</th>
      </tr></thead>
      <tbody>{rows if rows else '<tr class="empty-row"><td colspan="9">—</td></tr>'}
      </tbody></table>"""

def build_history_table(history, limit=40):
    recent = sorted(history, key=lambda x: x["date"], reverse=True)[:limit]
    if not recent:
        return """<table><thead><tr>
          <th>Date</th><th>Cause</th><th>Effet</th><th>Lag</th>
          <th>Z-score entrée</th><th>Rendement réalisé</th><th>WR théo.</th>
        </tr></thead><tbody>
        <tr class="empty-row"><td colspan="7">Aucun historique — les signaux s'accumuleront ici</td></tr>
        </tbody></table>"""

    rows = ""
    for h in recent:
        ret_html = (fmt_pct(h["ret_realise"]) if h["ret_realise"] is not None
                    else '<span class="neu">En cours</span>')
        rows += f"""<tr>
          <td>{h['date']}</td>
          <td><strong>{h['cause']}</strong></td>
          <td class="arrow">→</td>
          <td>{h['effect']}</td>
          <td style="text-align:center">{h['lag']}j</td>
          <td>{fmt_z(h['zscore_eff'])}</td>
          <td>{ret_html}</td>
          <td class="pos">{h['win_rate']:.1f}%</td>
        </tr>"""

    return f"""<table>
      <thead><tr>
        <th>Date</th><th>Cause</th><th></th><th>Effet</th><th>Lag</th>
        <th>Z-score entrée</th><th>Rendement réalisé</th><th>WR théo.</th>
      </tr></thead>
      <tbody>{rows}</tbody></table>"""

def build_perf_table(perf_rows):
    if not perf_rows:
        return """<table><thead><tr>
          <th>Signal</th><th>Déclenchements</th>
          <th>WR réalisé</th><th>WR théorique</th><th>Moy. ret.</th>
        </tr></thead><tbody>
        <tr class="empty-row"><td colspan="5">Les statistiques s'accumuleront après les premiers signaux</td></tr>
        </tbody></table>"""

    rows = ""
    for p in perf_rows:
        wr_cls = "pos" if p["wr_realise"] >= 55 else ("neu" if p["wr_realise"] >= 50 else "neg")
        rows += f"""<tr>
          <td><strong>{p['cause']}</strong>
              <span class="arrow">→</span>
              <strong>{p['effect']}</strong> L{p['lag']}</td>
          <td style="text-align:center">{p['n']}</td>
          <td class="{wr_cls}" style="text-align:center"><strong>{p['wr_realise']:.1f}%</strong></td>
          <td class="pos" style="text-align:center">—</td>
          <td style="text-align:center">{fmt_pct(p['avg_ret'])}</td>
        </tr>"""

    return f"""<table>
      <thead><tr>
        <th>Signal</th><th>Déclenchements</th>
        <th>WR réalisé</th><th>WR théorique</th><th>Moy. ret.</th>
      </tr></thead>
      <tbody>{rows}</tbody></table>"""

def build_univers_table(indicators):
    rows = ""
    for sym in sorted(indicators.keys()):
        ind = indicators[sym]
        if not ind:
            continue
        rows += f"""<tr>
          <td><strong>{sym}</strong><br>
              <small style="color:var(--muted)">{ETF_NAMES.get(sym,'')}</small></td>
          <td><strong>{ind['prix']:.2f}$</strong></td>
          <td>{fmt_pct(ind['var_pct'])}</td>
          <td>{fmt_z(ind['zscore_20'])}</td>
          <td>{fmt_z(ind['zscore_60'])}</td>
        </tr>"""

    return f"""<table>
      <thead><tr>
        <th>ETF</th><th>Prix</th><th>Var. jour</th>
        <th title="Z-score 20 jours">Z20</th>
        <th title="Z-score 60 jours">Z60</th>
      </tr></thead>
      <tbody>{rows}</tbody></table>"""

def generate_html(today_str, actifs, veille, history, perf, indicators, n_signals_total):
    n_actifs    = len(actifs)
    n_confirmes = sum(1 for s in actifs if s["confirmé"])
    n_hist      = len(history)
    n_wr        = sum(1 for h in history if h.get("ret_realise") is not None and h["ret_realise"] > 0)
    n_done      = sum(1 for h in history if h.get("ret_realise") is not None)
    wr_realise  = f"{n_wr/n_done*100:.0f}%" if n_done > 0 else "—"

    actifs_table  = build_actifs_table(actifs)
    veille_table  = build_veille_table(veille)
    history_table = build_history_table(history)
    perf_table    = build_perf_table(perf)
    univers_table = build_univers_table(indicators)

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>FNBLab — Signaux Granger</title>
  {CSS}
</head>
<body>
  {NAVBAR}
  <div class="container">

    <div class="page-title">Signaux Granger — Sous-univers Phase 6</div>
    <div class="page-sub">
      {n_signals_total} signaux qualité (WR&gt;55%, Sharpe&gt;0.5) sur 14 ETFs · Lags 1–5 jours
    </div>

    <div class="date-stamp">
      <span class="dot"></span>
      Mise à jour : {today_str} · Source : yfinance
    </div>

    <div class="stats-row">
      <div class="stat-pill">
        <div class="val" style="color:{'#2ECC71' if n_actifs > 0 else 'var(--muted)'}">{n_actifs}</div>
        <div class="lbl">Signaux actifs</div>
      </div>
      <div class="stat-pill">
        <div class="val" style="color:#74b9ff">{n_confirmes}</div>
        <div class="lbl">Confirmés (Z&lt;-1.5)</div>
      </div>
      <div class="stat-pill">
        <div class="val">{n_hist}</div>
        <div class="lbl">Signaux historisés</div>
      </div>
      <div class="stat-pill">
        <div class="val" style="color:{'#2ECC71' if n_done > 0 else 'var(--muted)'}">{wr_realise}</div>
        <div class="lbl">WR réalisé</div>
      </div>
      <div class="stat-pill">
        <div class="val">{n_signals_total}</div>
        <div class="lbl">Signaux qualité (pool)</div>
      </div>
    </div>

    <!-- Section 1 : Signaux actifs -->
    <div class="section">
      <div class="section-header">
        <h2>⚡ Signaux actifs aujourd'hui</h2>
        <span class="badge-count">{n_actifs}</span>
        <span style="color:var(--muted);font-size:12px;margin-left:auto">
          Actif si cumul cause &lt; {SEUIL_SIGNAL}σ√lag · Confirmé si Z-score effet &lt; {SEUIL_ZSCORE}
        </span>
      </div>
      <div class="section-body">{actifs_table}</div>
    </div>

    <!-- Section 2 : Signaux en veille (top 20) -->
    <div class="section">
      <div class="section-header">
        <h2>🔍 Signaux en veille (top 20 par Sharpe)</h2>
        <span class="badge-count">{len(veille)}</span>
      </div>
      <div class="section-body">{veille_table}</div>
    </div>

    <!-- Section 3 : Univers -->
    <div class="section">
      <div class="section-header">
        <h2>📊 Univers — 14 ETFs Phase 6</h2>
      </div>
      <div class="section-body">{univers_table}</div>
    </div>

    <!-- Section 4 : Historique -->
    <div class="section">
      <div class="section-header">
        <h2>📋 Historique des signaux (40 derniers)</h2>
        <span class="badge-count">{n_hist}</span>
      </div>
      <div class="section-body">{history_table}</div>
    </div>

    <!-- Section 5 : Performance -->
    <div class="section">
      <div class="section-header">
        <h2>🏆 Performance réalisée par signal</h2>
      </div>
      <div class="section-body">{perf_table}</div>
    </div>

    <!-- Méthodologie -->
    <div class="section">
      <div class="section-header"><h2>📖 Méthodologie</h2></div>
      <div class="section-body" style="padding:20px 24px;line-height:1.8;color:var(--muted)">
        <p><strong style="color:#fff">Source des signaux</strong> — 56 paires cause→effet
           issues du test de causalité de Granger (lags 1–5 jours, p&lt;0.05)
           sur 25 ans de données EOD, filtrées sur WR&gt;55%, Sharpe&gt;0.5, N≥20.</p>
        <br>
        <p><strong style="color:#fff">Condition d'activation</strong> — Le signal est ACTIF
           si le rendement cumulé de la cause sur <em>lag</em> jours est inférieur à
           −1σ×√lag (σ = écart-type journalier sur 252 jours).</p>
        <br>
        <p><strong style="color:#fff">Confirmation</strong> — Le signal est CONFIRMÉ
           si le z-score 20 jours de l'effet est &lt; −1.5, indiquant une condition
           de survente indépendante.</p>
        <br>
        <p><strong style="color:#fff">Limites</strong> — Les signaux Granger mesurent
           la prédictibilité linéaire passée, non la causalité économique.
           Ce site est un projet de recherche personnel.
           <strong>Ce ne sont pas des conseils financiers.</strong></p>
      </div>
    </div>

  </div>
  <footer class="footer">
    FNBLab TMX v2 · Signaux Granger Phase 6 · {today_str} ·
    <a href="https://github.com/Syl77qc/tmx_automatic">GitHub</a><br>
    Ce site ne constitue pas un conseil financier.
  </footer>
</body>
</html>"""

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    today_str = date.today().isoformat()
    print(f"\n{'='*60}")
    print(f"  tmx_generate_signaux.py — {today_str}")
    print(f"{'='*60}\n")

    # 1. Charger signaux qualité
    print("1. Chargement des signaux Granger qualité...")
    signals_df = load_signals()
    print(f"   {len(signals_df)} signaux chargés")

    # 2. Fetch yfinance
    print("\n2. Fetch prix yfinance...")
    close = fetch_prices(ETFS, days=300)

    # 3. Indicateurs
    print("\n3. Calcul des indicateurs...")
    indicators = compute_indicators(close)

    # 4. Évaluation des signaux
    print("\n4. Évaluation des signaux...")
    actifs, veille = evaluate_signals(signals_df, indicators)
    print(f"   Actifs : {len(actifs)}  |  En veille : {len(veille)}")
    if actifs:
        for s in actifs:
            conf = " [CONFIRMÉ]" if s["confirmé"] else ""
            print(f"   ⚡ {s['cause']} → {s['effect']} L{s['lag']}"
                  f"  WR={s['win_rate']}%  Sh={s['sharpe']}{conf}")

    # 5. Historique
    print("\n5. Mise à jour historique...")
    history = load_history()
    history = update_history(history, actifs, close, today_str)
    print(f"   {len(history)} entrées dans l'historique")

    # 6. Performance
    perf = compute_perf(history)

    # 7. Génération HTML
    print("\n6. Génération signaux.html...")
    html = generate_html(
        today_str, actifs, veille,
        history, perf, indicators,
        len(signals_df)
    )
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(f"   ✓ {OUTPUT_HTML}")

    print(f"\n{'='*60}")
    print("  ✓ Terminé. Pour publier :")
    print("    git add signaux.html signal_history.json")
    print(f"   git commit -m 'signaux {today_str}'")
    print("    git push")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
