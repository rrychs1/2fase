import pandas as pd
import pandas_ta as ta
import numpy as np

# Create dummy data
df = pd.DataFrame({
    'close': np.linspace(100, 110, 50) + np.random.normal(0, 1, 50)
})

# Calculate bbands
bbands = ta.bbands(df['close'], length=20, std=2)
print("BBands columns identified:")
print(bbands.columns.tolist())

# Test current logic
b_cols = bbands.columns
bbu_key = next((k for k in ['BBU_20_2.0', 'BBU_20_2'] if k in b_cols), None)
bbl_key = next((k for k in ['BBL_20_2.0', 'BBL_20_2'] if k in b_cols), None)

print(f"\nBBU key found: {bbu_key}")
print(f"BBL key found: {bbl_key}")
