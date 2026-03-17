import logging
import math

logger = logging.getLogger(__name__)

def validate_order(symbol: str, price: float, quantity: float, current_price: float) -> tuple[bool, str]:
    """
    Validates an order before sending to the exchange.
    Ensures minimum notional, valid price ranges, and handles precision.
    
    Args:
        symbol: The trading pair symbol (e.g., 'BTC/USDT').
        price: The intended order price.
        quantity: The intended order quantity.
        current_price: The current market price.
        
    Returns:
        tuple[bool, str]: (is_valid, reason_if_invalid)
    """
    if price <= 0:
        reason = "Price must be strictly positive."
        logger.error(f"[{symbol}] Validation Failed: {reason}")
        return False, reason
        
    if quantity <= 0:
        reason = "Quantity must be strictly positive."
        logger.error(f"[{symbol}] Validation Failed: {reason}")
        return False, reason

    # 1. Safe Rounding & Exchange Precision
    # In a fully integrated system this precision would be fetched from the exchange (e.g., ccxt markets)
    # We apply a safe rounding floor to the quantity to respect common exchange precisions (e.g., 4 decimal places)
    precision_decimals = 4
    rounded_quantity = math.floor(quantity * (10 ** precision_decimals)) / (10 ** precision_decimals)
    
    if rounded_quantity <= 0:
        reason = f"Quantity {quantity} is too small and rounded down to 0 based on exchange precision."
        logger.warning(f"[{symbol}] Validation Failed: {reason}")
        return False, reason

    # 2. Protection against unrealistic prices (>5% away)
    deviation = abs(price - current_price) / current_price
    if deviation > 0.05:
        reason = f"Order price ({price}) is >5% away from current market price ({current_price}). Deviation: {deviation*100:.2f}%"
        logger.warning(f"[{symbol}] Validation Failed: {reason}")
        return False, reason

    # 3. Ensure minimum notional >= 100 USDT
    notional = price * rounded_quantity
    if notional < 100.0:
        reason = f"Order notional ({notional:.2f} USDT) is smaller than the minimum required 100 USDT limit."
        logger.warning(f"[{symbol}] Validation Failed: {reason}")
        return False, reason

    # Order passed all checks
    logger.info(f"[{symbol}] Order Validated: {rounded_quantity} @ {price} (Notional: {notional:.2f} USDT)")
    return True, "Valid"
