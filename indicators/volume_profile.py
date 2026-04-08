import pandas as pd
import numpy as np
from common.types import VolumeProfile


def compute_volume_profile(df: pd.DataFrame, bins: int = 24) -> VolumeProfile:
    price_min = df["low"].min()
    price_max = df["high"].max()

    bin_edges = np.linspace(price_min, price_max, bins + 1)

    # Calculate volume per bin
    hist, _ = np.histogram(df["close"], bins=bin_edges, weights=df["volume"])

    # POC - Price with highest volume
    max_vol_idx = np.argmax(hist)
    poc = (bin_edges[max_vol_idx] + bin_edges[max_vol_idx + 1]) / 2

    # Value Area (Simplified 70% volume around POC)
    total_volume = hist.sum()
    target_volume = total_volume * 0.70

    current_volume = hist[max_vol_idx]
    low_idx = max_vol_idx
    high_idx = max_vol_idx

    while current_volume < target_volume:
        vol_below = hist[low_idx - 1] if low_idx > 0 else 0
        vol_above = hist[high_idx + 1] if high_idx < bins - 1 else 0

        if vol_below > vol_above or (vol_below == vol_above and low_idx > 0):
            low_idx -= 1
            current_volume += vol_below
        elif high_idx < bins - 1:
            high_idx += 1
            current_volume += vol_above
        else:
            break

        if low_idx <= 0 and high_idx >= bins - 1:
            break

    val = bin_edges[low_idx]
    vah = bin_edges[high_idx + 1]

    return VolumeProfile(
        poc=float(poc),
        vah=float(vah),
        val=float(val),
        bins=bin_edges.tolist(),
        distribution=hist.tolist(),
    )
