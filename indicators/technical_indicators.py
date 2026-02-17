import pandas as pd
import pandas_ta as ta

def add_standard_indicators(df: pd.DataFrame) -> pd.DataFrame:
    # Defensas por si el DF está vacío o le faltan columnas
    required_cols = {'open', 'high', 'low', 'close'}
    if not isinstance(df, pd.DataFrame) or len(df) == 0 or not required_cols.issubset(df.columns):
        return df

    # EMAs
    df['EMA_fast'] = ta.ema(df['close'], length=50)
    df['EMA_slow'] = ta.ema(df['close'], length=200)

    # MACD (identificación robusta por prefijos)
    macd = ta.macd(df['close'])
    if macd is not None and isinstance(macd, pd.DataFrame):
        macd_cols = macd.columns
        # Buscar columnas que empiezan por MACD_, MACDs_, MACDh_
        macd_key = next((k for k in macd_cols if k.startswith('MACD_') and not k.startswith('MACDs_') and not k.startswith('MACDh_')), None)
        # Si no hay uno con guion bajo, buscar el exacto "MACD"
        if not macd_key: macd_key = 'MACD' if 'MACD' in macd_cols else None
        
        macds_key = next((k for k in macd_cols if k.startswith('MACDs_')), None)
        macdh_key = next((k for k in macd_cols if k.startswith('MACDh_')), None)
        
        if macd_key: df['MACD'] = macd[macd_key]
        if macds_key: df['MACD_signal'] = macd[macds_key]
        if macdh_key: df['MACD_hist'] = macd[macdh_key]

    # RSI y ATR
    df['RSI'] = ta.rsi(df['close'], length=14)
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)

    # Bollinger Bands (identificación robusta por prefijos)
    bbands = ta.bbands(df['close'], length=20, std=2)
    if bbands is not None and isinstance(bbands, pd.DataFrame):
        b_cols = bbands.columns
        bbl_key = next((k for k in b_cols if k.startswith('BBL_')), None)
        bbu_key = next((k for k in b_cols if k.startswith('BBU_')), None)
        bbb_key = next((k for k in b_cols if k.startswith('BBB_')), None) # Bandwidth column
        
        if bbl_key: df['BB_lower'] = bbands[bbl_key]
        if bbu_key: df['BB_upper'] = bbands[bbu_key]
        
        if bbb_key:
            # Usar el ancho de banda calculado por la librería (suele ser en porcentaje)
            # pandas_ta lo devuelve como (Upper - Lower) / Mid * 100 o similar.
            # Nosotros queremos (Upper - Lower) / close para consistencia con el detector.
            df['BB_width'] = bbands[bbb_key] / 100.0 if bbands[bbb_key].mean() > 1.0 else bbands[bbb_key]
        elif bbu_key and bbl_key:
            with pd.option_context('mode.use_inf_as_na', True):
                df['BB_width'] = (df['BB_upper'] - df['BB_lower']) / df['close']

    return df

    return df
