"""
Resilience utilities — shared retry logic with exponential backoff.

Used by exchange, telegram, and websocket modules to survive
transient failures without crashing the bot.
"""

import asyncio
import logging
import time
import functools
from typing import Optional, Any

logger = logging.getLogger(__name__)


async def retry_async(
    coro_func,
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,),
    default: Any = None,
    context: str = "",
    **kwargs,
):
    """
    Execute an async callable with exponential backoff retry.

    Args:
        coro_func: Async callable to execute.
        max_retries: Maximum number of retry attempts (0 = no retries).
        base_delay: Initial delay in seconds before first retry.
        max_delay: Maximum delay cap between retries.
        backoff_factor: Multiplier applied to delay after each failure.
        exceptions: Tuple of exception types to catch and retry on.
        default: Value to return if all retries are exhausted.
        context: Descriptive label for log messages.

    Returns:
        The result of coro_func, or `default` if all attempts fail.
    """
    last_exception = None
    delay = base_delay

    for attempt in range(max_retries + 1):
        try:
            return await coro_func(*args, **kwargs)
        except exceptions as e:
            last_exception = e
            if attempt < max_retries:
                logger.warning(
                    "[Resilience] %s failed (attempt %d/%d): %s. Retrying in %.1fs...",
                    context or coro_func.__name__,
                    attempt + 1,
                    max_retries + 1,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * backoff_factor, max_delay)
            else:
                logger.error(
                    "[Resilience] %s failed permanently after %d attempts: %s",
                    context or coro_func.__name__,
                    max_retries + 1,
                    e,
                )

    return default


def retry_sync(
    func,
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,),
    default: Any = None,
    context: str = "",
    **kwargs,
):
    """
    Execute a synchronous callable with exponential backoff retry.

    Same interface as retry_async but for blocking calls.
    """
    last_exception = None
    delay = base_delay

    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except exceptions as e:
            last_exception = e
            if attempt < max_retries:
                logger.warning(
                    "[Resilience] %s failed (attempt %d/%d): %s. Retrying in %.1fs...",
                    context or getattr(func, "__name__", "sync_call"),
                    attempt + 1,
                    max_retries + 1,
                    e,
                    delay,
                )
                time.sleep(delay)
                delay = min(delay * backoff_factor, max_delay)
            else:
                logger.error(
                    "[Resilience] %s failed permanently after %d attempts: %s",
                    context or getattr(func, "__name__", "sync_call"),
                    max_retries + 1,
                    e,
                )

    return default


class ServiceHealth:
    """
    Tracks the health of an external service and provides
    automatic temporary disabling with periodic recovery attempts.
    """

    def __init__(
        self,
        name: str,
        max_failures: int = 5,
        cooldown_seconds: float = 300.0,
    ):
        self.name = name
        self.max_failures = max_failures
        self.cooldown_seconds = cooldown_seconds

        self.consecutive_failures = 0
        self.last_failure_ts = 0.0
        self.disabled_until = 0.0
        self._permanently_disabled = False

    @property
    def is_available(self) -> bool:
        """True if the service should be attempted."""
        if self._permanently_disabled:
            return False
        if self.disabled_until > 0 and time.time() < self.disabled_until:
            return False
        return True

    def record_success(self):
        """Reset failure counters on a successful call."""
        self.consecutive_failures = 0
        self.disabled_until = 0.0

    def record_failure(self):
        """Record a failure. Auto-disables if threshold is exceeded."""
        self.consecutive_failures += 1
        self.last_failure_ts = time.time()

        if self.consecutive_failures >= self.max_failures:
            self.disabled_until = time.time() + self.cooldown_seconds
            logger.warning(
                "[ServiceHealth] %s temporarily disabled for %.0fs after %d consecutive failures.",
                self.name,
                self.cooldown_seconds,
                self.consecutive_failures,
            )

    def disable_permanently(self, reason: str = ""):
        """Permanently disable this service for the session."""
        self._permanently_disabled = True
        logger.error(
            "[ServiceHealth] %s permanently disabled. Reason: %s",
            self.name,
            reason or "unspecified",
        )

    def re_enable(self):
        """Manually re-enable a disabled service."""
        self._permanently_disabled = False
        self.consecutive_failures = 0
        self.disabled_until = 0.0
        logger.info("[ServiceHealth] %s re-enabled.", self.name)
