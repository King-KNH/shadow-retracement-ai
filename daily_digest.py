"""
daily_digest.py — Tourne une fois par jour à 12h heure du Cameroun (11h UTC).
En semaine : court commentaire sur le contexte de marché actuel.
Le week-end (marché fermé) : réflexion plus approfondie, pistes d'optimisation
à explorer, sans requête de données de marché (inutile, marché fermé).
"""
import os
import requests
from datetime import datetime, timezone

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

STRATEGY_CONTEXT = """Shadow Retracement : stratégie de retracement vers order block/zone
d'accumulation en discount (achat) ou premium (vente), confirmée par POC (profil temps-prix),
avec TP sur ancien plus haut/bas de structure. Validée sur XAUUSD (R:R>=2.0) et EURUSD
(stop>=10 pips, R:R>=2.5), sur 2023-2026, avec spread et slippage réalistes inclus."""


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=15)
        r.raise_for_status()
        print("Digest envoyé avec succès.")
    except Exception as e:
        print(f"ERREUR: échec d'envoi du digest ({e})")


def ask_groq(prompt):
    if not GROQ_API_KEY:
        return "(Avis IA indisponible : GROQ_API_KEY non configurée)"
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY.strip()}"},
            json={
                "model": "openai/gpt-oss-120b",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 350,
                "temperature": 0.5,
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        detail = getattr(e, "response", None)
        detail_text = detail.text[:300] if detail is not None else str(e)
        return f"(Avis IA indisponible : {detail_text})"


def weekday_digest():
    """Jour de semaine : court commentaire sur le contexte de marché."""
    prompt = f"""{STRATEGY_CONTEXT}

C'est un jour de semaine, le marché est ouvert. En 3-4 phrases maximum,
donne un point de vue général et personnel sur le contexte de marché actuel
pour XAUUSD et EURUSD (tendance générale, facteurs macro à surveiller cette semaine),
et un mot d'encouragement ou de vigilance pour le trader. Reste concis, en français."""

    commentary = ask_groq(prompt)
    return f"👋 Signe de vie quotidien — {datetime.now(timezone.utc).strftime('%d/%m/%Y')}\n\n{commentary}"


def weekend_digest():
    """Week-end : marché fermé, pas de requête de données. Réflexion/optimisation."""
    prompt = f"""{STRATEGY_CONTEXT}

C'est le week-end, le marché est fermé, aucune donnée de prix fraîche n'est disponible.
Prends ce temps pour une réflexion stratégique : propose UNE piste concrète d'amélioration
ou de nouveau concept de trading à tester sur Shadow Retracement (variable mathématique,
filtre supplémentaire, ou concept d'analyse technique non encore exploré). Explique en
3-5 phrases pourquoi cette piste pourrait être intéressante, en français. Sois concret,
pas vague — nomme le concept précisément pour qu'il puisse être testé plus tard."""

    reflection = ask_groq(prompt)
    return f"🧠 Réflexion du week-end — {datetime.now(timezone.utc).strftime('%d/%m/%Y')}\n\n{reflection}\n\n(Piste à valider par backtest avant adoption — aucune modification automatique de la stratégie)"


if __name__ == "__main__":
    now_utc = datetime.now(timezone.utc)
    is_weekend = now_utc.weekday() >= 5  # 5=samedi, 6=dimanche

    message = weekend_digest() if is_weekend else weekday_digest()
    print(message)
    send_telegram(message)
