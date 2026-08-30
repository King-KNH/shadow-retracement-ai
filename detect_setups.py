import pandas as pd
import numpy as np
from structure_detection import detect_swings, get_structure_points

def compute_poc(m1_df, start_time, end_time, n_bins=50):
    """
    Profil temps-prix proxy (puisque le volume réel n'existe pas en Forex).
    Découpe la plage de prix de l'impulsion en n_bins, compte combien de
    bougies M1 ont leur close dans chaque bin. Le bin le plus visité = POC.
    """
    segment = m1_df.loc[start_time:end_time]
    if len(segment) < 2:
        return None

    lo, hi = segment['low'].min(), segment['high'].max()
    if hi == lo:
        return (lo + hi) / 2

    bins = np.linspace(lo, hi, n_bins + 1)
    counts = np.zeros(n_bins)
    for close in segment['close']:
        b = min(int((close - lo) / (hi - lo) * n_bins), n_bins - 1)
        counts[b] += 1

    poc_bin = np.argmax(counts)
    poc_price = (bins[poc_bin] + bins[poc_bin + 1]) / 2
    return poc_price


def build_legs(structure_points):
    """Construit les segments (legs) entre points de structure consécutifs alternés."""
    legs = []
    for i in range(1, len(structure_points)):
        prev = structure_points.iloc[i - 1]
        curr = structure_points.iloc[i]
        direction = 'bullish' if curr['type'] == 'high' else 'bearish'
        legs.append({
            'start_time': prev['datetime'], 'start_price': prev['price'],
            'end_time': curr['datetime'], 'end_price': curr['price'],
            'direction': direction
        })
    return pd.DataFrame(legs)


def find_ob_candle(h1_df, leg_start_time, leg_end_time, direction):
    """
    Order block = dernière bougie de couleur opposée avant l'impulsion.
    Recherche en partant de leg_start_time et en avançant.
    """
    window = h1_df.loc[leg_start_time:leg_end_time]
    if direction == 'bullish':
        opposite = window[window['close'] < window['open']]  # bougies baissières
    else:
        opposite = window[window['close'] > window['open']]  # bougies haussières

    if len(opposite) == 0:
        return None
    return opposite.iloc[0]  # la première rencontrée = juste avant l'impulsion


def classify_zone(ob_high, ob_low, dealing_low, dealing_high, direction):
    """Discount si zone sous le Fib 50%, premium si au-dessus."""
    eq = (dealing_low + dealing_high) / 2
    zone_mid = (ob_high + ob_low) / 2
    if direction == 'bullish':
        return 'discount' if zone_mid < eq else 'premium'
    else:
        return 'premium' if zone_mid > eq else 'discount'


def detect_setups(h1_df, m1_df, lookback=5, poc_bins=50):
    swung = detect_swings(h1_df, lookback=lookback)
    points = get_structure_points(swung)
    legs = build_legs(points)

    setups = []
    for i in range(1, len(legs)):
        leg = legs.iloc[i]
        prev_leg = legs.iloc[i - 1]

        ob = find_ob_candle(h1_df, leg['start_time'], leg['end_time'], leg['direction'])
        if ob is None:
            continue

        ob_high, ob_low = ob['high'], ob['low']

        # Dealing range = leg précédente (pour le filtre premium/discount)
        dealing_low = min(prev_leg['start_price'], prev_leg['end_price'])
        dealing_high = max(prev_leg['start_price'], prev_leg['end_price'])

        zone_type = classify_zone(ob_high, ob_low, dealing_low, dealing_high, leg['direction'])
        valid = (leg['direction'] == 'bullish' and zone_type == 'discount') or \
                (leg['direction'] == 'bearish' and zone_type == 'premium')

        poc = compute_poc(m1_df, leg['start_time'], leg['end_time'], n_bins=poc_bins)

        setups.append({
            'leg_start': leg['start_time'], 'leg_end': leg['end_time'],
            'direction': leg['direction'], 'ob_time': ob.name,
            'ob_high': ob_high, 'ob_low': ob_low,
            'zone_type': zone_type, 'valid_pd_filter': valid,
            'poc': poc,
            'target_price': leg['end_price'],  # ancien plus haut/bas = TP
        })

    return pd.DataFrame(setups)


if __name__ == '__main__':
    h1 = pd.read_csv('/home/claude/data/EURUSD_H1.csv', index_col='datetime', parse_dates=True)
    m1 = pd.read_csv('/home/claude/data/EURUSD_M1_clean.csv', index_col='datetime', parse_dates=True)

    setups = detect_setups(h1, m1)
    print(f"Total legs analysés: {len(setups)}")
    print(f"Setups valides (filtre premium/discount OK): {setups['valid_pd_filter'].sum()}")
    print(f"\nRépartition zone_type:\n{setups['zone_type'].value_counts()}")
    print(f"\nExemple de setups valides:")
    print(setups[setups['valid_pd_filter']].head(10)[['leg_end', 'direction', 'ob_high', 'ob_low', 'poc', 'target_price']])

    setups.to_csv('/home/claude/data/EURUSD_setups_raw.csv', index=False)
