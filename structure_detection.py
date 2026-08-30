import pandas as pd
import numpy as np

def detect_swings(df, lookback=2):
    """
    Détecte les swing highs/lows via la méthode des fractales.
    Un swing high = bougie dont le High est supérieur aux `lookback` bougies
    de chaque côté. Idem pour swing low.
    lookback=2 -> fractale classique 5 bougies (structure interne, plus sensible)
    lookback=5 -> structure plus large (externe, moins de faux signaux)
    """
    highs = df['high'].values
    lows = df['low'].values
    n = len(df)

    swing_high = np.full(n, False)
    swing_low = np.full(n, False)

    for i in range(lookback, n - lookback):
        window_h = highs[i - lookback:i + lookback + 1]
        window_l = lows[i - lookback:i + lookback + 1]
        if highs[i] == window_h.max() and np.argmax(window_h) == lookback:
            swing_high[i] = True
        if lows[i] == window_l.min() and np.argmin(window_l) == lookback:
            swing_low[i] = True

    result = df.copy()
    result['swing_high'] = swing_high
    result['swing_low'] = swing_low
    return result


def get_structure_points(df_with_swings):
    """Extrait uniquement les points de swing, avec leur type et prix."""
    points = []
    for idx, row in df_with_swings.iterrows():
        if row['swing_high']:
            points.append({'datetime': idx, 'type': 'high', 'price': row['high']})
        if row['swing_low']:
            points.append({'datetime': idx, 'type': 'low', 'price': row['low']})
    raw = pd.DataFrame(points).sort_values('datetime').reset_index(drop=True)
    return enforce_alternation(raw)


def enforce_alternation(raw_points):
    """
    Force une alternance stricte high/low/high/low.
    Quand deux points du même type se suivent, ne garde que le plus extrême
    (le plus haut des 'high', le plus bas des 'low').
    """
    if len(raw_points) == 0:
        return raw_points

    cleaned = [raw_points.iloc[0].to_dict()]
    for _, row in raw_points.iloc[1:].iterrows():
        last = cleaned[-1]
        if row['type'] == last['type']:
            # Même type consécutif -> garder le plus extrême
            if row['type'] == 'high' and row['price'] > last['price']:
                cleaned[-1] = row.to_dict()
            elif row['type'] == 'low' and row['price'] < last['price']:
                cleaned[-1] = row.to_dict()
            # sinon on ignore le nouveau point (moins extrême)
        else:
            cleaned.append(row.to_dict())

    return pd.DataFrame(cleaned).reset_index(drop=True)


def determine_bias(structure_points, current_idx):
    """
    Détermine le biais directionnel à un instant donné en comparant
    les 2 derniers swing highs et les 2 derniers swing lows.
    Séquence de plus hauts et plus bas croissants -> bullish
    Séquence décroissante -> bearish
    """
    past = structure_points[structure_points['datetime'] <= current_idx]
    highs = past[past['type'] == 'high'].tail(2)
    lows = past[past['type'] == 'low'].tail(2)

    if len(highs) < 2 or len(lows) < 2:
        return 'undefined'

    higher_high = highs['price'].iloc[-1] > highs['price'].iloc[-2]
    higher_low = lows['price'].iloc[-1] > lows['price'].iloc[-2]

    if higher_high and higher_low:
        return 'bullish'
    elif not higher_high and not higher_low:
        return 'bearish'
    else:
        return 'ranging'


if __name__ == '__main__':
    h1 = pd.read_csv('/home/claude/data/EURUSD_H1.csv', index_col='datetime', parse_dates=True)

    # Structure externe (lookback large) et interne (lookback court)
    h1_external = detect_swings(h1, lookback=5)
    h1_internal = detect_swings(h1, lookback=2)

    ext_points = get_structure_points(h1_external)
    int_points = get_structure_points(h1_internal)

    print(f"Swings structure externe détectés: {len(ext_points)}")
    print(f"Swings structure interne détectés: {len(int_points)}")
    print("\nExemple structure externe (5 premiers):")
    print(ext_points.head())

    ext_points.to_csv('/home/claude/data/EURUSD_H1_swings_external.csv', index=False)
    int_points.to_csv('/home/claude/data/EURUSD_H1_swings_internal.csv', index=False)
