import ccxt.async_support as ccxt
import asyncio
import logging
import requests
import pandas as pd
import hmac
import hashlib
import time
from config.config_loader import Config

logger = logging.getLogger(__name__)

class ExchangeClient:
    def __init__(self):
        self.exchange = None
        self.public_exchange = None
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


    def _initialize_clients(self):
        # Authenticated Client config
        config = {
            'apiKey': Config.BINANCE_API_KEY,
            'secret': Config.BINANCE_SECRET_KEY,
            'enableRateLimit': True,
        }
        
        self.exchange = ccxt.binanceusdm(config)
        
        # Public Client config
        public_config = {
            'enableRateLimit': True,
        }
        self.public_exchange = ccxt.binanceusdm(public_config)

        if Config.USE_TESTNET:
            demo_fapi = 'https://demo-fapi.binance.com/fapi/v1'
            for client in [self.exchange, self.public_exchange]:
                # Override URLs to Binance Demo Trading (replaces deprecated testnet)
                client.urls['api']['public'] = demo_fapi
                client.urls['api']['private'] = demo_fapi
                client.urls['api']['fapiPublic'] = demo_fapi
                client.urls['api']['fapiPrivate'] = demo_fapi
            
            logger.info("Demo Trading mode enabled with fapi overrides.")

    async def init(self):
        """Initialize and load markets asynchronously with manual fallback."""
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
                    symbol_id = s['symbol'] # BTCUSDT
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
                                'max': float(lot_size.get('maxQty', 1000000))
                            },
                            'price': {
                                'min': float(price_filter.get('minPrice', 0)),
                                'max': float(price_filter.get('maxPrice', 1000000))
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
        try:
            clean_symbol = symbol.replace("/", "") if symbol else None
            return await self.exchange.fetch_open_orders(clean_symbol)
        except Exception as e:
            logger.error(f"Error fetching open orders: {e}")
            return []

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
        """Low-level signed request to fetch positions."""
        base_url = "https://fapi.binance.com"
        if Config.USE_TESTNET:
            base_url = "https://demo-fapi.binance.com"
        
        endpoint = "/fapi/v2/positionRisk"
        timestamp = int(time.time() * 1000)
        query_string = f"timestamp={timestamp}"
        
        signature = hmac.new(
            self.exchange.secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        url = f"{base_url}{endpoint}?{query_string}&signature={signature}"
        headers = {'X-MBX-APIKEY': self.exchange.apiKey}
        
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                active = []
                for p in data:
                    # Binance returns symbol strings like 'BTCUSDT'
                    # We need to normalize back to CCXT style 'BTC/USDT' if possible
                    # but for now we filter by contracts
                    if float(p.get('positionAmt', 0)) != 0:
                        # Dynamic mapping from symbols loaded in init()
                        symbol_id = p['symbol']
                        ccxt_sym = symbol_id
                        # Try to find the CCXT symbol (e.g. BTC/USDT) from the API ID (BTCUSDT)
                        if self.exchange.markets:
                            for sym, info in self.exchange.markets.items():
                                if info.get('id') == symbol_id:
                                    ccxt_sym = sym
                                    break
                        
                        active.append({
                            'symbol': ccxt_sym,
                            'contracts': float(p['positionAmt']),
                            'entryPrice': float(p['entryPrice']),
                            'unrealizedPnl': float(p['unRealizedProfit']),
                            'leverage': int(p['leverage']),
                            'info': p
                        })
                return active
            else:
                logger.error(f"Manual positions fetch failed: {r.status_code}")
        except Exception as e:
            logger.error(f"Manual positions fetch exception: {e}")
        return []

    async def fetch_balance(self):
        """Fetch balance with multiple fallbacks, including a direct API request."""
        try:
            # Try CCXT first
            return await self.exchange.fetch_balance()
        except Exception as e:
            logger.warning(f"CCXT fetch_balance failed: {e}. Attempting manual fetch.")
            return await self._manual_fetch_balance()

    async def _manual_fetch_balance(self):
        """Low-level signed request to fetch balance without depending on CCXT market loading."""
        base_url = "https://fapi.binance.com"
        if Config.USE_TESTNET:
            base_url = "https://demo-fapi.binance.com"
        
        endpoint = "/fapi/v2/balance"
        timestamp = int(time.time() * 1000)
        query_string = f"timestamp={timestamp}"
        
        signature = hmac.new(
            self.exchange.secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        url = f"{base_url}{endpoint}?{query_string}&signature={signature}"
        headers = {'X-MBX-APIKEY': self.exchange.apiKey}
        
        try:
            # We use asyncio + requests (could use aiohttp but requests is already here)
            # For a bot iteration, a blocking request is acceptable as long as it has a timeout.
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                total_usdt = 0.0
                for b in data:
                    if b.get('asset') == 'USDT':
                        total_usdt = float(b.get('balance', 0))
                        break
                return {'total': {'USDT': total_usdt}, 'info': data}
            else:
                logger.error(f"Manual balance fetch failed: {r.status_code} {r.text}")
        except Exception as e:
            logger.error(f"Manual balance fetch exception: {e}")
        
        return {'total': {'USDT': 0.0}, 'info': {}}

    async def create_order(self, symbol, type, side, amount, price=None, params=None):
        """Unified order placement with manual fallback for Testnet stability."""
        try:
            # Clean symbol for Testnet
            clean_symbol = symbol.replace("/", "")
            
            # Enforce precision locally using our manual market data
            amount_prec = self.amount_to_precision(symbol, amount)
            price_prec = self.price_to_precision(symbol, price) if price else None
            
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
        try:
            # We use the unified symbol because manual markets are keyed by it
            return await self.exchange.set_leverage(leverage, symbol)
        except Exception as e:
            logger.error(f"Set leverage error for {symbol}: {e}")

    def amount_to_precision(self, symbol, amount):
        try:
            # If markets were manually injected, CCXT will use them
            return self.exchange.amount_to_precision(symbol, amount)
        except Exception:
            return str(round(amount, 3)) # Safe fallback

    def price_to_precision(self, symbol, price):
        try:
            return self.exchange.price_to_precision(symbol, price)
        except Exception:
            return str(round(price, 2)) # Safe fallback
