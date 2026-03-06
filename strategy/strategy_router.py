class StrategyRouter:
    def __init__(self, neutral_grid, trend_dca):
        self.neutral_grid = neutral_grid
        self.trend_dca = trend_dca

    async def route_signals(self, symbol, regime, market_state):
        signals = []
        
        if regime == "range":
            # Prioritize Neutral Grid
            grid_signals = await self.neutral_grid.on_market_state(
                symbol, 
                market_state
            )
            if grid_signals:
                signals.extend(grid_signals)
            
        elif regime == "trend":
            # Prioritize Trend DCA
            trend_signals = await self.trend_dca.on_new_candle(
                symbol, 
                market_state
            )
            if trend_signals:
                signals.extend(trend_signals)
        
        return signals
