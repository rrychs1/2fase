import logging
from common.types import Signal, SignalAction

logger = logging.getLogger(__name__)


class OrderValidator:
    """Validates and sanitizes orders before execution to prevent exchange rejections."""

    @staticmethod
    def validate_signal(
        signal: Signal,
        current_price: float,
        config,
        equity: float = 0.0,
    ) -> Signal:
        """
        Validates the signal against Binance constraints.
        Returns the original or modified signal if valid, None if blocked.

        M-04: ``equity`` is optional; when provided, any upscale is capped at
        ``config.MAX_RISK_PER_TRADE * equity`` so the minimum-notional bump
        cannot silently override the risk budget.
        """
        if not signal or signal.amount <= 0:
            logger.warning(
                f"[Validator] Blocked {signal.action.value} on {signal.symbol}: size <= 0"
            )
            return None

        # For exits, we just ensure amount > 0, price deviation is less strict
        is_exit = signal.action in [SignalAction.EXIT_LONG, SignalAction.EXIT_SHORT]

        target_price = signal.price if signal.price else current_price

        # 1. Price Deviation Check (skip for market exits)
        if current_price and target_price and not is_exit:
            deviation = abs(target_price - current_price) / current_price
            if deviation > config.MAX_PRICE_DEVIATION_PCT:
                logger.warning(
                    f"[Validator] Blocked {signal.action.value} on {signal.symbol}: "
                    f"Price {target_price:.2f} is {deviation*100:.2f}% away from {current_price:.2f} "
                    f"(Max: {config.MAX_PRICE_DEVIATION_PCT*100:.2f}%)"
                )
                return None

        # 2. Minimum Notional Check
        if target_price:
            notional = signal.amount * target_price
            if notional < config.MIN_NOTIONAL:
                # Upscale the order to meet the minimum notional requirement
                new_amount = (
                    config.MIN_NOTIONAL / target_price
                ) * 1.02  # 2% buffer to be safe against ticking

                # M-04: cap upscale at the risk budget when equity is known
                if equity > 0:
                    max_risk_amount = (equity * config.MAX_RISK_PER_TRADE) / target_price
                    if new_amount > max_risk_amount:
                        logger.warning(
                            f"[Validator] {signal.action.value} on {signal.symbol}: "
                            f"Min-notional upscale ({new_amount:.4f}) exceeds risk budget "
                            f"({max_risk_amount:.4f} @ {config.MAX_RISK_PER_TRADE*100:.1f}% of equity). "
                            "Order BLOCKED to protect risk limits."
                        )
                        return None

                logger.info(
                    f"[Validator] {signal.action.value} on {signal.symbol} notional {notional:.2f} < "
                    f"{config.MIN_NOTIONAL}. Upscaling {signal.amount:.4f} -> {new_amount:.4f}"
                )
                signal.amount = new_amount

        return signal

