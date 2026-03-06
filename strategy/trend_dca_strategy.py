import pandas as pd
import logging
from common.types import Side, SignalAction, Signal, DcaLevel, TrendPosition
from datetime import datetime

logger = logging.getLogger(__name__)

class TrendDcaStrategy:
    def __init__(self, config):
        self.config = config
        self.active_positions: dict[str, TrendPosition] = {} # symbol -> TrendPosition

    def generate_trend_signal(self, symbol: str, df: pd.DataFrame) -> Side:
        """
        Identify the current trend direction based on EMAs and MACD.
        Returns Side.LONG, Side.SHORT, or None.
        """
        if df is None or len(df) < 5:
            return None
            
        last_row = df.iloc[-1]
        
        # Check if indicators exist
        if 'EMA_fast' not in df.columns or 'EMA_slow' not in df.columns or 'MACD' not in df.columns:
            return None

        # Bullish trend: EMA_fast > EMA_slow AND MACD > 0
        is_bullish = last_row['EMA_fast'] > last_row['EMA_slow'] and last_row['MACD'] > 0
        is_bearish = last_row['EMA_fast'] < last_row['EMA_slow'] and last_row['MACD'] < 0
        
        logger.debug(f"[TrendDca] {symbol} Trend Check: EMA_f={last_row['EMA_fast']:.2f}, EMA_s={last_row['EMA_slow']:.2f}, MACD={last_row['MACD']:.4f}")
        
        if is_bullish:
            return Side.LONG
        elif is_bearish:
            return Side.SHORT
        
        return None

    def plan_dca_levels(self, entry_price: float, side: Side, total_amount: float) -> list[DcaLevel]:
        """
        Pre-calculate DCA levels based on entry price and steps.
        Static 1.5% distance for simplicity, could be ATR-based.
        """
        levels = []
        step_pct = 0.010  # 1.0% — tighter DCA steps for testnet
        amount_per_step = total_amount / (self.config.DCA_STEPS + 1)
        
        for i in range(1, self.config.DCA_STEPS + 1):
            if side == Side.LONG:
                price = entry_price * (1 - step_pct * i)
            else:
                price = entry_price * (1 + step_pct * i)
            
            levels.append(DcaLevel(price=price, amount=amount_per_step))
        return levels

    def calculate_sl_tp(self, entry_price: float, side: Side, atr: float):
        """Calculate Stop Loss and Take Profit using ATR multiplier."""
        if side == Side.LONG:
            sl = entry_price - (atr * 2.0)   # Tighter stop: 2.0×ATR
            tp = entry_price + (atr * 3.5)   # Achievable target: 3.5×ATR
        else:
            sl = entry_price + (atr * 2.0)
            tp = entry_price - (atr * 3.5)
        return sl, tp

    async def on_new_candle(self, symbol: str, market_state: dict) -> list[Signal]:
        """
        Core logic to generate signals on each candle.
        """
        df = market_state.get('df')
        position_state = market_state.get('position')
        equity = market_state.get('equity', 10000.0)
        
        signals = []
        if df is None or len(df) < 20:
            return signals

        last_row = df.iloc[-1]
        prev_row = df.iloc[-2]
        trend = self.generate_trend_signal(symbol, df)
        
        # Current Price & Budget
        current_price = last_row['close']
        atr = last_row.get('ATR', 0.0)
        total_amount = equity * 0.15  # 15% allocation for trend + DCA (conservative for testnet)

        # 1. Logic for NEW Entries
        if not position_state or not position_state.get('is_active', False):
            if trend == Side.LONG:
                # LONG Pullback
                if prev_row['low'] <= last_row['EMA_fast'] and last_row['close'] > last_row['EMA_fast']:
                    logger.info(f"[TrendDca] {symbol} Pullback LONG detected at {current_price}")
                    sl, tp = self.calculate_sl_tp(current_price, Side.LONG, atr)
                    
                    dca_levels = self.plan_dca_levels(current_price, Side.LONG, total_amount)
                    
                    signals.append(Signal(
                        symbol=symbol,
                        action=SignalAction.ENTER_LONG,
                        side=Side.LONG,
                        price=current_price,
                        stop_loss=sl,
                        take_profit=tp,
                        strategy="TrendDCA",
                        confidence=0.8,
                        meta={'dca_levels': [{'price': d.price, 'amount': d.amount, 'filled': False} for d in dca_levels]}
                    ))
                    # Initialize internal position tracking
                    self.active_positions[symbol] = TrendPosition(
                        symbol=symbol, side=Side.LONG, entry_price=current_price,
                        dca_levels=dca_levels, stop_loss=sl, take_profit=tp, is_active=True
                    )
                else:
                    logger.info(f"[TrendDca] {symbol} Bullish trend. Waiting for pullback to {last_row['EMA_fast']:.2f}")

            elif trend == Side.SHORT:
                # SHORT Pullback
                if prev_row['high'] >= last_row['EMA_fast'] and last_row['close'] < last_row['EMA_fast']:
                    logger.info(f"[TrendDca] {symbol} Pullback SHORT detected at {current_price}")
                    sl, tp = self.calculate_sl_tp(current_price, Side.SHORT, atr)
                    
                    dca_levels = self.plan_dca_levels(current_price, Side.SHORT, total_amount)
                    
                    signals.append(Signal(
                        symbol=symbol,
                        action=SignalAction.ENTER_SHORT,
                        side=Side.SHORT,
                        price=current_price,
                        stop_loss=sl,
                        take_profit=tp,
                        strategy="TrendDCA",
                        confidence=0.8,
                        meta={'dca_levels': [{'price': d.price, 'amount': d.amount, 'filled': False} for d in dca_levels]}
                    ))
                    # Initialize internal position tracking
                    self.active_positions[symbol] = TrendPosition(
                        symbol=symbol, side=Side.SHORT, entry_price=current_price,
                        dca_levels=dca_levels, stop_loss=sl, take_profit=tp, is_active=True
                    )
                else:
                    logger.info(f"[TrendDca] {symbol} Bearish trend. EMA_f={last_row['EMA_fast']:.2f}, PrevHigh={prev_row['high']:.2f}. Waiting for pullback.")
            else:
                logger.debug(f"[TrendDca] {symbol} Neutral zone (No Trend).")
        
        # 2. Logic for EXISTING Positions (Exit & DCA)
        else:
            side = position_state.get('side')
            # Ensure internal state is synchronized with current real position
            if symbol not in self.active_positions or not self.active_positions[symbol].is_active:
                # Reconstruction of state if missing but position exists
                self.active_positions[symbol] = TrendPosition(
                    symbol=symbol,
                    side=Side.LONG if side == "LONG" else Side.SHORT,
                    entry_price=position_state.get('entry_price', 0),
                    is_active=True
                )

            # Check for Exit
            if side == "LONG":
                tp = position_state.get('take_profit')
                sl = position_state.get('stop_loss')
                if tp is not None and current_price >= tp:
                    signals.append(Signal(symbol=symbol, action=SignalAction.EXIT_LONG, side=Side.LONG, price=current_price, strategy="TrendDCA"))
                    self.active_positions[symbol].is_active = False 
                elif sl is not None and current_price <= sl:
                    signals.append(Signal(symbol=symbol, action=SignalAction.EXIT_LONG, side=Side.LONG, price=current_price, strategy="TrendDCA"))
                    self.active_positions[symbol].is_active = False

                # Check DCA levels
                dca_levels = self.active_positions[symbol].dca_levels
                for level in dca_levels:
                    if not level.filled and current_price <= level.price:
                        logger.info(f"[TrendDca] {symbol} LONG DCA Level {level.price} hit!")
                        signals.append(Signal(
                            symbol=symbol, action=SignalAction.DCA_ADD, side=Side.LONG, 
                            price=level.price, amount=level.amount, strategy="TrendDCA"
                        ))
                        level.filled = True

            elif side == "SHORT":
                tp = position_state.get('take_profit')
                sl = position_state.get('stop_loss')
                if tp is not None and current_price <= tp:
                    signals.append(Signal(symbol=symbol, action=SignalAction.EXIT_SHORT, side=Side.SHORT, price=current_price, strategy="TrendDCA"))
                    self.active_positions[symbol].is_active = False
                elif sl is not None and current_price >= sl:
                    signals.append(Signal(symbol=symbol, action=SignalAction.EXIT_SHORT, side=Side.SHORT, price=current_price, strategy="TrendDCA"))
                    self.active_positions[symbol].is_active = False

                # Check DCA levels
                dca_levels = self.active_positions[symbol].dca_levels
                for level in dca_levels:
                    if not level.filled and current_price >= level.price:
                        logger.info(f"[TrendDca] {symbol} SHORT DCA Level {level.price} hit!")
                        signals.append(Signal(
                            symbol=symbol, action=SignalAction.DCA_ADD, side=Side.SHORT, 
                            price=level.price, amount=level.amount, strategy="TrendDCA"
                        ))
                        level.filled = True

        return signals

    def reconcile_with_exchange(self, symbol: str, open_orders: list[dict]):
        """Verify DCA orders match exchange state."""
        pos = self.active_positions.get(symbol)
        if not pos or not pos.is_active:
            return

        order_ids_on_exchange = {str(o['id']) for o in open_orders}
        for level in pos.dca_levels:
            if level.order_id and level.order_id not in order_ids_on_exchange:
                if not level.filled:
                    logger.warning(f"[TrendDca] {symbol} DCA Order {level.order_id} missing from exchange. Resetting.")
                    level.order_id = None

    def update_order_id(self, symbol: str, price: float, order_id: str):
        """Update DCA level with real order ID."""
        pos = self.active_positions.get(symbol)
        if pos:
            for level in pos.dca_levels:
                if abs(level.price - price) / price < 0.0001:
                    level.order_id = str(order_id)
                    return
