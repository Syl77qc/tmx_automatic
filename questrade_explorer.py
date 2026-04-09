"""
TMX v2 — Questrade API Explorer
Phase 1 : Vérification des capacités de l'API

Ce script est 100% lecture seule. Il ne place aucun ordre et n'écrit rien
sur ton compte Questrade. Il documente ce qui est accessible et produit
un rapport JSON pour guider l'architecture de la Phase 1.

Usage :
    1. Crée un fichier .env dans le même répertoire avec :
       QUESTRADE_REFRESH_TOKEN=ton_token_ici
    2. Lance : python questrade_explorer.py

Le token manuel expire dans 7 jours — génère-en un nouveau dans l'API Centre
si nécessaire (API Centre → Personal apps → New manual authorization).
"""

import os
import json
import time
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv

# ── Configuration ─────────────────────────────────────────────────────────────

# Les 12 FNBs de l'univers TMX v2 (section 6 du PRD)
UNIVERSE = [
    "XIU.TO",  # S&P/TSX 60 — Rapide — Bloc Marché large
    "XFN.TO",  # Financières CA — Moyen — Bloc Marché large
    "XEG.TO",  # Énergie CA — Lent — Sans bloc
    "XUT.TO",  # Services publics CA — Rapide — Bloc Taux
    "XIT.TO",  # Technologies CA — Rapide — Sans bloc
    "XRE.TO",  # Immobilier CA — Lent — Bloc Taux
    "XMA.TO",  # Matériaux CA — Moyen — Bloc Métaux
    "XIN.TO",  # International — Rapide — Bloc Marché large
    "XHC.TO",  # Soins de santé — Moyen — Sans bloc
    "XST.TO",  # Consommation de base — Rapide — Sans bloc
    "XGD.TO",  # Mines d'or — Moyen — Bloc Métaux
    "ZAG.TO",  # Obligations CA — Lent — Bloc Taux
]

# Intervalles de candles disponibles selon la doc Questrade
CANDLE_INTERVALS = ["OneMinute", "FiveMinutes", "FifteenMinutes", "HalfHour",
                    "OneHour", "OneDay", "OneWeek", "OneMonth", "OneYear"]

# ── Authentification OAuth2 ────────────────────────────────────────────────────

class QuestradeSession:
    """
    Gère l'authentification OAuth2 et le renouvellement automatique
    de l'access token (expire après 30 minutes).
    """

    def __init__(self, refresh_token: str):
        self.refresh_token = refresh_token
        self.access_token = None
        self.api_server = None
        self._authenticate()

    def _authenticate(self):
        """Échange le refresh token contre un access token."""
        print("\n🔐 Authentification Questrade...")
        url = f"https://login.questrade.com/oauth2/token?grant_type=refresh_token&refresh_token={self.refresh_token}"
        
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            self.access_token = data["access_token"]
            self.api_server = data["api_server"].rstrip("/")
            # Le nouveau refresh token remplace l'ancien (usage unique)
            self.refresh_token = data["refresh_token"]
            expires_in = data.get("expires_in", 1800)
            
            print(f"   ✅ Authentifié — Token expire dans {expires_in // 60} minutes")
            print(f"   🌐 Serveur API : {self.api_server}")
            
        except requests.exceptions.HTTPError as e:
            print(f"   ❌ Erreur d'authentification : {e}")
            print("   → Vérifie que ton token est valide et non expiré (durée de vie : 7 jours)")
            raise

    def get(self, endpoint: str, params: dict = None) -> dict:
        """Requête GET authentifiée avec gestion d'erreurs."""
        url = f"{self.api_server}/v1/{endpoint.lstrip('/')}"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            
            if resp.status_code == 401:
                print("   ⚠️  Token expiré — renouvellement...")
                self._authenticate()
                headers["Authorization"] = f"Bearer {self.access_token}"
                resp = requests.get(url, headers=headers, params=params, timeout=15)
            
            resp.raise_for_status()
            return {"success": True, "data": resp.json(), "status_code": resp.status_code}
            
        except requests.exceptions.HTTPError as e:
            return {"success": False, "error": str(e), "status_code": resp.status_code,
                    "detail": resp.text[:500]}
        except requests.exceptions.Timeout:
            return {"success": False, "error": "Timeout (15s)", "status_code": None}
        except Exception as e:
            return {"success": False, "error": str(e), "status_code": None}


