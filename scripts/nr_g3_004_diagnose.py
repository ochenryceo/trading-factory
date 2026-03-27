#!/usr/bin/env python3
"""
Quick diagnosis: WHY is ATR>1.5x so rare in 2023+?
Is it that vol-of-vol declined, or is there a normalization issue?
"""
import sys
from pathlib import Path
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import pandas as pd
import numpy as np
from services.darwin.backtester import load_parquet, atr

df = load_parquet("NQ", "1h")
close = df["close"]
high = df["high"]
low = df["low"]

_atr = atr(high, low, close, 14)
atr_avg = _atr.rolling(20).mean()
atr_ratio = _atr / atr_avg.replace(0, np.nan)

# ATR as % of price (normalized)
atr_pct = (_atr / close) * 100
atr_pct_avg = atr_pct.rolling(20).mean()
atr_pct_ratio = atr_pct / atr_pct_avg.replace(0, np.nan)

df_a = pd.DataFrame({
    "atr": _atr,
    "atr_avg20": atr_avg,
    "atr_ratio": atr_ratio,
    "atr_pct": atr_pct,
    "atr_pct_avg20": atr_pct_avg,
    "atr_pct_ratio": atr_pct_ratio,
    "close": close,
}, index=df.index)
df_a["year"] = df_a.index.year

print("ATR RATIO STATISTICS (absolute ATR / 20-bar avg):")
print(f"{'Year':>6} | {'MeanClose':>10} | {'MeanATR':>8} | {'ATR_ratio_mean':>14} | {'ATR_ratio_std':>13} | {'%>1.5x':>7} | {'%>1.3x':>7} | {'%>1.2x':>7}")
print("-" * 95)
for yr, g in df_a.groupby("year"):
    print(f"{yr:>6} | {g['close'].mean():>10.0f} | {g['atr'].mean():>8.1f} | "
          f"{g['atr_ratio'].mean():>14.3f} | {g['atr_ratio'].std():>13.3f} | "
          f"{(g['atr_ratio']>1.5).mean()*100:>6.1f}% | "
          f"{(g['atr_ratio']>1.3).mean()*100:>6.1f}% | "
          f"{(g['atr_ratio']>1.2).mean()*100:>6.1f}%")

print("\n\nATR% RATIO STATISTICS (ATR/close% / 20-bar avg of ATR/close%):")
print(f"{'Year':>6} | {'MeanATR%':>8} | {'ATR%_ratio_mean':>15} | {'ATR%_ratio_std':>14} | {'%>1.5x':>7} | {'%>1.3x':>7} | {'%>1.2x':>7}")
print("-" * 80)
for yr, g in df_a.groupby("year"):
    print(f"{yr:>6} | {g['atr_pct'].mean():>7.3f}% | "
          f"{g['atr_pct_ratio'].mean():>15.3f} | {g['atr_pct_ratio'].std():>14.3f} | "
          f"{(g['atr_pct_ratio']>1.5).mean()*100:>6.1f}% | "
          f"{(g['atr_pct_ratio']>1.3).mean()*100:>6.1f}% | "
          f"{(g['atr_pct_ratio']>1.2).mean()*100:>6.1f}%")

print("\n\nCONCLUSION:")
r2023_abs = df_a[df_a["year"]>=2023]["atr_ratio"].std()
r2020_abs = df_a[(df_a["year"]>=2020)&(df_a["year"]<2023)]["atr_ratio"].std()
r2023_pct = df_a[df_a["year"]>=2023]["atr_pct_ratio"].std()
r2020_pct = df_a[(df_a["year"]>=2020)&(df_a["year"]<2023)]["atr_pct_ratio"].std()
print(f"  ATR ratio std 2020-2022: {r2020_abs:.3f}, 2023+: {r2023_abs:.3f}")
print(f"  ATR% ratio std 2020-2022: {r2020_pct:.3f}, 2023+: {r2023_pct:.3f}")
