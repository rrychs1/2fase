"""
System Health Monitor -- proactive production monitoring.

Tracks:
  - API connectivity (Exchange + Telegram)
  - Loop execution time (avg, max, slow cycle count)
  - Memory usage (RSS via psutil)
  - Uptime and iteration count

Provides:
  - get_report() for structured health snapshots
  - Periodic background logging
  - Telegram alerts on anomalies (memory spike, slow loops, API down)
  - Data for /health endpoint
"""

import time
import logging
import asyncio
import psutil
import os
from collections import deque
from datetime import datetime

logger = logging.getLogger(__name__)

# Thresholds
LOOP_SLOW_THRESHOLD_MS = 5000  # 5 seconds
MEMORY_WARNING_MB = 512
MEMORY_CRITICAL_MB = 1024
API_STALE_THRESHOLD_S = 300  # 5 minutes with no successful API call


class HealthMonitor:
    """
    Centralized health tracker for the trading bot.

    Usage:
        monitor = HealthMonitor()
        monitor.record_loop(elapsed_ms=120)
        monitor.record_api_success("exchange")
        report = monitor.get_report()
    """

    def __init__(self):
        self.start_time = time.time()
        self.process = psutil.Process(os.getpid())

        # Loop timing
        self._loop_times: deque = deque(maxlen=500)
        self._slow_loops = 0
        self._total_loops = 0

        # API tracking: {name: {"last_success": float, "last_failure": float, "failures": int}}
        self._services = {
            "exchange": {"last_success": 0.0, "last_failure": 0.0, "failures": 0},
            "telegram": {"last_success": 0.0, "last_failure": 0.0, "failures": 0},
            "websocket": {"last_success": 0.0, "last_failure": 0.0, "failures": 0},
        }

        # Anomaly dedup (avoid spamming alerts)
        self._last_alert_ts = {}

        # Background task handle
        self._task = None

    # ------------------------------------------------------------------
    #  Recording
    # ------------------------------------------------------------------

    def record_loop(self, elapsed_ms: float):
        """Record a single loop iteration duration in milliseconds."""
        self._loop_times.append(elapsed_ms)
        self._total_loops += 1
        if elapsed_ms > LOOP_SLOW_THRESHOLD_MS:
            self._slow_loops += 1

    def record_api_success(self, service: str):
        """Mark a successful API call for a service."""
        if service in self._services:
            self._services[service]["last_success"] = time.time()
            self._services[service]["failures"] = 0

    def record_api_failure(self, service: str):
        """Mark a failed API call for a service."""
        if service in self._services:
            self._services[service]["last_failure"] = time.time()
            self._services[service]["failures"] += 1

    # ------------------------------------------------------------------
    #  Queries
    # ------------------------------------------------------------------

    def get_memory_mb(self) -> float:
        """Current RSS memory usage in MB."""
        try:
            return self.process.memory_info().rss / (1024 * 1024)
        except Exception:
            return 0.0

    def get_cpu_percent(self) -> float:
        """CPU usage percentage for this process."""
        try:
            return self.process.cpu_percent(interval=0)
        except Exception:
            return 0.0

    def get_uptime_seconds(self) -> float:
        return time.time() - self.start_time

    def get_loop_stats(self) -> dict:
        """Return loop timing statistics."""
        if not self._loop_times:
            return {
                "total": self._total_loops,
                "avg_ms": 0.0,
                "max_ms": 0.0,
                "slow_count": self._slow_loops,
            }

        times = list(self._loop_times)
        return {
            "total": self._total_loops,
            "avg_ms": round(sum(times) / len(times), 1),
            "max_ms": round(max(times), 1),
            "slow_count": self._slow_loops,
        }

    def get_service_status(self) -> dict:
        """Return connectivity status for each tracked service."""
        now = time.time()
        result = {}
        for name, data in self._services.items():
            last_ok = data["last_success"]
            stale = (now - last_ok) > API_STALE_THRESHOLD_S if last_ok > 0 else False
            result[name] = {
                "status": "down" if stale or data["failures"] >= 5 else "up",
                "last_success_ago_s": round(now - last_ok, 1) if last_ok > 0 else -1,
                "consecutive_failures": data["failures"],
            }
        return result

    # ------------------------------------------------------------------
    #  Full report (used by /health endpoint + periodic log)
    # ------------------------------------------------------------------

    def get_report(self) -> dict:
        """Build a complete health snapshot."""
        memory_mb = self.get_memory_mb()
        loop_stats = self.get_loop_stats()
        services = self.get_service_status()

        # Overall status
        issues = []
        if memory_mb > MEMORY_CRITICAL_MB:
            issues.append(f"memory_critical ({memory_mb:.0f}MB)")
        elif memory_mb > MEMORY_WARNING_MB:
            issues.append(f"memory_high ({memory_mb:.0f}MB)")

        for svc_name, svc_data in services.items():
            if svc_data["status"] == "down":
                issues.append(f"{svc_name}_down")

        if loop_stats["avg_ms"] > LOOP_SLOW_THRESHOLD_MS:
            issues.append(f"loops_slow (avg {loop_stats['avg_ms']:.0f}ms)")

        overall = "degraded" if issues else "healthy"

        return {
            "status": overall,
            "timestamp": datetime.now().isoformat(),
            "uptime_s": round(self.get_uptime_seconds(), 0),
            "memory_mb": round(memory_mb, 1),
            "cpu_percent": round(self.get_cpu_percent(), 1),
            "loop": loop_stats,
            "services": services,
            "issues": issues,
        }

    # ------------------------------------------------------------------
    #  Anomaly detection
    # ------------------------------------------------------------------

    def detect_anomalies(self) -> list:
        """Return a list of anomaly strings if any thresholds are breached."""
        anomalies = []
        memory_mb = self.get_memory_mb()

        if memory_mb > MEMORY_CRITICAL_MB:
            anomalies.append(
                f"CRITICAL: Memory usage at {memory_mb:.0f}MB "
                f"(threshold: {MEMORY_CRITICAL_MB}MB)"
            )
        elif memory_mb > MEMORY_WARNING_MB:
            anomalies.append(
                f"WARNING: Memory usage at {memory_mb:.0f}MB "
                f"(threshold: {MEMORY_WARNING_MB}MB)"
            )

        services = self.get_service_status()
        for svc_name, svc_data in services.items():
            if svc_data["status"] == "down":
                anomalies.append(
                    f"WARNING: {svc_name} appears down "
                    f"(failures: {svc_data['consecutive_failures']}, "
                    f"last success: {svc_data['last_success_ago_s']}s ago)"
                )

        loop_stats = self.get_loop_stats()
        if loop_stats["avg_ms"] > LOOP_SLOW_THRESHOLD_MS:
            anomalies.append(
                f"WARNING: Loop avg {loop_stats['avg_ms']:.0f}ms "
                f"exceeds threshold ({LOOP_SLOW_THRESHOLD_MS}ms)"
            )

        return anomalies

    # ------------------------------------------------------------------
    #  Background periodic reporter
    # ------------------------------------------------------------------

    async def start_periodic_report(self, interval_s: float = 300, telegram=None):
        """
        Start a background task that logs health reports periodically
        and sends Telegram alerts on anomalies.
        """
        self._task = asyncio.create_task(self._report_loop(interval_s, telegram))

    async def _report_loop(self, interval_s: float, telegram):
        """Internal loop -- never crashes, runs until cancelled."""
        while True:
            try:
                await asyncio.sleep(interval_s)

                report = self.get_report()

                # Always log the health summary
                logger.info(
                    "[HEALTH] status=%s | mem=%.0fMB | cpu=%.1f%% | "
                    "loops=%d (avg %.0fms, slow %d) | issues=%s",
                    report["status"],
                    report["memory_mb"],
                    report["cpu_percent"],
                    report["loop"]["total"],
                    report["loop"]["avg_ms"],
                    report["loop"]["slow_count"],
                    report["issues"] or "none",
                )

                # Persist report to disk for /health endpoint
                try:
                    import json

                    health_path = os.path.join(
                        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data",
                        "health_state.json",
                    )
                    with open(health_path, "w", encoding="utf-8") as f:
                        json.dump(report, f)
                except Exception as write_err:
                    logger.debug(
                        "[HEALTH] Failed to write health_state.json: %s", write_err
                    )

                # Alert on anomalies via Telegram (deduplicated)
                if telegram:
                    anomalies = self.detect_anomalies()
                    for anomaly in anomalies:
                        dedup_key = anomaly.split(":")[0]
                        now = time.time()
                        last = self._last_alert_ts.get(dedup_key, 0)
                        if now - last > 900:  # Max 1 alert per anomaly per 15 min
                            self._last_alert_ts[dedup_key] = now
                            try:
                                await telegram.warning(
                                    f"[HEALTH] {anomaly}",
                                    dedup_key=f"health_{dedup_key}",
                                )
                            except Exception:
                                pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("[HEALTH] Report loop error: %s", e)

    def stop(self):
        """Cancel the background task."""
        if self._task and not self._task.done():
            self._task.cancel()