# ── Tests de capacités ─────────────────────────────────────────────────────────

def test_account_info(session: QuestradeSession) -> dict:
    """Test 1 : Informations du compte."""
    print("\n📋 Test 1 — Informations du compte")
    result = session.get("accounts")
    
    if result["success"]:
        accounts = result["data"].get("accounts", [])
        print(f"   ✅ {len(accounts)} compte(s) trouvé(s)")
        for acc in accounts:
            print(f"      → #{acc.get('number')} | Type: {acc.get('type')} | "
                  f"Statut: {acc.get('status')} | Primaire: {acc.get('isPrimary')}")
        return {"success": True, "accounts": accounts}
    else:
        print(f"   ❌ Échec : {result['error']}")
        return {"success": False, "error": result["error"]}


def test_symbol_resolution(session: QuestradeSession) -> dict:
    """Test 2 : Résolution des symbolId pour les 12 FNBs."""
    print("\n🔍 Test 2 — Résolution des 12 symboles TSX")
    symbol_map = {}
    failed = []
    
    for ticker in UNIVERSE:
        result = session.get("symbols/search", params={"prefix": ticker, "offset": 0})
        
        if result["success"]:
            symbols = result["data"].get("symbols", [])
            # Cherche la correspondance exacte
            match = next((s for s in symbols if s.get("symbol") == ticker), None)
            
            if match:
                symbol_map[ticker] = {
                    "symbolId": match.get("symbolId"),
                    "description": match.get("description", ""),
                    "currency": match.get("currency", ""),
                    "listingExchange": match.get("listingExchange", ""),
                    "securityType": match.get("securityType", ""),
                    "prevDayClosePrice": match.get("prevDayClosePrice"),
                }
                print(f"   ✅ {ticker:<10} ID: {match.get('symbolId'):<8} "
                      f"| {match.get('description', '')[:40]}")
            else:
                failed.append(ticker)
                print(f"   ⚠️  {ticker:<10} Aucune correspondance exacte — résultats: "
                      f"{[s.get('symbol') for s in symbols[:3]]}")
        else:
            failed.append(ticker)
            print(f"   ❌ {ticker:<10} Erreur: {result['error']}")
        
        time.sleep(0.3)  # Respecter les rate limits
    
    print(f"\n   → {len(symbol_map)}/12 symboles résolus, {len(failed)} échecs")
    return {"success": len(failed) == 0, "symbol_map": symbol_map, "failed": failed}


def test_l1_quotes(session: QuestradeSession, symbol_map: dict) -> dict:
    """Test 3 : Quotes L1 en temps réel pour les 12 FNBs."""
    print("\n📈 Test 3 — Quotes L1 (prix en temps réel)")
    
    resolved = {k: v for k, v in symbol_map.items() if "symbolId" in v}
    if not resolved:
        print("   ❌ Aucun symbolId disponible — test ignoré")
        return {"success": False, "error": "Aucun symbolId"}
    
    ids = ",".join(str(v["symbolId"]) for v in resolved.values())
    result = session.get(f"markets/quotes/{ids}")
    
    quotes_info = {}
    if result["success"]:
        quotes = result["data"].get("quotes", [])
        print(f"   ✅ {len(quotes)} quotes reçus")
        
        for q in quotes:
            ticker = q.get("symbol", "?")
            bid = q.get("bidPrice")
            ask = q.get("askPrice")
            last = q.get("lastTradePrice")
            volume = q.get("volume")
            spread_pct = ((ask - bid) / ((ask + bid) / 2) * 100) if bid and ask and (bid + ask) > 0 else None
            
            quotes_info[ticker] = {
                "bid": bid, "ask": ask, "last": last,
                "volume": volume, "spread_pct": round(spread_pct, 4) if spread_pct else None,
                "isHalted": q.get("isHalted"),
            }
            spread_str = f"{spread_pct:.3f}%" if spread_pct else "N/A"
            print(f"   ✅ {ticker:<10} Last: {last:<10} Bid: {bid:<10} Ask: {ask:<10} "
                  f"Spread: {spread_str:<10} Vol: {volume}")
        
        return {"success": True, "quotes": quotes_info}
    else:
        print(f"   ❌ Échec : {result['error']}")
        if result.get("detail"):
            print(f"      Détail : {result['detail']}")
        return {"success": False, "error": result["error"]}


