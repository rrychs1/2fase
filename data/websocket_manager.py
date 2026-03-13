import asyncio
import json
import logging
import time
import websockets
from dataclasses import dataclass
from typing import Dict, List, Optional
from config.config_loader import Config

logger = logging.getLogger(__name__)

@dataclass
class KlineEvent:
    symbol: str
    timeframe: str
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool

class WebsocketManager:
    """
    Production-grade Binance Futures Websocket Manager.
    Features: Auto-Reconnect, Exponential Backoff, Heartbeat Monitor, Data Deduplication.
    """
    def __init__(self, config: Config):
        self.config = config
        self.base_url = "wss://fstream.binance.com/ws/"
        if self.config.USE_TESTNET:
            self.base_url = "wss://stream.binancefuture.com/ws/"
            
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.event_queue = asyncio.Queue()
        
        self.is_running = False
        self.last_message_time = time.time()
        self.reconnect_attempts = 0
        self.max_retries = getattr(self.config, 'WS_MAX_RETRIES', 5)
        self.heartbeat_timeout = getattr(self.config, 'WS_HEARTBEAT_TIMEOUT', 60)
        
        # Deduplication Tracker: {(symbol, timeframe): last_kline_close_time}
        self.last_processed_timestamps: Dict[str, int] = {}
        
        # Streams we want to track
        # e.g. {"btcusdt": ["15m", "4h"]}
        self.subscriptions: Dict[str, List[str]] = {}
        
        self._receive_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

    def add_subscription(self, symbol: str, timeframes: List[str]):
        """Register streams to listen to before connecting."""
        clean_symbol = symbol.replace("/", "").lower()
        if clean_symbol not in self.subscriptions:
            self.subscriptions[clean_symbol] = []
        for tf in timeframes:
            if tf not in self.subscriptions[clean_symbol]:
                self.subscriptions[clean_symbol].append(tf)

    async def connect(self):
        """Establish connection and send subscription payloads."""
        self.is_running = True
        self.reconnect_attempts = 0
        await self._connect_and_loop()
        
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._monitor_heartbeat())

    async def _connect_and_loop(self):
        while self.is_running:
            try:
                streams = []
                for sym, tfs in self.subscriptions.items():
                    for tf in tfs:
                        streams.append(f"{sym}@kline_{tf}")
                
                if not streams:
                    logger.warning("[WS] No subscriptions defined. Pausing WS...")
                    await asyncio.sleep(5)
                    continue

                # Build combined stream URL
                stream_url = f"{self.base_url}{'/'.join(streams)}"
                
                logger.info(f"[WS] Connecting to streams: {len(streams)} active...")
                async with websockets.connect(stream_url, ping_interval=20, ping_timeout=20) as websocket:
                    self.ws = websocket
                    self.reconnect_attempts = 0
                    self.last_message_time = time.time()
                    logger.info("[WS] Connection established successfully.")
                    
                    # Blocking receive loop
                    await self._receive_loop()
            
            except Exception as e:
                logger.error(f"[WS] Connection Error: {e}")
                self.ws = None
            
            if self.is_running:
                await self._handle_reconnect()

    async def _receive_loop(self):
        """Consume messages infinitely from the active socket."""
        try:
            async for message in self.ws:
                self.last_message_time = time.time()
                await self._process_message(message)
        except websockets.exceptions.ConnectionClosed as e:
            logger.warning(f"[WS] Connection Closed: {e}")
        except Exception as e:
            logger.error(f"[WS] Receive Loop Error: {e}")

    async def _process_message(self, message: str):
        """Parse JSON Binance payload, filter duplicates, push to Queue."""
        try:
            data = json.loads(message)
            if 'e' not in data or data['e'] != 'kline':
                # Unknown or non-kline payload
                return
                
            k = data['k']
            symbol = data['s'] # eg BTCUSDT
            timeframe = k['i'] # eg 15m
            is_closed = k['x'] # True if candle is finalized
            start_time = int(k['t'])
            
            # Format generic symbol
            generic_sym = symbol
            if generic_sym.endswith("USDT"):
                generic_sym = generic_sym.replace("USDT", "/USDT")

            event = KlineEvent(
                symbol=generic_sym,
                timeframe=timeframe,
                timestamp=start_time,
                open=float(k['o']),
                high=float(k['h']),
                low=float(k['l']),
                close=float(k['c']),
                volume=float(k['v']),
                is_closed=is_closed
            )

            # Deduplication Check (Only care if it's closed)
            if is_closed:
                tracker_key = f"{generic_sym}_{timeframe}"
                last_processed = self.last_processed_timestamps.get(tracker_key, 0)
                
                if start_time <= last_processed:
                    # Duplicate or Out-Of-Order late packet. Drop it.
                    logger.debug(f"[WS] Dropped Duplicate/Stale Kline: {tracker_key} @ {start_time}")
                    return
                else:
                    self.last_processed_timestamps[tracker_key] = start_time

            # Put in queue for asynchronous consumption by BotRunner
            await self.event_queue.put(event)
            
        except json.JSONDecodeError:
            pass
        except Exception as e:
            logger.error(f"[WS] Error parsing message: {e}")

    async def _handle_reconnect(self):
        """Exponential backoff reconnect logic."""
        if self.reconnect_attempts >= self.max_retries:
            logger.critical("[WS] Max reconnect attempts reached. Websocket Engine DEAD.")
            self.is_running = False
            return
            
        self.reconnect_attempts += 1
        backoff_time = min(2 ** self.reconnect_attempts, 60)
        logger.warning(f"[WS] Reconnecting in {backoff_time}s (Attempt {self.reconnect_attempts}/{self.max_retries})...")
        await asyncio.sleep(backoff_time)

    async def _monitor_heartbeat(self):
        """Background watchdog to kill dead sockets."""
        while self.is_running:
            await asyncio.sleep(1) # Check every second for better responsiveness
            now = time.time()
            if self.ws and not self.ws.closed:
                idle_time = now - self.last_message_time
                if idle_time > self.heartbeat_timeout:
                    logger.error(f"[WS] Heartbeat timeout! No messages for {idle_time:.0f}s. Forcing reconnect...")
                    await self.ws.close() # This throws ConnectionClosed in recv loop, triggering reconnect

    async def stop(self):
        """Graceful shutdown."""
        logger.info("[WS] Halting Websocket Manager...")
        self.is_running = False
        if self.ws:
            await self.ws.close()
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
