import pandas as pd
import ta.volatility as volatility_i
import numpy as np

# Create dummy data
df = pd.DataFrame({
    'close': np.linspace(100, 110, 50) + np.random.normal(0, 1, 50)
})

# Calculate Bollinger Bands using ta library
bb_obj = volatility_i.BollingerBands(close=df['close'], window=20, window_dev=2)
df['BB_upper'] = bb_obj.bollinger_hband()
df['BB_lower'] = bb_obj.bollinger_lband()
df['BB_width'] = bb_obj.bollinger_wband()

print("BB_upper sample:", df['BB_upper'].tail(5).values)
print("BB_lower sample:", df['BB_lower'].tail(5).values)
print("BB_width sample:", df['BB_width'].tail(5).values)
