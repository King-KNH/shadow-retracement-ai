"""
history.py — Historique de prix persistant par actif/timeframe.
Premier run : récupère la fenêtre complète (bootstrap).
Runs suivants : ne demande que les bougies nouvelles depuis la dernière
bougie connue, les ajoute, et purge les plus anciennes pour garder une
fenêtre glissante constante. Fichiers CSV recommités par le workflow.
"""
import os
import pandas as pd

WINDOWS = {
    "H1": {"granularity": 3600, "keep_days": 60, "bootstrap_count": 1440},
    "M1": {"granularity": 60, "keep_days": 4, "bootstrap_count": 5000},
}


def history_path(asset, tf):
    return f"history_{asset}_{tf}.csv"


def load_history(asset, tf):
    path = history_path(asset, tf)
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path, index_col="datetime", parse_dates=True)
    return df if len(df) > 0 else None


def save_history(asset, tf, df):
    df.to_csv(history_path(asset, tf))


def trim_window(df, tf):
    keep_days = WINDOWS[tf]["keep_days"]
    cutoff = df.index.max() - pd.Timedelta(days=keep_days)
    return df[df.index >= cutoff]


def update_history(asset, tf, fetch_since_fn, fetch_bootstrap_fn):
    """
    fetch_since_fn(last_epoch) -> DataFrame des bougies depuis last_epoch (exclu)
    fetch_bootstrap_fn(count) -> DataFrame des `count` dernières bougies (premier run)
    """
    existing = load_history(asset, tf)

    if existing is None:
        print(f"{asset} {tf}: aucun historique local, bootstrap complet.")
        fresh = fetch_bootstrap_fn(WINDOWS[tf]["bootstrap_count"])
        save_history(asset, tf, fresh)
        return fresh

    last_ts = existing.index.max()
    last_epoch = int(last_ts.timestamp())
    print(f"{asset} {tf}: historique local jusqu'à {last_ts}, récupération des nouvelles bougies uniquement.")

    new_candles = fetch_since_fn(last_epoch)
    if new_candles is not None and len(new_candles) > 0:
        combined = pd.concat([existing, new_candles])
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    else:
        combined = existing

    combined = trim_window(combined, tf)
    save_history(asset, tf, combined)
    print(f"{asset} {tf}: {len(new_candles) if new_candles is not None else 0} nouvelle(s) bougie(s), total conservé: {len(combined)}")
    return combined
