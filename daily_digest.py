"""
daily_digest.py — Tourne une fois par jour à 12h heure du Cameroun (11h UTC).
En semaine : court commentaire sur le contexte de marché actuel.
Le week-end (marché fermé) : lecture technique de la structure actuelle par
paire (basée sur l'historique déjà sauvegardé, aucune nouvelle requête au
marché) + une piste d'amélioration à explorer.
"""
import os
import sys
import requests
from datetime import datetime, timezone

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

STRATEGY_CONTEXT = """Shadow Retracement : stratégie de retracement vers order block/zone
d'accumulation en discount (achat) ou premium (vente), confirmée par POC (profil temps-prix),
avec TP sur ancien plus haut/bas de structure. Validée sur XAUUSD (R:R>=2.0) et EURUSD
(stop>=10 pips, R:R>=2.5), sur 2023-2026, avec spread et slippage réalistes inclus.

CONTRAINTE DE DONNÉES IMPORTANTE, à respecter strictement : le Forex et l'or au comptant
(XAUUSD) sont des marchés décentralisés SANS volume réel disponible (aucune bourse centrale
ne le mesure). Ne propose JAMAIS un concept basé sur du vrai volume échangé, du VWAP, ou tout
indicateur nécessitant un vrai volume (OBV, volume profile classique, etc.) — cette donnée
n'existe tout simplement pas ici. Le seul proxy disponible est un profil temps-prix (compter
le temps passé à chaque niveau de prix via les bougies M1), déjà utilisé pour le POC. Toute
proposition doit se baser uniquement sur le prix (OHLC), la structure, ou ce proxy temps-prix."""


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
                "max_tokens": 500,
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
pour XAUUSD, EURUSD et BTCUSD (tendance générale, facteurs macro à surveiller cette semaine),
et un mot d'encouragement ou de vigilance pour le trader. Reste concis, en français."""

    commentary = ask_groq(prompt)
    return f"👋 Signe de vie quotidien — {datetime.now(timezone.utc).strftime('%d/%m/%Y')}\n\n{commentary}"


def build_weekly_technical_read():
    """
    Relit l'historique déjà sauvegardé (par le dernier scan de vendredi) et
    fait tourner le moteur de détection réel, SANS interroger le marché.
    Retourne un résumé factuel par actif (biais, setups actifs, distances) --
    des données calculées, pas inventées par l'IA.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import history as hist
        from shadow_retracement_ai import scan_active_setups
    except Exception as e:
        return None, f"Lecture de l'historique impossible ({e})"

    summary_lines = []
    for asset in ["XAUUSD", "EURUSD", "BTCUSD"]:
        h1 = hist.load_history(asset, "H1")
        m1 = hist.load_history(asset, "M1")
        if h1 is None or m1 is None or len(h1) < 50 or len(m1) < 50:
            summary_lines.append(f"{asset}: historique local insuffisant (pas encore de scan complet effectué).")
            continue

        try:
            signals = scan_active_setups(m1, asset, h1_df=h1)
        except Exception as e:
            summary_lines.append(f"{asset}: erreur lors du calcul des setups ({e})")
            continue

        if not signals:
            summary_lines.append(f"{asset}: aucune zone Shadow Retracement valide identifiée en clôture de vendredi.")
        else:
            for sig in signals:
                summary_lines.append(
                    f"{asset} {sig['direction']} — entrée {sig['entry']:.5f}, stop {sig['sl']:.5f}, "
                    f"TP {sig['tp']:.5f}, R:R {sig['rr_ratio']}, distance au prix de clôture: "
                    f"{sig['distance_to_entry_pips']} pips, statut: {sig['status']}"
                )

    return "\n".join(summary_lines), None


def weekend_digest():
    """
    Week-end : pas de nouvelle requête au marché. Deux parties :
    1. Lecture technique factuelle par paire (basée sur l'historique déjà en mémoire)
    2. Une piste d'amélioration à explorer (comme avant)
    """
    technical_summary, error = build_weekly_technical_read()

    if technical_summary:
        prep_prompt = f"""{STRATEGY_CONTEXT}

Voici l'état RÉEL et CALCULÉ (pas halluciné) des zones Shadow Retracement à la
clôture de vendredi, par paire :

{technical_summary}

Rédige une préparation de semaine en français, structurée par paire (XAUUSD puis
EURUSD), en 2-3 phrases par paire : mentionne les zones actives identifiées
ci-dessus (niveaux exacts), et ce à quoi il faut être attentif au retour du marché.
IMPORTANT : ne prédis JAMAIS la direction future du prix — décris uniquement ce
que la structure calculée montre actuellement, pas un pronostic. Si aucune zone
n'est active pour une paire, dis-le simplement."""
        weekly_prep = ask_groq(prep_prompt)
    else:
        weekly_prep = f"(Préparation de semaine indisponible : {error})"

    idea_prompt = f"""{STRATEGY_CONTEXT}

Propose UNE piste concrète d'amélioration ou de nouveau concept de trading à
tester sur Shadow Retracement (variable mathématique, filtre supplémentaire,
ou concept d'analyse technique non encore exploré, respectant la contrainte
de données ci-dessus). Explique en 3-4 phrases pourquoi cette piste pourrait
être intéressante, en français. Sois concret, nomme le concept précisément."""
    idea = ask_groq(idea_prompt)

    date_str = datetime.now(timezone.utc).strftime('%d/%m/%Y')
    return (
        f"🧠 Préparation de la semaine — {date_str}\n\n{weekly_prep}\n\n"
        f"---\n💡 Piste d'amélioration à explorer\n\n{idea}\n\n"
        f"(Lecture technique basée sur des données réelles calculées. Piste d'amélioration "
        f"à valider par backtest avant adoption — aucune modification automatique de la stratégie.)"
    )


if __name__ == "__main__":
    now_utc = datetime.now(timezone.utc)
    is_weekend = now_utc.weekday() >= 5  # 5=samedi, 6=dimanche

    message = weekend_digest() if is_weekend else weekday_digest()
    print(message)
    send_telegram(message)