def test_historical_daily(session: QuestradeSession, symbol_map: dict) -> dict:
    """Test 4 : Données historiques quotidiennes (65 jours pour amorcer z-score 60j)."""
    print("\n📅 Test 4 — Données historiques quotidiennes (65 jours)")
    
    # Test sur XIU.TO d'abord, puis échantillon de 3 autres
    test_symbols = ["XIU.TO", "XEG.TO", "ZAG.TO", "XGD.TO"]
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=90)  # Marge pour avoir 65 jours de bourse
    
    results = {}
    for ticker in test_symbols:
        if ticker not in symbol_map:
            continue
        
        symbol_id = symbol_map[ticker]["symbolId"]
        params = {
            "startTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S-00:00"),
            "endTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S-00:00"),
            "interval": "OneDay",
        }
        
        result = session.get(f"markets/candles/{symbol_id}", params=params)
        
        if result["success"]:
            candles = result["data"].get("candles", [])
            if candles:
                first_date = candles[0].get("start", "")[:10]
                last_date = candles[-1].get("start", "")[:10]
                # Vérifie la complétude des données
                has_volume = all(c.get("volume") is not None for c in candles)
                has_ohlc = all(c.get("open") and c.get("close") for c in candles)
                
                results[ticker] = {
                    "success": True,
                    "candle_count": len(candles),
                    "first_date": first_date,
                    "last_date": last_date,
                    "has_volume": has_volume,
                    "has_ohlc": has_ohlc,
                    "sample": candles[-1],  # Dernière bougie comme référence
                }
                status = "✅" if len(candles) >= 60 else "⚠️ "
                print(f"   {status} {ticker:<10} {len(candles)} bougies | "
                      f"{first_date} → {last_date} | "
                      f"OHLC: {'✓' if has_ohlc else '✗'} | Vol: {'✓' if has_volume else '✗'}")
            else:
                results[ticker] = {"success": False, "error": "Aucune bougie retournée"}
                print(f"   ⚠️  {ticker:<10} Aucune donnée retournée")
        else:
            results[ticker] = {"success": False, "error": result["error"]}
            print(f"   ❌ {ticker:<10} Erreur: {result['error']}")
        
        time.sleep(0.3)
    
    return {"success": all(r.get("success") for r in results.values()), "results": results}


def test_intraday_candles(session: QuestradeSession, symbol_map: dict) -> dict:
    """Test 5 : Candles intraday 5 minutes — données récentes."""
    print("\n⏱️  Test 5 — Candles intraday 5 minutes (3 derniers jours ouvrables)")
    
    # XIU.TO comme test représentatif
    ticker = "XIU.TO"
    if ticker not in symbol_map:
        print(f"   ❌ {ticker} non résolu — test ignoré")
        return {"success": False}
    
    symbol_id = symbol_map[ticker]["symbolId"]
    end_dt = datetime.now(timezone.utc)
    # 3 jours pour avoir au moins 1 journée de bourse complète
    start_dt = end_dt - timedelta(days=5)
    
    params = {
        "startTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S-00:00"),
        "endTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S-00:00"),
        "interval": "FiveMinutes",
    }
    
    result = session.get(f"markets/candles/{symbol_id}", params=params)
    
    if result["success"]:
        candles = result["data"].get("candles", [])
        if candles:
            first_dt = candles[0].get("start", "")
            last_dt = candles[-1].get("start", "")
            # Une journée de bourse = ~78 bougies de 5 min (9h30-16h00)
            expected_per_day = 78
            trading_days_est = len(candles) / expected_per_day
            
            print(f"   ✅ {ticker} — {len(candles)} bougies 5 min")
            print(f"      Première : {first_dt[:19]}")
            print(f"      Dernière : {last_dt[:19]}")
            print(f"      Équivalent ~{trading_days_est:.1f} journées de bourse")
            print(f"      Exemple dernière bougie : {candles[-1]}")
            
            return {
                "success": True,
                "ticker": ticker,
                "candle_count": len(candles),
                "first": first_dt,
                "last": last_dt,
                "sample_last": candles[-1],
                "intraday_available": True,
            }
        else:
            print(f"   ⚠️  Aucune bougie 5 min retournée — marché peut-être fermé")
            return {"success": True, "intraday_available": False,
                    "note": "Aucune bougie — vérifier pendant les heures de marché"}
    else:
        print(f"   ❌ Erreur : {result['error']}")
        if result.get("detail"):
            print(f"      Détail : {result['detail']}")
        return {"success": False, "error": result["error"]}


