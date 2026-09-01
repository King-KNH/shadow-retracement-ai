"""
fetch_and_scan.py — Script conçu pour tourner sur GitHub Actions (cloud, gratuit).
Récupère les bougies fraîches via l'API Deriv, scanne Shadow Retracement,
maintient un état persistant (state.json) pour le cycle de vie des setups
ET un historique de prix persistant (history_*.csv) pour ne jamais
redemander des données déjà connues -- seulement les nouvelles bougies
depuis la dernière exécution.

Secrets requis :
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GROQ_API_KEY (optionnel)
"""
import os
import json
import requests
import websocket
import pandas as pd
from shadow_retracement_ai import scan_active_setups, format_signal, ASSET_CONFIG
import state as st
import history as hist

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

DERIV_APP_ID = "1089"
DERIV_WS_URL = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
DERIV_SYMBOLS = {"XAUUSD": "frxXAUUSD", "EURUSD": "frxEURUSD"}


def _parse_candles(candles):
    rows = [{
        "datetime": pd.to_datetime(c["epoch"], unit="s"),
        "open": float(c["open"]), "high": float(c["high"]),
        "low": float(c["low"]), "close": float(c["close"]), "volume": 0
    } for c in candles]
    return pd.DataFrame(rows).set_index("datetime")


def fetch_deriv_bootstrap(symbol, granularity, count):
    """Récupère les `count` dernières bougies (premier run, aucun historique local)."""
    ws = websocket.create_connection(DERIV_WS_URL, timeout=30)
    try:
        request = {
            "ticks_history": symbol, "adjust_start_time": 1, "count": count,
            "end": "latest", "start": 1, "style": "candles", "granularity": granularity,
        }
        ws.send(json.dumps(request))
        response = json.loads(ws.recv())
        if "error" in response:
            raise RuntimeError(f"Erreur API Deriv (bootstrap): {response['error']['message']}")
        return _parse_candles(response["candles"])
    finally:
        ws.close()


def fetch_deriv_since(symbol, granularity, last_epoch):
    """Récupère uniquement les bougies apparues depuis last_epoch (exclu)."""
    ws = websocket.create_connection(DERIV_WS_URL, timeout=30)
    try:
        request = {
            "ticks_history": symbol, "adjust_start_time": 1,
            "end": "latest", "start": last_epoch + 1,
            "style": "candles", "granularity": granularity,
        }
        ws.send(json.dumps(request))
        response = json.loads(ws.recv())
        if "error" in response:
            raise RuntimeError(f"Erreur API Deriv (incrémental): {response['error']['message']}")
        candles = response.get("candles", [])
        if not candles:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        return _parse_candles(candles)
    finally:
        ws.close()


def fetch_market_data(asset, symbol):
    """
    Utilise l'historique persistant : bootstrap complet au premier run,
    puis uniquement les nouvelles bougies ensuite. Retourne (H1, M1) prêts
    à l'emploi pour la détection.
    """
    h1 = hist.update_history(
        asset, "H1",
        fetch_since_fn=lambda last_epoch: fetch_deriv_since(symbol, 3600, last_epoch),
        fetch_bootstrap_fn=lambda count: fetch_deriv_bootstrap(symbol, 3600, count),
    )
    m1_recent = hist.update_history(
        asset, "M1",
        fetch_since_fn=lambda last_epoch: fetch_deriv_since(symbol, 60, last_epoch),
        fetch_bootstrap_fn=lambda count: fetch_deriv_bootstrap(symbol, 60, count),
    )
    return h1, m1_recent


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=15)
        r.raise_for_status()
        print("Notification Telegram envoyée avec succès.")
    except Exception as e:
        print(f"ERREUR: échec d'envoi Telegram ({e}). Vérifie TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID.")


def ask_groq_judgment(asset, sig):
    if not GROQ_API_KEY:
        return None
    prompt = f"""Tu es un analyste trading expérimenté. Voici un setup détecté automatiquement :
Actif: {asset}
Direction: {sig['direction']}
Entrée: {sig['entry']:.5f}
Stop loss: {sig['sl']:.5f}
Take profit: {sig['tp']:.5f}
R:R: {sig['rr_ratio']}
Statut: {sig['status']}

En 2-3 phrases maximum, donne ton avis: ce setup te semble-t-il cohérent ?
Réponds en français, de façon concise."""
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY.strip()}"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 250,
                "temperature": 0.3,
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        detail = getattr(e, "response", None)
        detail_text = detail.text[:300] if detail is not None else str(e)
        print(f"Avis Groq indisponible ({detail_text}), notification envoyée sans jugement.")
        return None


def run():
    state = st.load_state()

    for asset, symbol in DERIV_SYMBOLS.items():
        try:
            h1, m1_recent = fetch_market_data(asset, symbol)
            print(f"{asset}: H1={len(h1)} bougies, M1={len(m1_recent)} bougies récentes")

            if len(h1) < 50 or len(m1_recent) < 50:
                print(f"{asset}: historique insuffisant pour une détection fiable ce cycle, on saute.")
                continue

            signals = scan_active_setups(m1_recent, asset, h1_df=h1)
            current_price = m1_recent["close"].iloc[-1]

            for sig in signals:
                sid = st.setup_id(asset, sig)
                record = st.get_or_create(state, sid, sig, asset)

                # Nouveau setup, jamais notifié ET assez proche du prix actuel pour être actionnable
                max_dist = ASSET_CONFIG[asset]["max_distance_pips"]
                close_enough = sig["distance_to_entry_pips"] <= max_dist

                if not record["notified_detected"] and close_enough:
                    text = format_signal(sig, asset)
                    judgment = ask_groq_judgment(asset, sig)
                    message = f"📡 Nouveau setup Shadow Retracement\n{text}"
                    if judgment:
                        message += f"\n🧠 Avis IA:\n{judgment}"
                    send_telegram(message)
                    record["notified_detected"] = True
                elif not record["notified_detected"]:
                    print(f"{asset}: setup trop éloigné ({sig['distance_to_entry_pips']} pips), pas encore notifié.")

                new_status = st.update_status(record, current_price)
                if new_status == "triggered":
                    send_telegram(f"✅ {asset} — Entrée déclenchée à {record['entry']:.5f}")
                elif new_status == "closed_win":
                    send_telegram(f"🎯 {asset} — Take Profit atteint ! ({record['tp']:.5f})")
                elif new_status == "closed_loss":
                    send_telegram(f"❌ {asset} — Stop Loss touché. ({record['sl']:.5f})")

            if not signals:
                print(f"{asset}: aucun setup actif détecté ce cycle.")

        except Exception as e:
            print(f"Erreur sur {asset}: {e}")

    st.prune_closed(state)
    st.save_state(state)


if __name__ == "__main__":
    run()
