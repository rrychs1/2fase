import time
import logging
from collections import deque

logger = logging.getLogger(__name__)


class CircuitBreaker:
    def __init__(self, threshold=5, window_seconds=300, config=None):
        """
        threshold: Number of errors before tripping.
        window_seconds: Time window to look back for errors.
        config: Optional Config object.  When provided, CIRCUIT_BREAKER_COOLDOWN_SEC
                overrides the default 600-second cooldown (L-05 fix).
        """
        self.threshold = threshold
        self.window_seconds = window_seconds
        self.errors = deque()  # Stores timestamps of errors
        self.tripped = False
        self.tripped_at = 0
        # L-05: read from config if available so operators can tune via env var
        self.cooldown_seconds = (
            getattr(config, "CIRCUIT_BREAKER_COOLDOWN_SEC", 600)
            if config is not None
            else 600
        )

    def report_error(self, error_type="exchange"):
        """Record a serious error and check if we should trip."""
        now = time.time()
        self.errors.append(now)
        self._clean_window(now)

        if len(self.errors) >= self.threshold:
            if not self.tripped:
                logger.critical(
                    f"CIRCUIT BREAKER TRIPPED! {len(self.errors)} errors in {self.window_seconds}s."
                )
                self.tripped = True
                self.tripped_at = now
            return True
        return False

    def is_tripped(self) -> bool:
        """Check if the breaker is currently tripped."""
        if not self.tripped:
            return False

        now = time.time()
        # Auto-reset after cooldown
        if now - self.tripped_at > self.cooldown_seconds:
            logger.info("Circuit Breaker auto-resetting after cooldown.")
            self.tripped = False
            self.errors.clear()
            return False

        return True

    def _clean_window(self, now):
        """Remove errors outside the current window."""
        while self.errors and (now - self.errors[0] > self.window_seconds):
            self.errors.popleft()

    def reset(self):
        """Manual reset of the circuit breaker."""
        self.tripped = False
        self.errors.clear()
        logger.info("Circuit Breaker reset manually.")