def test_order_capabilities(session: QuestradeSession) -> dict:
    """
    Test 6 : Vérification de l'accès à l'exécution d'ordres.
    
    Note : L'API Questrade limite l'exécution d'ordres aux 'partner developers'.
    Ce test confirme ce que la documentation annonce — il ne tente PAS de placer
    un ordre réel, il vérifie seulement si l'endpoint est accessible.
    """
    print("\n🔒 Test 6 — Accès exécution d'ordres (lecture seule du endpoint)")
    
    # On récupère la liste des comptes pour avoir un account_id
    acc_result = session.get("accounts")
    if not acc_result["success"] or not acc_result["data"].get("accounts"):
        return {"success": False, "can_execute": False, "error": "Compte non accessible"}
    
    account_id = acc_result["data"]["accounts"][0]["number"]
    
    # Tenter de lire les ordres existants (GET, pas POST — 100% sans risque)
    result = session.get(f"accounts/{account_id}/orders")
    
    if result["success"]:
        orders = result["data"].get("orders", [])
        print(f"   ✅ Endpoint ordres accessible en lecture ({len(orders)} ordre(s) existant(s))")
        print(f"   ℹ️  Note : La LECTURE des ordres est disponible.")
        print(f"   ℹ️  Note : L'EXÉCUTION (POST) nécessite un statut 'partner developer'.")
        print(f"   → Pour TMX v2 paper trading : simulateur JSON = plan A confirmé.")
        return {
            "success": True,
            "can_read_orders": True,
            "can_execute_orders": False,  # Confirmé par la doc officielle
            "note": "Exécution réservée aux partner developers. Simulateur JSON = plan A.",
        }
    elif result.get("status_code") == 403:
        print(f"   🔒 Endpoint ordres non autorisé (403) — confirmé : exécution non disponible")
        return {"success": True, "can_read_orders": False, "can_execute_orders": False}
    else:
        print(f"   ❌ Erreur inattendue : {result['error']}")
        return {"success": False, "error": result["error"]}


# ── Rapport final ──────────────────────────────────────────────────────────────

def generate_report(results: dict) -> dict:
    """Génère le rapport de capacités JSON."""
    
    now = datetime.now().isoformat()
    
    # Compte les symboles résolus
    symbol_map = results.get("symbols", {}).get("symbol_map", {})
    resolved_count = len(symbol_map)
    
    # Capacités confirmées
    capabilities = {
        "authentication": results.get("account", {}).get("success", False),
        "symbol_resolution": resolved_count == 12,
        "l1_quotes_realtime": results.get("quotes", {}).get("success", False),
        "historical_daily_candles": results.get("historical_daily", {}).get("success", False),
        "intraday_5min_candles": results.get("intraday", {}).get("success", False),
        "order_execution_api": False,  # Confirmé par doc : partner developers seulement
    }
    
    # Recommandations architecture Phase 1
    architecture_decision = {
        "data_source": "Questrade API (quotes L1 + candles OHLC)",
        "vix_source": "yfinance (^VIX) — gratuit, temps réel",
        "paper_trading": "Simulateur JSON interne — plan A permanent (pas de fallback nécessaire)",
        "historical_bootstrap": (
            f"{min(c.get('candle_count', 0) for c in results.get('historical_daily', {}).get('results', {}).values() if c.get('success'))} jours disponibles"
            if results.get("historical_daily", {}).get("results") else "À vérifier"
        ),
        "intraday_confirmed": results.get("intraday", {}).get("intraday_available", False),
    }
    
    report = {
        "generated_at": now,
        "tmx_version": "v2",
        "phase": "Phase 1 — Semaine 1",
        "capabilities": capabilities,
        "architecture_decision": architecture_decision,
        "symbol_map": symbol_map,
        "detailed_results": {
            "account": results.get("account", {}),
            "quotes_sample": {k: v for k, v in results.get("quotes", {}).get("quotes", {}).items()},
            "historical_daily": results.get("historical_daily", {}),
            "intraday": results.get("intraday", {}),
            "order_access": results.get("orders", {}),
        },
    }
    
    return report


