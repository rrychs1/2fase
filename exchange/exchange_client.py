import ccxt.async_support as ccxt
import asyncio
import logging
import requests
import pandas as pd
import hmac
import hashlib
import time
from datetime import datetime
from config.config_loader import Config

logger = logging.getLogger(__name__)

class ExchangeClient:
    def __init__(self):
        self.exchange = None
        self.public_exchange = None
        self.sim_mode = Config.TRADING_ENV == 'SIM'
        self._initialize_clients()

    async def fetch_ohlcv(self, symbol, timeframe, limit=500):
        try:
            # Try CCXT first
            if self.public_exchange:
                data = await self.public_exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
                if data: return data
        except Exception as e:
            logger.debug(f"CCXT OHLCV failed, trying fallback: {e}")
        
        # Fallback to direct requests (useful if CCXT hangs on load_markets)
        return self._fetch_ohlcv_fallback(symbol, timeframe, limit)

    def _fetch_ohlcv_fallback(self, symbol, timeframe, limit):
        """Direct REST fallback to bypass CCXT market loading overhead."""
        base_url = "https://fapi.binance.com/fapi/v1/klines"
        if Config.USE_TESTNET:
            base_url = "https://demo-fapi.binance.com/fapi/v1/klines"
            
        # Symbol format BTC/USDT -> BTCUSDT
        clean_symbol = symbol.replace("/", "")
        params = {
            "symbol": clean_symbol,
            "interval": timeframe,
            "limit": limit
        }
        
        try:
            r = requests.get(base_url, params=params, timeout=10)
            if r.status_code == 200:
                data = r.json()
                # CCXT Format: [[ts, o, h, l, c, v], ...]
                return [[int(c[0]), float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])] for c in data]
            else:
                logger.error(f"Fallback OHLCV failed for {symbol}: {r.status_code} {r.text}")
        except Exception as e:
            logger.error(f"Fallback OHLCV exception for {symbol}: {e}")
        return []


    async def _apply_backoff(self):
        """Apply centralized delay if backoff is active."""
        if self.backoff_multiplier > 1.0:
            delay = min(30, (self.backoff_multiplier - 1) * 2) # Caps at 30s
            if delay > 0.5:
                logger.warning(f"[Exchange] Rate-limit backoff: Sleeping {delay:.2f}s")
                await asyncio.sleep(delay)
            
            # Decay backoff over time
            now = time.time()
            if now - self.last_rate_limit_hit > 60:
                self.backoff_multiplier *= self.backoff_decay
                if self.backoff_multiplier < 1.1: self.backoff_multiplier = 1.0

    def _manual_request(self, method, endpoint, params=None):
        """Unified signed request helper for Testnet/Live manual fallbacks."""
        # Note: In manual requests, we use synchronous requests, so we handle backoff simply
        if self.backoff_multiplier > 1.2:
            time.sleep(min(5, self.backoff_multiplier))

        base_url = "https://demo-fapi.binance.com" if Config.USE_TESTNET else "https://fapi.binance.com"
        # ... rest of the method logic unchanged in its core ...
        timestamp = int(time.time() * 1000)
        
        payload = {'timestamp': timestamp, 'recvWindow': 10000}
        if params:
            payload.update(params)
            
        # Build query string
        query_parts = []
        for k in sorted(payload.keys()):
            query_parts.append(f"{k}={payload[k]}")
        query_string = "&".join(query_parts)
        
        signature = hmac.new(
            self.exchange.secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        url = f"{base_url}{endpoint}?{query_string}&signature={signature}"
        headers = {'X-MBX-APIKEY': self.exchange.apiKey}
        
        try:
            full_timeout = 30 # High timeout for Testnet slowness
            if method.upper() == 'GET':
                r = requests.get(url, headers=headers, timeout=full_timeout)
            else:
                r = requests.post(url, headers=headers, timeout=full_timeout)
                
            if r.status_code == 200:
                return r.json()
            elif r.status_code in [429, 418]:
                logger.error(f"RATE LIMIT HIT (Manual): {r.status_code}")
                self.backoff_multiplier += 1.0
                self.last_rate_limit_hit = time.time()
                return None
            else:
                logger.error(f"Manual {method} {endpoint} failed: {r.status_code} {r.text}")
                return None
        except Exception as e:
            logger.error(f"Manual {method} {endpoint} exception: {e}")
            return None

    def _initialize_clients(self):
        # Authenticated Client config
        config = {
            'apiKey': Config.BINANCE_API_KEY,
            'secret': Config.BINANCE_SECRET_KEY,
            'enableRateLimit': True,
        }
        
        # Adaptive Backoff State
        self.backoff_multiplier = 1.0
        self.last_rate_limit_hit = 0
        self.backoff_decay = 0.95 # Decay backoff by 5% each minute (approx)
        
        if self.sim_mode:
            logger.info("SIM Mode active: Bypassing exchange client initialization.")
            return

        self.exchange = ccxt.binanceusdm(config)
        
        # Public Client config
        public_config = {
            'enableRateLimit': True,
        }
        self.public_exchange = ccxt.binanceusdm(public_config)

        if Config.USE_TESTNET:
            demo_base = 'https://demo-fapi.binance.com'
            for client in [self.exchange, self.public_exchange]:
                # Override ALL fapi URL keys to Binance Demo Trading
                client.urls['api']['fapiPublic'] = f'{demo_base}/fapi/v1'
                client.urls['api']['fapiPublicV2'] = f'{demo_base}/fapi/v2'
                client.urls['api']['fapiPublicV3'] = f'{demo_base}/fapi/v3'
                client.urls['api']['fapiPrivate'] = f'{demo_base}/fapi/v1'
                client.urls['api']['fapiPrivateV2'] = f'{demo_base}/fapi/v2'
                client.urls['api']['fapiPrivateV3'] = f'{demo_base}/fapi/v3'
                client.urls['api']['fapiData'] = f'{demo_base}/futures/data'
                client.urls['api']['public'] = f'{demo_base}/fapi/v1'
                client.urls['api']['private'] = f'{demo_base}/fapi/v1'
            
            logger.info("Demo Trading mode enabled with full fapi overrides.")

    async def init(self):
        """Initialize and load markets asynchronously with manual fallback."""
        if self.sim_mode:
            logger.info("SIM Mode: Skipping market loading.")
            return

        try:
            # Try to load markets for both
            if self.public_exchange:
                await asyncio.wait_for(self.public_exchange.load_markets(), timeout=10)
            if self.exchange:
                await asyncio.wait_for(self.exchange.load_markets(), timeout=10)
            logger.info(f"Markets loaded via CCXT. (Testnet: {Config.USE_TESTNET})")
        except Exception as e:
            logger.warning(f"CCXT Market loading failed: {e}. Attempting manual load.")
            await self._manual_load_markets()

    async def _manual_load_markets(self):
        """Manually fetch and inject market info to satisfy CCXT's precision requirements."""
        url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
        if Config.USE_TESTNET:
            url = "https://demo-fapi.binance.com/fapi/v1/exchangeInfo"
        
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                markets = {}
                for s in data['symbols']:
                    # Focus ONLY on Perpetual Swaps to avoid symbol collisions with quarterly/delivery
                    if s.get('contractType') != 'PERPETUAL':
                        continue
                        
                    symbol_id = s['symbol'] # e.g. BTCUSDT
                    base = s['baseAsset']
                    quote = s['quoteAsset']
                    ccxt_symbol = f"{base}/{quote}"
                    
                    # Extract filters for precision
                    filters = {f['filterType']: f for f in s['filters']}
                    price_filter = filters.get('PRICE_FILTER', {})
                    lot_size = filters.get('LOT_SIZE', {})
                    
                    market_info = {
                        'id': symbol_id,
                        'symbol': ccxt_symbol,
                        'base': base,
                        'quote': quote,
                        'active': s['status'] == 'TRADING',
                        'precision': {
                            'price': int(s['pricePrecision']),
                            'amount': int(s['quantityPrecision'])
                        },
                        'limits': {
                            'amount': {
                                'min': float(lot_size.get('minQty', 0)),
                                'max': float(lot_size.get('maxQty', 1000000)),
                                'step': float(lot_size.get('stepSize', 0.0001))
                            },
                            'price': {
                                'min': float(price_filter.get('minPrice', 0)),
                                'max': float(price_filter.get('maxPrice', 1000000)),
                                'tick': float(price_filter.get('tickSize', 0.01))
                            },
                            'cost': {
                                'min': float(filters.get('MIN_NOTIONAL', {}).get('notional', 5.0))
                            }
                        },
                        'type': 'swap',
                        'spot': False,
                        'future': False,
                        'swap': True,
                        'contract': True,
                        'linear': True,
                        'inverse': False,
                        'expiry': None,
                        'expiryDatetime': None,
                        'settle': quote,
                        'settleId': quote
                    }
                    markets[ccxt_symbol] = market_info
                    
                for client in [self.exchange, self.public_exchange]:
                    if client:
                        client.markets = markets
                        client.symbols = list(markets.keys())
                        client.markets_loaded = True
                logger.info(f"Successfully injected {len(markets)} markets manually.")
            else:
                logger.error(f"Manual market load failed: {r.status_code}")
        except Exception as e:
            logger.error(f"Manual market load exception: {e}")

    async def close(self):
        """Close exchange connections."""
        if self.exchange: await self.exchange.close()
        if self.public_exchange: await self.public_exchange.close()

    async def fetch_open_orders(self, symbol=None):
        if Config.USE_TESTNET:
            return await self._manual_fetch_open_orders(symbol)
        try:
            orders = await self.exchange.fetch_open_orders(symbol)
            return self._normalize_orders(orders)
        except Exception as e:
            logger.error(f"Error fetching open orders: {e}")
            return []

    async def fetch_my_trades(self, symbol, limit=50):
        if Config.USE_TESTNET:
            return await self._manual_fetch_my_trades(symbol, limit)
        try:
            trades = await self.exchange.fetch_my_trades(symbol, limit=limit)
            return self._normalize_trades(trades)
        except Exception as e:
            logger.error(f"Error fetching trades for {symbol}: {e}")
            return []

    def _normalize_orders(self, orders):
        normalized = []
        for o in orders:
            normalized.append({
                "symbol": o.get("symbol"),
                "side": o.get("side", "").upper(),
                "price": float(o.get("price") or o.get("stopPrice") or 0),
                "type": o.get("type", "limit").upper(),
                "amount": float(o.get("amount", 0)),
                "id": o.get("id")
            })
        return normalized

    def _normalize_trades(self, trades):
        normalized = []
        for t in trades:
            # Extract basic info
            trade_id = str(t.get('id', ''))
            side = t.get("side", "").upper()
            pnl = float(t.get("info", {}).get("realizedPnl", 0))
            amount = float(t.get("amount", 0))
            
            # Suspicious check: if pnl is exactly 0 but amount is significant 
            # (Note: this is a heuristic, realizedPnl 0 is normal for opening trades)
            # We flag it if we suspect it SHOULD have PnL but doesn't.
            # In Binance, only trades that reduce/close have realizedPnl.
            # However, the user wants explicit mapping.
            is_suspicious = False
            if pnl == 0 and amount > 0:
                # RealizedPnL 0 is normal for OPENING. If it's a CLOSING trade (heuristic side check or just log)
                # the DataEngine/BotRunner will handle actual position closing checks.
                # Here we just ensure we HAVE the pnl field mapped correctly.
                pass

            normalized.append({
                "id": trade_id,
                "symbol": t.get("symbol"),
                "side": side,
                "price": float(t.get("price", 0)),
                "amount": amount,
                "pnl": pnl,
                "closed_at": t.get("datetime"),
                "is_suspicious": is_suspicious,
                "info": t.get("info", {})
            })
        return normalized

    async def _manual_fetch_open_orders(self, symbol=None):
        params = {}
        if symbol:
            params['symbol'] = symbol.replace("/", "")
            
        orders = self._manual_request('GET', "/fapi/v1/openOrders", params)
        if not orders: return []
        
        normalized = []
        for o in orders:
            sym_id = o['symbol']
            ccxt_sym = sym_id
            if self.exchange.markets:
                for s, info in self.exchange.markets.items():
                    if info.get('id') == sym_id:
                        ccxt_sym = s; break
            
            normalized.append({
                "symbol": ccxt_sym,
                "side": o.get('side', '').upper(),
                "price": float(o.get('price', 0) or o.get('stopPrice', 0)),
                "type": o.get('type', '').upper(),
                "amount": float(o.get('origQty', 0)),
                "id": o.get('orderId')
            })
        return normalized

    async def _manual_fetch_my_trades(self, symbol, limit=50):
        params = {'symbol': symbol.replace("/", ""), 'limit': limit}
        trades = self._manual_request('GET', "/fapi/v1/userTrades", params)
        if not trades: return []
        
        normalized = []
        for t in trades:
            trade_id = str(t.get('id'))
            pnl = float(t.get('realizedPnl', 0))
            amount = float(t.get('qty', 0))
            side = "BUY" if t.get('side', '').upper() == 'BUY' else "SELL"
            
            # Suspicious logic for Phase 4
            is_suspicious = False
            # If PnL is absolutely 0 on a trade > $10 notional (approx)
            if pnl == 0 and (amount * float(t.get('price', 0))) > 10:
                # Potential missing PnL if this was a closure
                # We flag as suspicious if it's not clearly an opening (hard to tell without position history here, 
                # but we'll log it for the auditor).
                is_suspicious = True

            normalized.append({
                "id": trade_id,
                "symbol": symbol,
                "side": side,
                "price": float(t.get('price', 0)),
                "amount": amount,
                "pnl": pnl,
                "closed_at": datetime.fromtimestamp(t.get('time', 0)/1000).isoformat(),
                "is_suspicious": is_suspicious,
                "info": t
            })
        return normalized

    async def cancel_all_orders(self, symbol):
        try:
            clean_symbol = symbol.replace("/", "")
            return await self.exchange.cancel_all_orders(clean_symbol)
        except Exception as e:
            logger.error(f"Error cancelling orders for {symbol}: {e}")
            return None

    async def fetch_positions(self):
        """Fetch active positions with multiple fallbacks."""
        if Config.USE_TESTNET:
            return await self._manual_fetch_positions()
        try:
            return await self.exchange.fetch_positions()
        except Exception as e:
            logger.warning(f"CCXT fetch_positions failed: {e}. Attempting manual fetch.")
            return await self._manual_fetch_positions()

    async def _manual_fetch_positions(self):
        data = self._manual_request('GET', "/fapi/v2/positionRisk")
        if not data: return []
        
        active = []
        for p in data:
            if float(p.get('positionAmt', 0)) != 0:
                symbol_id = p['symbol']
                ccxt_sym = symbol_id
                if self.exchange.markets:
                    for sym, info in self.exchange.markets.items():
                        if info.get('id') == symbol_id:
                            ccxt_sym = sym; break
                
                active.append({
                    'symbol': ccxt_sym,
                    'contracts': float(p['positionAmt']),
                    'entryPrice': float(p['entryPrice']),
                    'unrealizedPnl': float(p['unRealizedProfit']),
                    'leverage': int(p['leverage']),
                    'info': p
                })
        return active

    async def fetch_balance(self):
        """Fetch balance with multiple fallbacks, including a direct API request."""
        if self.sim_mode:
            return {'total': {'USDT': 10000.0}, 'free': {'USDT': 10000.0}, 'info': {}}

        if Config.USE_TESTNET:
            # Skip CCXT on Demo Trading — go straight to manual for reliability
            return await self._manual_fetch_balance()
        try:
            return await self.exchange.fetch_balance()
        except Exception as e:
            logger.warning(f"CCXT fetch_balance failed: {e}. Attempting manual fetch.")
            return await self._manual_fetch_balance()

    async def _manual_fetch_balance(self):
        data = self._manual_request('GET', "/fapi/v2/balance")
        if not data: 
            logger.warning("[Exchange] Manual fetch_balance returned no data.")
            return {'total': {'USDT': 0.0}, 'free': {'USDT': 0.0}, 'info': {}}
        
        for asset in data:
            if asset.get('asset') == 'USDT':
                total = float(asset.get('balance', 0))
                free = float(asset.get('withdrawAvailable') or asset.get('availableBalance') or 0)
                # Double check total is valid
                if total < 0:
                    logger.error(f"[Exchange] CRITICAL: USDT Balance is negative ({total})!")
                return {
                    'total': {'USDT': total},
                    'free': {'USDT': free},
                    'info': asset
                }
        return {'total': {'USDT': 0.0}, 'free': {'USDT': 0.0}, 'info': {}}

    def validate_order_filters(self, symbol, amount, price=None):
        """
        Validates an order against symbol-specific filters (MIN_NOTIONAL, stepSize, etc).
        Returns (is_valid, reason)
        """
        market = self.exchange.markets.get(symbol)
        if not market:
            return False, f"Market info missing for {symbol}"
        
        limits = market.get('limits', {})
        
        # 1. Min Qty
        min_qty = limits.get('amount', {}).get('min', 0)
        if amount < min_qty:
            return False, f"Amount {amount} < Min Qty {min_qty}"
        
        # 2. Notional (Cost)
        if price:
            notional = amount * price
            min_notional = limits.get('cost', {}).get('min', 5.0)
            if notional < min_notional:
                return False, f"Notional {notional:.2f} < Min Notional {min_notional}"
        
        return True, ""

    async def create_order(self, symbol, type, side, amount, price=None, params=None):
        """Unified order placement with manual fallback for Testnet stability."""
        try:
            # Clean symbol for Testnet
            clean_symbol = symbol.replace("/", "")
            
            # Enforce precision locally using our manual market data
            amount_prec = self.amount_to_precision(symbol, amount)
            price_prec = self.price_to_precision(symbol, price) if price else None
            
            if self.sim_mode:
                logger.info(f"[SIM] Created {side} order for {symbol} @ {price or 'MARKET'}")
                return {"id": f"sim-{int(time.time())}", "status": "closed", "symbol": symbol, "side": side, "amount": amount_prec, "price": price_prec}

            if Config.USE_TESTNET:
                # Direct API Call for maximum reliability on Testnet
                return await self._manual_create_order(clean_symbol, type, side, amount_prec, price_prec, params)
            
            # Live/Normal mode: use CCXT
            return await self.exchange.create_order(symbol, type, side, float(amount_prec), float(price_prec) if price_prec else None, params)
        except Exception as e:
            logger.error(f"Order creation failed: {e}")
            # Fallback to manual even if not testnet (if we want to be safe)
            return await self._manual_create_order(symbol.replace("/", ""), type, side, amount, price, params)

    async def _manual_create_order(self, symbol, type, side, amount, price=None, params=None):
        """Low-level signed POST request to place an order."""
        base_url = "https://fapi.binance.com"
        if Config.USE_TESTNET:
            base_url = "https://demo-fapi.binance.com"
        
        endpoint = "/fapi/v1/order"
        timestamp = int(time.time() * 1000)
        
        # Normalize Side for Binance
        side_map = {
            'LONG': 'BUY',
            'BUY': 'BUY',
            'SHORT': 'SELL',
            'SELL': 'SELL'
        }
        binance_side = side_map.get(side.upper(), 'BUY')
        
        # Build payload
        payload = {
            'symbol': symbol,
            'side': binance_side,
            'type': type.upper().replace("_", ""), # stop_market -> STOPMARKET
            'quantity': amount,
            'timestamp': timestamp,
            'recvWindow': 5000
        }
        
        if type.lower() == 'limit':
            payload['price'] = price
            payload['timeInForce'] = 'GTC'
        
        if params:
            payload.update(params)
            # Normalize stopPrice if present
            if 'stopPrice' in payload and not payload['stopPrice']:
                payload['stopPrice'] = price
        
        # Sort and sign
        query_string = "&".join([f"{k}={v}" for k, v in sorted(payload.items())])
        signature = hmac.new(
            self.exchange.secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        url = f"{base_url}{endpoint}?{query_string}&signature={signature}"
        headers = {'X-MBX-APIKEY': self.exchange.apiKey}
        
        try:
            r = requests.post(url, headers=headers, timeout=10)
            if r.status_code == 200:
                return r.json()
            else:
                logger.error(f"Manual order failed: {r.status_code} {r.text}")
                return None
        except Exception as e:
            logger.error(f"Manual order exception: {e}")
            return None

    async def set_leverage(self, symbol, leverage):
        """Set leverage with manual fallback for Demo Trading."""
        if Config.USE_TESTNET:
            return await self._manual_set_leverage(symbol, leverage)
        try:
            return await self.exchange.set_leverage(leverage, symbol)
        except Exception as e:
            logger.error(f"Set leverage error for {symbol}: {e}")
            return await self._manual_set_leverage(symbol, leverage)

    async def _manual_set_leverage(self, symbol, leverage):
        """Low-level signed POST to set leverage on Demo Trading."""
        base_url = "https://fapi.binance.com"
        if Config.USE_TESTNET:
            base_url = "https://demo-fapi.binance.com"
        
        endpoint = "/fapi/v1/leverage"
        clean_symbol = symbol.replace("/", "")
        timestamp = int(time.time() * 1000)
        
        payload = {
            'symbol': clean_symbol,
            'leverage': leverage,
            'timestamp': timestamp,
            'recvWindow': 5000
        }
        
        query_string = "&".join([f"{k}={v}" for k, v in sorted(payload.items())])
        signature = hmac.new(
            self.exchange.secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        url = f"{base_url}{endpoint}?{query_string}&signature={signature}"
        headers = {'X-MBX-APIKEY': self.exchange.apiKey}
        
        try:
            r = requests.post(url, headers=headers, timeout=10)
            if r.status_code == 200:
                logger.info(f"Leverage set to {leverage}x for {symbol}")
                return r.json()
            else:
                logger.warning(f"Set leverage failed for {symbol}: {r.status_code} {r.text}")
        except Exception as e:
            logger.warning(f"Set leverage exception for {symbol}: {e}")
        return None

    def amount_to_precision(self, symbol, amount):
        try:
            market = self.exchange.markets.get(symbol)
            if market and 'limits' in market:
                step = market['limits']['amount'].get('step', 0.0001)
                rounded = round(round(float(amount) / step) * step, 8)
                precision = market['precision'].get('amount', 3)
                return f"{rounded:.{precision}f}"
            return self.exchange.amount_to_precision(symbol, amount)
        except Exception:
            return str(round(amount, 3))

    def price_to_precision(self, symbol, price):
        try:
            market = self.exchange.markets.get(symbol)
            if market and 'limits' in market:
                tick = market['limits']['price'].get('tick', 0.01)
                rounded = round(round(float(price) / tick) * tick, 8)
                precision = market['precision'].get('price', 2)
                return f"{rounded:.{precision}f}"
            return self.exchange.price_to_precision(symbol, price)
        except Exception:
            return str(round(price, 2))
