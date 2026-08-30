"""
state.py — Mémoire persistante entre les exécutions du scan.
Le fichier state.json est lu au début, mis à jour, puis recommité dans le
dépôt à la fin de l'exécution (voir scan.yml). C'est ce qui donne à l'IA
une continuité : elle sait quels setups elle a déjà vus, à quel stade
(détecté, déclenché, breakeven, clôturé) sans tout redécouvrir à chaque fois.
"""
import json
import os

STATE_FILE = "state.json"


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"tracked_setups": {}}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)


def setup_id(asset, sig):
    """Identifiant unique et stable d'un setup, basé sur sa zone (pas sur l'heure du scan)."""
    return f"{asset}_{sig['direction']}_{sig['entry']:.5f}_{sig['sl']:.5f}"


def get_or_create(state, sid, sig, asset):
    if sid not in state["tracked_setups"]:
        state["tracked_setups"][sid] = {
            "asset": asset, "direction": sig["direction"],
            "entry": sig["entry"], "sl": sig["sl"], "tp": sig["tp"],
            "status": "detected", "notified_detected": False,
        }
    return state["tracked_setups"][sid]


def update_status(record, current_price, breakeven_applied=False):
    """
    Met à jour le statut d'un setup suivi selon le prix actuel.
    Retourne le nouveau statut SI il a changé (sinon None -> pas de notification).
    """
    old_status = record["status"]
    entry, sl, tp, direction = record["entry"], record["sl"], record["tp"], record["direction"]

    if old_status == "detected":
        in_zone = (min(entry, sl) <= current_price <= max(entry, sl))
        if in_zone:
            record["status"] = "triggered"
            return "triggered"

    elif old_status == "triggered":
        if direction == "bullish":
            if current_price <= sl:
                record["status"] = "closed_loss"
                return "closed_loss"
            if current_price >= tp:
                record["status"] = "closed_win"
                return "closed_win"
        else:
            if current_price >= sl:
                record["status"] = "closed_loss"
                return "closed_loss"
            if current_price <= tp:
                record["status"] = "closed_win"
                return "closed_win"

    return None


def prune_closed(state, keep_last_n=200):
    """Évite que state.json grossisse indéfiniment : purge les setups clôturés anciens."""
    tracked = state["tracked_setups"]
    closed = {k: v for k, v in tracked.items() if v["status"] in ("closed_win", "closed_loss")}
    active = {k: v for k, v in tracked.items() if v["status"] not in ("closed_win", "closed_loss")}
    if len(closed) > keep_last_n:
        closed = dict(list(closed.items())[-keep_last_n:])
    state["tracked_setups"] = {**active, **closed}
