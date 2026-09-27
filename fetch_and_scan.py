"""
fetch_and_scan.py — Script conçu pour tourner sur GitHub Actions (cloud, gratuit).
Récupère les bougies fraîches via l'API Twelve Data (REST, pas de blocage
Cloudflare connu contrairement à l'ancienne API Deriv), scanne Shadow
Retracement, maintient un état persistant (state.json) pour le cycle de vie
des setups ET un historique de prix persistant (history_*.csv) pour ne
jamais redemander des données déjà connues -- seulement les nouvelles
bougies depuis la dernière exécution.

Secrets requis :
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TWELVEDATA_API_KEY, GROQ_API_KEY (optionnel)
"""
import os
import requests
import pandas as pd
from shadow_retracement_ai import scan_active_setups, format_signal, ASSET_CONFIG
import state as st
import history as hist

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
TWELVEDATA_API_KEY = os.environ["TWELVEDATA_API_KEY"]

TWELVEDATA_BASE_URL = "https://api.twelvedata.com/time_series"
TWELVEDATA_SYMBOLS = {"XAUUSD": "XAU/USD", "EURUSD": "EUR/USD", "BTCUSD": "BTC/USD"}
TWELVEDATA_INTERVALS = {"H1": "1h", "M1": "1min"}


def _parse_td_values(values):
    rows = [{
        "datetime": pd.to_datetime(v["datetime"]),
        "open": float(v["open"]), "high": float(v["high"]),
        "low": float(v["low"]), "close": float(v["close"]),
        "volume": float(v.get("volume") or 0),
    } for v in values]
    return pd.DataFrame(rows).set_index("datetime")


def _twelvedata_request(params):
    headers = {"Authorization": f"apikey {TWELVEDATA_API_KEY.strip()}"}
    r = requests.get(TWELVEDATA_BASE_URL, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("status") == "error":
        raise RuntimeError(f"Erreur API Twelve Data: {data.get('message')}")
    return data.get("values", [])


def fetch_twelvedata_bootstrap(symbol, interval, count):
    """Récupère les `count` dernières bougies (premier run, aucun historique local)."""
    values = _twelvedata_request({
        "symbol": symbol, "interval": interval,
        "outputsize": min(count, 5000), "order": "asc",
    })
    if not values:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    return _parse_td_values(values)


def fetch_twelvedata_since(symbol, interval, last_epoch):
    """Récupère uniquement les bougies apparues depuis last_epoch (exclu)."""
    start_date = pd.Timestamp(last_epoch, unit="s") + pd.Timedelta(seconds=1)
    values = _twelvedata_request({
        "symbol": symbol, "interval": interval,
        "start_date": start_date.strftime("%Y-%m-%d %H:%M:%S"),
        "order": "asc", "timezone": "UTC",
    })
    print(f"  -> fetch_twelvedata_since({symbol}, {interval}): {len(values)} bougie(s) reçue(s) depuis {start_date}")
    if not values:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    return _parse_td_values(values)


def fetch_market_data(asset, symbol):
    """
    Utilise l'historique persistant : bootstrap complet au premier run,
    puis uniquement les nouvelles bougies ensuite. Retourne (H1, M1) prêts
    à l'emploi pour la détection.
    """
    h1 = hist.update_history(
        asset, "H1",
        fetch_since_fn=lambda last_epoch: fetch_twelvedata_since(symbol, TWELVEDATA_INTERVALS["H1"], last_epoch),
        fetch_bootstrap_fn=lambda count: fetch_twelvedata_bootstrap(symbol, TWELVEDATA_INTERVALS["H1"], count),
    )
    m1_recent = hist.update_history(
        asset, "M1",
        fetch_since_fn=lambda last_epoch: fetch_twelvedata_since(symbol, TWELVEDATA_INTERVALS["M1"], last_epoch),
        fetch_bootstrap_fn=lambda count: fetch_twelvedata_bootstrap(symbol, TWELVEDATA_INTERVALS["M1"], count),
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
                "model": "openai/gpt-oss-120b",
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
    from datetime import datetime, timezone
    if datetime.now(timezone.utc).weekday() >= 5:  # 5=samedi, 6=dimanche
        print("Marché fermé le week-end, scan ignoré (garde-fou indépendant du déclencheur externe).")
        return

    state = st.load_state()

    for asset, symbol in TWELVEDATA_SYMBOLS.items():
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
