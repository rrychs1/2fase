import asyncio
import json
import logging
import time
import websockets
from dataclasses import dataclass
from typing import Dict, List, Optional
from config.config_loader import Config
from common.resilience import ServiceHealth

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

    Fixes applied:
      C-01 — _connect_and_loop and _monitor_heartbeat are proper async tasks (not awaited
              inline), so both run concurrently from the start.
      C-02 — Combined-stream URL uses ?streams= query param; single-stream uses /ws/ path.
              The combined-stream wrapper {"stream":..., "data":{...}} is parsed correctly.
      C-03 — Heartbeat correctly restarts the connection because _connect_and_loop runs as
              a task whose while-loop iterates after ConnectionClosed exits _receive_loop.
              ws=None is set after close() to make state unambiguous.
      C-04 — connect() creates both tasks before returning; no blocking await.
      H-01 — Fast-path for open candles: parse k['x'] before allocating KlineEvent.
      H-02 — Hot-path debug log uses %-style formatting (no f-string evaluated eagerly).
      M-01 — latest_open is capped at max(64, 4 * subscription_count) entries.
      M-02 — asyncio.CancelledError is explicitly re-raised in _connect_and_loop so task
              cancellation works correctly on shutdown.
    """

    def __init__(self, config: Config):
        self.config = config

        # C-02: base URLs differ for combined vs single stream
        if self.config.USE_TESTNET:
            self._ws_base = "wss://stream.binancefuture.com"
        else:
            self._ws_base = "wss://fstream.binance.com"

        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.event_queue: asyncio.Queue = asyncio.Queue()

        self.is_running = False
        self.last_message_time = time.time()
        self.reconnect_attempts = 0
        self.max_retries = getattr(self.config, "WS_MAX_RETRIES", 5)
        self.heartbeat_timeout = getattr(self.config, "WS_HEARTBEAT_TIMEOUT", 60)
        self.health = ServiceHealth("Websocket", max_failures=20, cooldown_seconds=60)

        # Deduplication Tracker: {(symbol, timeframe): last_kline_close_time}
        self.last_processed_timestamps: Dict[str, int] = {}

        # Streams we want to track — e.g. {"btcusdt": ["15m", "4h"]}
        self.subscriptions: Dict[str, List[str]] = {}

        # H-01: latest open-candle data (raw dict, not KlineEvent)
        # M-01: bounded — trimmed to _latest_open_max_size entries
        self.latest_open: Dict[str, dict] = {}
        self._latest_open_max_size: int = 64  # updated in connect()

        # C-01 / C-04: task handles — initialised here so stop() is always safe
        self._connect_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

    def add_subscription(self, symbol: str, timeframes: List[str]):
        """Register streams to listen to before connecting."""
        clean_symbol = symbol.replace("/", "").lower()
        if clean_symbol not in self.subscriptions:
            self.subscriptions[clean_symbol] = []
        for tf in timeframes:
            if tf not in self.subscriptions[clean_symbol]:
                self.subscriptions[clean_symbol].append(tf)

    def _build_stream_url(self, streams: List[str]) -> str:
        """
        C-02: Build the correct Binance Futures websocket URL.
        - Single stream  → wss://<base>/ws/<stream>
        - Multi stream   → wss://<base>/stream?streams=<a>/<b>/...
        """
        if len(streams) == 1:
            return f"{self._ws_base}/ws/{streams[0]}"
        return f"{self._ws_base}/stream?streams={'/'.join(streams)}"

    async def connect(self):
        """
        C-04: Launch both the connect loop and heartbeat as independent tasks.
        Returns immediately; the tasks run in the background.
        """
        self.is_running = True
        self.reconnect_attempts = 0

        # M-01: size the latest_open cache relative to subscription count
        sub_count = sum(len(tfs) for tfs in self.subscriptions.values())
        self._latest_open_max_size = max(64, 4 * sub_count)

        # C-04: create tasks (never await them here)
        if self._connect_task is None or self._connect_task.done():
            self._connect_task = asyncio.create_task(self._connect_and_loop())

        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._monitor_heartbeat())

    async def _connect_and_loop(self):
        """
        C-01: Standalone async task — runs as long as self.is_running.
        C-04: Called via create_task, never awaited directly.
        M-02: Re-raises CancelledError so task cancellation propagates correctly.
        """
        while self.is_running:
            try:
                streams = [
                    f"{sym}@kline_{tf}"
                    for sym, tfs in self.subscriptions.items()
                    for tf in tfs
                ]

                if not streams:
                    logger.warning("[WS] No subscriptions defined. Pausing WS...")
                    await asyncio.sleep(5)
                    continue

                # C-02: use the correct URL format
                stream_url = self._build_stream_url(streams)

                logger.info("[WS] Connecting to %d stream(s): %s", len(streams), stream_url)
                async with websockets.connect(
                    stream_url, ping_interval=20, ping_timeout=20
                ) as websocket:
                    self.ws = websocket
                    self.reconnect_attempts = 0
                    self.last_message_time = time.time()
                    self.health.record_success()
                    logger.info("[WS] Connection established successfully.")

                    # Blocking receive loop — exits on ConnectionClosed
                    await self._receive_loop()

            except asyncio.CancelledError:
                # M-02: always propagate task cancellation
                raise
            except Exception as e:
                logger.error("[WS] Connection Error: %s", e)
                self.health.record_failure()
            finally:
                self.ws = None  # C-03: clear stale ws reference after any exit

            if self.is_running:
                await self._handle_reconnect()

    async def _receive_loop(self):
        """Consume messages infinitely from the active socket."""
        try:
            async for message in self.ws:
                self.last_message_time = time.time()
                await self._process_message(message)
        except websockets.exceptions.ConnectionClosed as e:
            logger.warning("[WS] Connection Closed: %s", e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("[WS] Receive Loop Error: %s", e)

    async def _process_message(self, message: str):
        """
        Parse JSON Binance payload, filter duplicates, push closed candles to Queue.

        C-02: Handles both single-stream payload  {"e": "kline", ...}
              and combined-stream wrapper          {"stream": "...", "data": {...}}
        H-01: Fast-path for open candles — skip KlineEvent allocation entirely.
        H-02: Debug log uses %-style formatting.
        M-01: latest_open trimmed to _latest_open_max_size.
        """
        try:
            data = json.loads(message)

            # C-02: unwrap combined-stream envelope if present
            if "data" in data and "stream" in data:
                data = data["data"]

            if data.get("e") != "kline":
                return

            k = data["k"]
            is_closed: bool = k["x"]  # H-01: parse this FIRST, cheaply

            symbol = data["s"]  # e.g. BTCUSDT
            timeframe = k["i"]  # e.g. 15m
            start_time = int(k["t"])

            # Format generic symbol (BTC/USDT)
            generic_sym = symbol
            if generic_sym.endswith("USDT"):
                generic_sym = generic_sym.replace("USDT", "/USDT")

            if not is_closed:
                # H-01: open candle — store lightweight raw dict, skip KlineEvent
                tracker_key = f"{generic_sym}_{timeframe}"
                self.latest_open[tracker_key] = {
                    "symbol": generic_sym,
                    "timeframe": timeframe,
                    "timestamp": start_time,
                    "open": float(k["o"]),
                    "high": float(k["h"]),
                    "low": float(k["l"]),
                    "close": float(k["c"]),
                    "volume": float(k["v"]),
                }
                # M-01: evict oldest entries when cache exceeds limit
                if len(self.latest_open) > self._latest_open_max_size:
                    oldest_key = next(iter(self.latest_open))
                    del self.latest_open[oldest_key]

                # H-02: %-style log — f-string not evaluated when log level > DEBUG
                logger.debug(
                    "[WS] Coalesced open kline for %s @ %s", tracker_key, start_time
                )
                return

            # Closed candle — build full KlineEvent and deduplicate
            tracker_key = f"{generic_sym}_{timeframe}"
            last_processed = self.last_processed_timestamps.get(tracker_key, 0)

            if start_time <= last_processed:
                logger.debug(
                    "[WS] Dropped Duplicate/Stale Kline: %s @ %s", tracker_key, start_time
                )
                return

            self.last_processed_timestamps[tracker_key] = start_time

            event = KlineEvent(
                symbol=generic_sym,
                timeframe=timeframe,
                timestamp=start_time,
                open=float(k["o"]),
                high=float(k["h"]),
                low=float(k["l"]),
                close=float(k["c"]),
                volume=float(k["v"]),
                is_closed=True,
            )
            await self.event_queue.put(event)

        except json.JSONDecodeError:
            pass
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("[WS] Error parsing message: %s", e)

    async def _handle_reconnect(self):
        """Exponential backoff reconnect logic — never permanently gives up."""
        self.reconnect_attempts += 1

        if self.reconnect_attempts <= self.max_retries:
            backoff_time = min(2 ** self.reconnect_attempts, 60)
        else:
            backoff_time = 120
            logger.warning(
                "[WS] Max reconnect attempts reached. Entering extended recovery mode "
                "(retry every %ds). The bot continues running.",
                backoff_time,
            )
            self.reconnect_attempts = 0  # Reset so we keep trying indefinitely

        logger.warning(
            "[WS] Reconnecting in %ds (Attempt %d/%d)...",
            backoff_time,
            self.reconnect_attempts,
            self.max_retries,
        )
        await asyncio.sleep(backoff_time)

    async def _monitor_heartbeat(self):
        """
        C-03: Background watchdog. After ws.close(), ConnectionClosed is raised
        inside _receive_loop, causing _connect_and_loop's while-loop to iterate
        and reconnect — no zombie state possible when both run as tasks.
        """
        while self.is_running:
            await asyncio.sleep(1)
            now = time.time()

            is_ws_open = False
            if self.ws:
                if hasattr(self.ws, "state"):
                    is_ws_open = self.ws.state.name == "OPEN"
                elif hasattr(self.ws, "open"):
                    is_ws_open = self.ws.open
                else:
                    is_ws_open = not getattr(self.ws, "closed", False)

            if is_ws_open:
                idle_time = now - self.last_message_time
                if idle_time > self.heartbeat_timeout:
                    logger.error(
                        "[WS] Heartbeat timeout! No messages for %.0fs. Forcing reconnect...",
                        idle_time,
                    )
                    # C-03: closing triggers ConnectionClosed in _receive_loop,
                    # which causes _connect_and_loop to reconnect on its next iteration.
                    try:
                        await self.ws.close()
                    except Exception:
                        pass
                    self.ws = None

    async def stop(self):
        """Graceful shutdown — cancels both background tasks."""
        logger.info("[WS] Halting Websocket Manager...")
        self.is_running = False

        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None

        for task in (self._connect_task, self._heartbeat_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
