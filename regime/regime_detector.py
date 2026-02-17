import pandas as pd

class RegimeDetector:
    def detect_regime(self, df: pd.DataFrame) -> str:
        # Defensas por si faltan columnas o hay NaNs al inicio
        if df is None or len(df) == 0:
            return "range"

        last_row = df.iloc[-1]

        # 1) BB Width (puede faltar si bbands no generó columnas)
        bb_col_exists = 'BB_width' in df.columns
        is_low_vol = False
        if bb_col_exists:
            # Rolling robusto con min_periods y manejo de NaN
            bb_series = df['BB_width']
            bb_ma = bb_series.rolling(100, min_periods=20).mean()
            bb_last = last_row.get('BB_width')
            bb_ma_last = bb_ma.iloc[-1]
            try:
                if pd.notna(bb_last) and pd.notna(bb_ma_last):
                    is_low_vol = bb_last < bb_ma_last
            except Exception:
                is_low_vol = False

        # 2) EMAs (pueden faltar o ser NaN al inicio)
        ema_fast = last_row.get('EMA_fast') if 'EMA_fast' in df.columns else None
        ema_slow = last_row.get('EMA_slow') if 'EMA_slow' in df.columns else None
        close = last_row.get('close')

        ema_dist = 0.0
        if pd.notna(ema_fast) and pd.notna(ema_slow) and pd.notna(close) and close:
            try:
                ema_dist = abs(float(ema_fast) - float(ema_slow)) / float(close)
            except Exception:
                ema_dist = 0.0

        # Heurística sencilla y robusta
        # - Si la distancia entre EMAs es suficientemente grande (>2%) y no estamos en baja volatilidad -> trend
        # - En caso contrario -> range
        if ema_dist > 0.02 and not is_low_vol:
            return "trend"
        return "range"