def print_summary(report: dict):
    """Affiche un résumé lisible du rapport."""
    print("\n" + "=" * 65)
    print("  TMX v2 — RAPPORT DE CAPACITÉS QUESTRADE API")
    print("=" * 65)
    
    caps = report["capabilities"]
    icons = {True: "✅", False: "❌"}
    
    print("\n  CAPACITÉS CONFIRMÉES :")
    print(f"  {icons[caps['authentication']]}  Authentification OAuth2")
    print(f"  {icons[caps['symbol_resolution']]}  Résolution des 12 symboles TSX")
    print(f"  {icons[caps['l1_quotes_realtime']]}  Quotes L1 temps réel")
    print(f"  {icons[caps['historical_daily_candles']]}  Candles historiques quotidiens")
    print(f"  {icons[caps['intraday_5min_candles']]}  Candles intraday 5 minutes")
    print(f"  {icons[caps['order_execution_api']]}  Exécution d'ordres (partner seulement)")
    
    arch = report["architecture_decision"]
    print("\n  DÉCISIONS ARCHITECTURALES PHASE 1 :")
    print(f"  → Source données marché : {arch['data_source']}")
    print(f"  → Source VIX           : {arch['vix_source']}")
    print(f"  → Paper trading        : {arch['paper_trading']}")
    print(f"  → Bootstrap historique : {arch['historical_bootstrap']}")
    
    # Spreads bid-ask si disponibles
    quotes = report["detailed_results"].get("quotes_sample", {})
    if quotes:
        print("\n  SPREADS BID-ASK OBSERVÉS (coûts réels vs PRD) :")
        for ticker, q in quotes.items():
            spread = q.get("spread_pct")
            if spread:
                flag = "✅" if spread < 0.10 else "⚠️ "
                print(f"  {flag} {ticker:<10} {spread:.3f}%  (PRD estime 0.05-0.10%)")
    
    print("\n" + "=" * 65)


# ── Point d'entrée ─────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  TMX v2 — Questrade API Explorer")
    print("  Phase 1 : Vérification des capacités (lecture seule)")
    print("=" * 65)
    
    # Chargement du token depuis .env
    load_dotenv()
    refresh_token = os.getenv("QUESTRADE_REFRESH_TOKEN")
    
    if not refresh_token:
        print("\n❌ QUESTRADE_REFRESH_TOKEN manquant dans le fichier .env")
        print("\nMarche à suivre :")
        print("  1. Connecte-toi à Questrade")
        print("  2. Menu → API Centre → Personal apps")
        print("  3. Clique sur 'New manual authorization' → 'Generate new token'")
        print("  4. Copie le token dans un fichier .env :")
        print("     QUESTRADE_REFRESH_TOKEN=ton_token_ici")
        return
    
    # Lancement des tests
    all_results = {}
    
    try:
        session = QuestradeSession(refresh_token)
        
        all_results["account"] = test_account_info(session)
        time.sleep(0.5)
        
        symbol_result = test_symbol_resolution(session)
        all_results["symbols"] = symbol_result
        symbol_map = symbol_result.get("symbol_map", {})
        time.sleep(0.5)
        
        all_results["quotes"] = test_l1_quotes(session, symbol_map)
        time.sleep(0.5)
        
        all_results["historical_daily"] = test_historical_daily(session, symbol_map)
        time.sleep(0.5)
        
        all_results["intraday"] = test_intraday_candles(session, symbol_map)
        time.sleep(0.5)
        
        all_results["orders"] = test_order_capabilities(session)
        
    except Exception as e:
        print(f"\n❌ Erreur critique : {e}")
        raise
    
    # Génération du rapport
    report = generate_report(all_results)
    print_summary(report)
    
    # Sauvegarde JSON
    output_path = Path("questrade_capabilities.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n  📄 Rapport complet sauvegardé : {output_path.resolve()}")
    print(f"  🕐 Généré le : {report['generated_at']}")
    print()


if __name__ == "__main__":
    main()
