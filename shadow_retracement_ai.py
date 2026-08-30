"""
IA Shadow Retracement — Moteur de scan autonome
=================================================
Prend en entrée un CSV de bougies M1 récentes (export MT5 ou autre),
reconstruit H1/M15/M5, détecte les setups actifs, et génère un signal
lisible si un setup valide est en formation.

Usage : python3 shadow_retracement_ai.py <fichier_M1.csv> <ASSET>
Exemple : python3 shadow_retracement_ai.py latest_xauusd.csv XAUUSD
"""
import pandas as pd
import numpy as np
import sys
from structure_detection import detect_swings, get_structure_points
from detect_setups import detect_setups

# Configurations validées par actif (issues du backtest)
ASSET_CONFIG = {
    'XAUUSD': {'pip_size': 0.01, 'spread_pips': 25, 'sl_slippage_pips': 12,
               'min_rr': 2.0, 'min_stop_pips': 0},
    'EURUSD': {'pip_size': 0.0001, 'spread_pips': 1.2, 'sl_slippage_pips': 0.6,
               'min_rr': 2.5, 'min_stop_pips': 10},
}


def load_m1(csv_path):
    df = pd.read_csv(csv_path, sep=';', header=None,
                      names=['datetime', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['datetime'], format='%Y%m%d %H%M%S')
    df = df.sort_values('datetime').drop_duplicates(subset='datetime').set_index('datetime')
    return df


def aggregate(m1_df):
    agg = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
    return {
        'M5': m1_df.resample('5min').agg(agg).dropna(subset=['open']),
        'M15': m1_df.resample('15min').agg(agg).dropna(subset=['open']),
        'H1': m1_df.resample('1h').agg(agg).dropna(subset=['open']),
    }


def scan_active_setups(m1_df, asset, h1_df=None):
    """
    h1_df : si fourni (cas du scan cloud, H1 récupéré séparément sur 60 jours),
    utilisé directement pour une structure fiable. Sinon (cas fichier local,
    ex: tests), H1 est reconstruit depuis m1_df comme avant.
    """
    cfg = ASSET_CONFIG[asset]
    if h1_df is None:
        tf = aggregate(m1_df)
        h1_df = tf['H1']
    setups = detect_setups(h1_df, m1_df, lookback=5, poc_bins=50)
    valid = setups[setups['valid_pd_filter']].copy()

    pip = cfg['pip_size']
    valid['risk_pips'] = (valid['ob_high'] - valid['ob_low']) / pip
    valid['reward_pips'] = (valid['target_price'] - valid[['ob_high', 'ob_low']].mean(axis=1)).abs() / pip
    valid['rr_ratio'] = valid['reward_pips'] / valid['risk_pips']

    filtered = valid[
        (valid['rr_ratio'] >= cfg['min_rr']) &
        (valid['risk_pips'] >= cfg['min_stop_pips'])
    ].copy()

    # Ne garder que les setups formés récemment (derniers 5 jours) -> zones encore actives
    recent_cutoff = m1_df.index.max() - pd.Timedelta(days=5)
    active = filtered[filtered['leg_end'] >= recent_cutoff]

    # Vérifier si le prix actuel est déjà entré dans la zone ou en approche
    current_price = m1_df['close'].iloc[-1]
    signals = []
    for _, s in active.iterrows():
        direction = s['direction']
        entry = s['ob_high'] if direction == 'bullish' else s['ob_low']
        sl = s['ob_low'] if direction == 'bullish' else s['ob_high']
        tp = s['target_price']

        distance_pips = abs(current_price - entry) / pip
        in_zone = s['ob_low'] <= current_price <= s['ob_high']

        signals.append({
            'direction': direction, 'entry': entry, 'sl': sl, 'tp': tp,
            'rr_ratio': round(s['rr_ratio'], 2), 'zone_formed': s['leg_end'],
            'distance_to_entry_pips': round(distance_pips, 1),
            'status': 'PRIX DANS LA ZONE' if in_zone else 'EN APPROCHE'
        })

    return signals


def format_signal(sig, asset):
    arrow = "🟢 ACHAT" if sig['direction'] == 'bullish' else "🔴 VENTE"
    return f"""
{arrow} — {asset}
Statut       : {sig['status']}
Entrée limite: {sig['entry']:.5f}
Stop loss    : {sig['sl']:.5f}
Take profit  : {sig['tp']:.5f}
R:R          : {sig['rr_ratio']}
Zone formée  : {sig['zone_formed']}
Distance prix actuel -> entrée: {sig['distance_to_entry_pips']} pips
"""


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python3 shadow_retracement_ai.py <fichier_M1.csv> <XAUUSD|EURUSD>")
        sys.exit(1)

    csv_path, asset = sys.argv[1], sys.argv[2].upper()
    if asset not in ASSET_CONFIG:
        print(f"Actif non supporté: {asset}. Utilise XAUUSD ou EURUSD.")
        sys.exit(1)

    m1 = load_m1(csv_path)
    print(f"Données chargées: {len(m1)} bougies M1, jusqu'à {m1.index.max()}")

    signals = scan_active_setups(m1, asset)

    if not signals:
        print(f"\nAucun setup Shadow Retracement actif détecté sur {asset} en ce moment.")
    else:
        print(f"\n{len(signals)} setup(s) actif(s) détecté(s) :")
        for sig in signals:
            print(format_signal(sig, asset))
